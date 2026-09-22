from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
import structlog

from database import AsyncSessionLocal
from models.all_models import DataSource, SourceType
from services import pii_classifier
from services.tenant_context import tenant_scoped
from services.source_lock import acquire_source_lock, describe_holder, format_lock_denial, SourceLockHeld

log = structlog.get_logger()

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


@tenant_scoped
class SchemaProfiler:
    def __init__(self, tenant_id: str, source_id: str, agent_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.source_id = source_id
        self.agent_id = agent_id
        # Transient per-call sample values, {table: {column: [values]}}, filled
        # by the profiler branches from data they already loaded and consumed
        # by _finalize(). Never persisted: a snapshot holding sample PII would
        # itself be the leak Item #10 exists to prevent.
        self._samples: dict = {}

    def _finalize(self, schema: dict, old_snapshot: dict | None) -> dict:
        """Classify every column, then reinstate any manual overrides from
        the previous snapshot so a re-profile cannot silently revert an
        engineer's correction. Samples are dropped afterwards."""
        pii_classifier.classify_snapshot(schema, self._samples)
        pii_classifier.merge_manual_overrides(old_snapshot, schema)
        self._samples = {}
        return schema

    async def _get_source(self, db) -> DataSource:
        r = await db.execute(select(DataSource).where(
            DataSource.id == self.source_id,
            DataSource.tenant_id == self.tenant_id
        ))
        return r.scalars().first()

    async def profile(self) -> dict:
        async with AsyncSessionLocal() as db:
            source = await self._get_source(db)
            if not source:
                return {"error": "Source not found"}
            try:
                async with acquire_source_lock(self.source_id, self.agent_id):
                    schema = await self._profile_source(source)
                    old_snapshot = source.schema_snapshot or {}
                    schema = self._finalize(schema, old_snapshot)
                    source.schema_snapshot = schema
                    source.last_profiled_at = utcnow()
                    await db.commit()
                    log.info("schema_profiled", source_id=self.source_id)
                    return {
                        "source_id": self.source_id,
                        "source_name": source.name,
                        "source_type": source.source_type,
                        "profiled_at": utcnow().isoformat(),
                        "schema": schema
                    }
            except SourceLockHeld as e:
                holder = await describe_holder(db, e.holder_agent_id)
                return {"error": format_lock_denial(self.source_id, holder, e.started_at_iso),
                        "source_id": self.source_id, "lock_conflict": True}
            except Exception as e:
                log.error("profile_error", source_id=self.source_id, error=str(e))
                return {"error": str(e), "source_id": self.source_id}

    async def detect_drift(self) -> dict:
        async with AsyncSessionLocal() as db:
            source = await self._get_source(db)
            if not source:
                return {"error": "Source not found"}
            old = source.schema_snapshot or {}
            if not old:
                return {"message": "No previous snapshot. Run profile first.", "drift": False}
            try:
                async with acquire_source_lock(self.source_id, self.agent_id):
                    current = await self._profile_source(source)
                    drift = self._compare_schemas(old, current)
                    if drift["has_drift"]:
                        source.schema_snapshot = self._finalize(current, old)
                        source.last_profiled_at = utcnow()
                        await db.commit()
                    return drift
            except SourceLockHeld as e:
                holder = await describe_holder(db, e.holder_agent_id)
                return {"error": format_lock_denial(self.source_id, holder, e.started_at_iso),
                        "lock_conflict": True}
            except Exception as e:
                return {"error": str(e)}

    async def _profile_source(self, source: DataSource) -> dict:
        t = source.source_type
        cfg = source.connection_config

        if t == SourceType.POSTGRES:
            return await self._profile_postgres(cfg)
        if t in (SourceType.CSV, SourceType.EXCEL, SourceType.JSON):
            return await self._profile_file(cfg, t)
        if t == SourceType.MYSQL:
            return await self._profile_mysql(cfg)
        return {"note": f"Profiling not yet implemented for {t}"}

    async def _profile_postgres(self, cfg: dict) -> dict:
        import asyncpg
        user = cfg.get("username", cfg.get("user", ""))
        dsn = f"postgresql://{user}:{cfg['password']}@{cfg['host']}:{cfg.get('port',5432)}/{cfg['database']}"
        schema = cfg.get("schema", "public")
        conn = await asyncpg.connect(dsn)
        tables_rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=$1 AND table_type='BASE TABLE'", schema
        )
        result = {}
        for t_row in tables_rows:
            tbl = t_row["table_name"]
            cols = await conn.fetch(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema=$1 AND table_name=$2 ORDER BY ordinal_position",
                schema, tbl
            )
            count = await conn.fetchrow(f'SELECT COUNT(*) cnt FROM "{schema}"."{tbl}"')
            result[tbl] = {
                "columns": [dict(c) for c in cols],
                "row_count": count["cnt"]
            }
            # One bounded read per table for value-based PII detection. Same
            # quoting as the COUNT(*) above -- this method's identifier
            # handling is a known Item #7 finding and is not changed here.
            sample_rows = await conn.fetch(
                f'SELECT * FROM "{schema}"."{tbl}" LIMIT {pii_classifier.VALUE_SAMPLE_SIZE}')
            if sample_rows:
                self._samples[tbl] = {
                    k: [r[k] for r in sample_rows if r[k] is not None]
                    for k in sample_rows[0].keys()
                }
        await conn.close()
        return result

    async def _profile_file(self, cfg: dict, source_type: SourceType) -> dict:
        import pandas as pd
        fp = cfg.get("file_path", "")
        if source_type == SourceType.CSV:
            df = pd.read_csv(fp, nrows=10000)
        elif source_type == SourceType.EXCEL:
            df = pd.read_excel(fp, nrows=10000)
        else:
            df = pd.read_json(fp)
        # Value samples for PII detection, from the frame already in memory --
        # no extra read. Bounded, non-null, and discarded after classification.
        self._samples["main"] = {
            c: df[c].dropna().head(pii_classifier.VALUE_SAMPLE_SIZE).tolist()
            for c in df.columns
        }
        return {
            "main": {
                "columns": [
                    {"column_name": c, "data_type": str(df[c].dtype),
                     "is_nullable": "YES" if df[c].isnull().any() else "NO",
                     "null_count": int(df[c].isnull().sum()),
                     "unique_count": int(df[c].nunique())}
                    for c in df.columns
                ],
                "row_count": len(df)
            }
        }

    async def _profile_mysql(self, cfg: dict) -> dict:
        import aiomysql
        conn = await aiomysql.connect(
            host=cfg["host"], port=int(cfg.get("port", 3306)),
            user=cfg.get("username", cfg.get("user", "")), password=cfg["password"], db=cfg["database"]
        )
        result = {}
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            tables = [r[0] for r in await cur.fetchall()]
            for tbl in tables:
                await cur.execute(f"DESCRIBE `{tbl}`")
                cols = await cur.fetchall()
                await cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
                count = (await cur.fetchone())[0]
                result[tbl] = {
                    "columns": [{"column_name": c[0], "data_type": c[1],
                                 "is_nullable": c[2]} for c in cols],
                    "row_count": count
                }
        conn.close()
        return result

    def _compare_schemas(self, old: dict, new: dict) -> dict:
        added_tables, removed_tables = [], []
        column_changes = {}

        old_tbls = set(old.keys())
        new_tbls = set(new.keys())
        added_tables = list(new_tbls - old_tbls)
        removed_tables = list(old_tbls - new_tbls)

        for tbl in old_tbls & new_tbls:
            old_cols = {c["column_name"]: c for c in old[tbl].get("columns", [])}
            new_cols = {c["column_name"]: c for c in new[tbl].get("columns", [])}
            added = list(set(new_cols) - set(old_cols))
            removed = list(set(old_cols) - set(new_cols))
            type_changed = [
                {"column": c, "old_type": old_cols[c]["data_type"],
                 "new_type": new_cols[c]["data_type"]}
                for c in (set(old_cols) & set(new_cols))
                if old_cols[c]["data_type"] != new_cols[c]["data_type"]
            ]
            if added or removed or type_changed:
                column_changes[tbl] = {
                    "added_columns": added,
                    "removed_columns": removed,
                    "type_changes": type_changed
                }

        has_drift = bool(added_tables or removed_tables or column_changes)
        return {
            "has_drift": has_drift,
            "added_tables": added_tables,
            "removed_tables": removed_tables,
            "column_changes": column_changes,
            "summary": f"{'Drift detected' if has_drift else 'No drift'}: "
                       f"{len(added_tables)} tables added, {len(removed_tables)} removed, "
                       f"{len(column_changes)} tables with column changes"
        }