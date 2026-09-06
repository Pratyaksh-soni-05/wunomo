import re
import time
import structlog
from datetime import datetime, timezone
from sqlalchemy import text, select

import asyncpg

from database import AsyncSessionLocal
from models.all_models import DataSource
from modules.governance.audit_trail import AuditTrail
from modules.transformation import sql_guard
from services.tenant_context import tenant_scoped

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


MAX_ROWS_HARD_CAP = 100_000
DEFAULT_ROW_LIMIT = 10_000

# How long a single query may run on the remote server, in seconds. The
# `timeout=30` already passed to asyncpg.connect() is the CONNECTION timeout —
# it bounds how long establishing the socket may take and then stops applying,
# so a query that connects instantly and then runs forever was never bounded by
# it. This is the one that bounds execution, and it is the backstop for the
# resource-exhaustion cases the parser cannot see: the parser can reject
# `pg_sleep(30)` and a cartesian join, but it cannot tell that a legitimately
# shaped aggregate over a billion rows will never finish.
STATEMENT_TIMEOUT_SECONDS = 30


@tenant_scoped
class SqlRunner:
    """
    Executes SQL against a registered DataSource with full safety controls.

    Safety layers:
      1. Parse-tree guard   — single read-only SELECT, no catalog access, no
                              timing/IO/egress functions, no cartesian joins
                              (modules/transformation/sql_guard.py)
      2. LIMIT injection    — added when the query's ROOT does not bound itself
      3. Statement timeout  — bounds execution, not just connection
      4. Hard row cap       — slices result to MAX_ROWS_HARD_CAP
      5. Audit trail        — every execution is logged

    Layer 1 replaced a keyword blocklist that allowed all 17 payloads in the
    adversarial battery in tests/test_sql_sandbox.py while rejecting three
    ordinary queries. It narrows, but does not eliminate, the caveat below.

    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    async def run_on_source(
        self,
        source_id: str,
        sql: str,
        params: dict | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
        actor: str = "agent",
    ) -> dict:
        log.info(
            "sql_runner.run_on_source",
            tenant_id=self.tenant_id,
            source_id=source_id,
            actor=actor,
        )

        safety = self._check_safety(sql)
        if "error" in safety:
            return safety

        effective_limit = min(row_limit, MAX_ROWS_HARD_CAP)
        sql_with_limit = self._inject_limit(sql, effective_limit, safety["has_root_limit"])

        source_result = await self._load_source(source_id)
        if "error" in source_result:
            return source_result
        source = source_result["source"]

        source_type = (
            source.source_type.value
            if hasattr(source.source_type, "value")
            else str(source.source_type)
        )

        start = time.monotonic()
        try:
            if source_type == "postgres":
                result = await self._run_postgres(
                    source.connection_config,
                    sql_with_limit,
                    params,
                )
            elif source_type == "mysql":
                result = await self._run_mysql(
                    source.connection_config,
                    sql_with_limit,
                    params,
                )
            else:
                return {
                    "error": f"SqlRunner does not support source type '{source_type}'."
                }
        except Exception as exc:
            log.error("sql_runner.execution_error", error=str(exc))
            return {"error": f"SQL execution failed: {str(exc)}"}

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        rows = result["rows"]
        truncated = len(rows) >= effective_limit
        rows = rows[:MAX_ROWS_HARD_CAP]

        await AuditTrail(self.tenant_id).log_action(
            actor=actor,
            action="sql.executed",
            resource_type="source",
            resource_id=source_id,
            payload={
                "row_count": len(rows),
                "truncated": truncated,
                "duration_ms": duration_ms,
            },
        )

        log.info(
            "sql_runner.run_on_source.done",
            row_count=len(rows),
            duration_ms=duration_ms,
            truncated=truncated,
        )
        return {
            "rows": rows,
            "columns": result["columns"],
            "row_count": len(rows),
            "truncated": truncated,
            "duration_ms": duration_ms,
            "source_id": source_id,
            "executed_sql": sql_with_limit,
        }

    async def run_internal(
        self,
        sql: str,
        params: dict | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
    ) -> dict:
        log.info("sql_runner.run_internal", tenant_id=self.tenant_id)

        safety = self._check_safety(sql)
        if "error" in safety:
            return safety

        effective_limit = min(row_limit, MAX_ROWS_HARD_CAP)
        sql_with_limit = self._inject_limit(sql, effective_limit, safety["has_root_limit"])

        start = time.monotonic()
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(text(sql_with_limit), params or {})
                rows_raw = result.fetchall()
                columns = list(result.keys()) if rows_raw is not None else []

            rows = [dict(zip(columns, row)) for row in rows_raw]
            rows = rows[:MAX_ROWS_HARD_CAP]
        except Exception as exc:
            log.error("sql_runner.run_internal.error", error=str(exc))
            return {"error": f"Internal SQL execution failed: {str(exc)}"}

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "truncated": len(rows) >= effective_limit,
            "duration_ms": duration_ms,
            "executed_sql": sql_with_limit,
        }

    async def dry_run(self, source_id: str, sql: str) -> dict:
        safety = self._check_safety(sql)
        if "error" in safety:
            return safety

        source_result = await self._load_source(source_id)
        if "error" in source_result:
            return source_result
        source = source_result["source"]

        source_type = (
            source.source_type.value
            if hasattr(source.source_type, "value")
            else str(source.source_type)
        )

        # EXPLAIN is prepended HERE, by us, and never accepted from the caller —
        # the guard rejects any EXPLAIN in the submitted SQL (it parses as an
        # unrecognised Command). That is what makes this a real dry run: a
        # caller can no longer supply `EXPLAIN ANALYZE ...`, which asks the
        # planner to genuinely execute the query it claims to only be
        # explaining. The old check listed EXPLAIN as an allowed leading token,
        # so that costume worked.
        explain_sql = f"EXPLAIN {sql}"

        try:
            if source_type == "postgres":
                result = await self._run_postgres(
                    source.connection_config,
                    explain_sql,
                    None,
                )
            elif source_type == "mysql":
                result = await self._run_mysql(
                    source.connection_config,
                    explain_sql,
                    None,
                )
            else:
                return {
                    "error": f"dry_run not supported for source type '{source_type}'"
                }

            return {
                "plan": result["rows"],
                "columns": result["columns"],
                "source_id": source_id,
            }
        except Exception as exc:
            return {"error": f"EXPLAIN failed: {str(exc)}"}

    async def _run_postgres(
        self,
        config: dict,
        sql: str,
        params: dict | None,
    ) -> dict:
        host = config.get("host", "localhost")
        port = int(config.get("port", 5432))
        database = config.get("database", "")
        user = config.get("username", config.get("user", ""))
        password = config.get("password", "")

        conn = await asyncpg.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            timeout=30,
            command_timeout=STATEMENT_TIMEOUT_SECONDS,
        )
        try:
            if params:
                ordered_params = list(params.values())
                for i, key in enumerate(params.keys(), 1):
                    sql = sql.replace(f":{key}", f"${i}")
                rows_raw = await conn.fetch(sql, *ordered_params)
            else:
                rows_raw = await conn.fetch(sql)

            if not rows_raw:
                return {"rows": [], "columns": []}

            columns = list(rows_raw[0].keys())
            rows = [dict(row) for row in rows_raw]
            return {"rows": rows, "columns": columns}
        finally:
            await conn.close()

    async def _run_mysql(
        self,
        config: dict,
        sql: str,
        params: dict | None,
    ) -> dict:
        """Uses asyncmy (pure-Python async MySQL) — lazy imported to avoid startup crash."""
        try:
            import asyncmy
        except ImportError:
            return {
                "error": "asyncmy not installed. Add asyncmy to requirements.txt to enable MySQL execution."
            }

        host = config.get("host", "localhost")
        port = int(config.get("port", 3306))
        db = config.get("database", "")
        user = config.get("username", config.get("user", ""))
        password = config.get("password", "")

        conn = await asyncmy.connect(
            host=host,
            port=port,
            db=db,
            user=user,
            password=password,
            connect_timeout=30,
        )
        try:
            async with conn.cursor() as cursor:
                if params:
                    await cursor.execute(sql, list(params.values()))
                else:
                    await cursor.execute(sql)

                rows = await cursor.fetchall()
                columns = [d[0] for d in cursor.description] if cursor.description else []
                return {
                    "rows": [dict(zip(columns, r)) for r in rows],
                    "columns": columns,
                }
        finally:
            conn.close()

    def _check_safety(self, sql: str) -> dict:
        """Parse-tree validation. See modules/transformation/sql_guard.py for
        what is enforced and why the keyword blocklist that used to live here
        was removed rather than extended."""
        verdict = sql_guard.validate(sql)
        if not verdict.ok:
            return {"error": verdict.error}
        return {"ok": True, "has_root_limit": verdict.has_root_limit}

    def _inject_limit(self, sql: str, limit: int, has_root_limit: bool) -> str:
        """Bound the row count of any query that does not bound its own.

        `has_root_limit` comes from the parse tree rather than from searching
        the text for `LIMIT`, which is the whole fix: the old regex matched a
        LIMIT anywhere, so a bounded subquery inside an unbounded outer scan
        counted as bounded and nothing was injected.

        The limit is still appended as text rather than by regenerating the
        query from the parse tree. Regenerating would discard the author's
        comments and re-quote every identifier, and `executed_sql` is returned
        to the caller and logged — a query that comes back looking nothing
        like what was submitted is a bad thing to hand someone debugging a
        transformation. Appending to a root that provably has no LIMIT or
        FETCH is valid in both dialects, including after ORDER BY and across a
        UNION, where it correctly bounds the whole set operation.
        """
        if has_root_limit:
            return sql
        clean = sql.rstrip().rstrip(";")
        # The newline matters: a query ending in a `-- comment` would otherwise
        # swallow the limit. transform_generator's system prompt explicitly
        # asks the model for inline comments, so this is the normal case.
        return f"{clean}\nLIMIT {limit};"

    async def _load_source(self, source_id: str) -> dict:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DataSource).where(
                        DataSource.id == source_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()

            if source is None:
                return {"error": f"DataSource {source_id} not found"}
            if not source.connection_config:
                return {"error": f"DataSource {source_id} has no connection config"}

            return {"source": source}
        except Exception as exc:
            return {"error": f"Failed to load source: {str(exc)}"}