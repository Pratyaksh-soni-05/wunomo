import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from datetime import datetime, timezone
from sqlalchemy import select, text
import structlog

from database import AsyncSessionLocal
from models.all_models import DataSource, SourceType
from config import settings

log = structlog.get_logger()

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

# Security guard: never let a tenant-registered source point at the app's own
# control-plane database — that's every tenant's data, not just theirs.
_APP_DB_URL = urlparse(settings.DATABASE_URL.replace("+asyncpg", "").replace("+psycopg2", ""))


def _points_at_app_database(source_type: str, cfg: dict) -> bool:
    if source_type not in ("postgres", "mysql"):
        return False
    host = str(cfg.get("host", ""))
    database = str(cfg.get("database", ""))
    return host == _APP_DB_URL.hostname and database == (_APP_DB_URL.path or "").lstrip("/")

SUPPORTED_EXTS = {
    "csv": SourceType.CSV, "xlsx": SourceType.EXCEL, "xls": SourceType.EXCEL,
    "json": SourceType.JSON, "pdf": SourceType.PDF, "docx": SourceType.DOCX
}


class ConnectorManager:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ── LIST ──────────────────────────────────────────────────────────────────
    async def list_sources(self) -> dict:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(DataSource).where(
                DataSource.tenant_id == self.tenant_id,
                DataSource.is_active == True
            ))
            sources = r.scalars().all()
            return {
                "sources": [
                    {
                        "id": s.id, "name": s.name,
                        "source_type": s.source_type,
                        "is_active": s.is_active,
                        "last_profiled_at": str(s.last_profiled_at) if s.last_profiled_at else None,
                        "tags": s.tags or [],
                        "owner": s.owner,
                        "created_at": str(s.created_at)
                    }
                    for s in sources
                ],
                "count": len(sources)
            }

    # ── REGISTER ──────────────────────────────────────────────────────────────
    async def register_source(self, name: str, source_type: str, connection_config: dict) -> dict:
        if _points_at_app_database(source_type, connection_config or {}):
            return {"error": "This connection points at the application's own internal "
                              "database, which holds every tenant's data. Registering it "
                              "as a source is not allowed."}
        async with AsyncSessionLocal() as db:
            existing = await db.execute(select(DataSource).where(
                DataSource.tenant_id == self.tenant_id,
                DataSource.name == name
            ))
            if existing.scalars().first():
                return {"error": f"Source '{name}' already exists for this tenant"}
            source = DataSource(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                name=name,
                source_type=SourceType(source_type),
                connection_config=connection_config,
                schema_snapshot={},
                tags=[],
                created_at=utcnow(),
                updated_at=utcnow()
            )
            db.add(source)
            await db.commit()
            await db.refresh(source)
            log.info("source_registered", tenant=self.tenant_id, source_id=source.id, type=source_type)

            try:
                from modules.governance.lineage_tracker import LineageTracker
                await LineageTracker(self.tenant_id).add_node(
                    "source", source.name, {"source_id": source.id, "source_type": source_type}
                )
            except Exception as exc:
                log.warning("source_lineage_registration_failed", source_id=source.id, error=str(exc))

            return {"id": source.id, "name": source.name, "source_type": source_type, "status": "registered"}

    # ── INGEST FILE ───────────────────────────────────────────────────────────
    async def ingest_file(self, file_path: str, source_type: str, pipeline_id: Optional[str] = None) -> dict:
        ext = Path(file_path).suffix.lower().lstrip(".")
        result = {"file": file_path, "type": ext, "status": "ingested", "rows": 0, "columns": []}
        try:
            if ext == "csv":
                import pandas as pd
                df = pd.read_csv(file_path, nrows=1000)
                result.update(self._df_summary(df))
            elif ext in ("xlsx", "xls"):
                import pandas as pd
                df = pd.read_excel(file_path, nrows=1000)
                result.update(self._df_summary(df))
            elif ext == "json":
                import pandas as pd
                df = pd.read_json(file_path)
                result.update(self._df_summary(df))
            elif ext == "pdf":
                return await self._ingest_pdf(file_path)
            elif ext == "docx":
                return await self._ingest_docx(file_path)
            else:
                raise ValueError(f"Unsupported file type: .{ext}")
        except Exception as e:
            log.error("ingest_file_error", file=file_path, error=str(e))
            result.update({"status": "error", "error": str(e)})
        return result

    def _df_summary(self, df) -> dict:
        # Replace NaN/Infinity with None before serialization
        preview_df = df.head(10).where(df.head(10).notna(), other=None)
        null_counts = {c: int(v) for c, v in df.isnull().sum().items()}
        return {
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
            "preview": preview_df.to_dict("records"),
            "null_counts": null_counts,
            "null_pct": {c: round(int(v) / len(df) * 100, 2) if len(df) > 0 else 0
                         for c, v in null_counts.items()},
            "shape": list(df.shape),
            "status": "ingested"
        }

    async def _ingest_pdf(self, file_path: str) -> dict:
        try:
            import pdfplumber
            pages = []
            with pdfplumber.open(file_path) as pdf:
                for p in pdf.pages:
                    pages.append(p.extract_text() or "")
            full = "\n".join(pages)
            return {
                "file": file_path, "type": "pdf",
                "pages": len(pages), "total_chars": len(full),
                "preview": full[:2000], "status": "ingested"
            }
        except Exception as e:
            return {"file": file_path, "type": "pdf", "status": "error", "error": str(e)}

    async def _ingest_docx(self, file_path: str) -> dict:
        try:
            from docx import Document
            doc = Document(file_path)
            paras = [p.text for p in doc.paragraphs if p.text.strip()]
            return {
                "file": file_path, "type": "docx",
                "paragraphs": len(paras),
                "preview": "\n".join(paras[:20]),
                "status": "ingested"
            }
        except Exception as e:
            return {"file": file_path, "type": "docx", "status": "error", "error": str(e)}

    # ── PREVIEW ───────────────────────────────────────────────────────────────
    async def preview(self, source_id: str, table: str = "main", limit: int = 50) -> dict:
        async with AsyncSessionLocal() as db:
            source = await db.get(DataSource, source_id)
            if not source or source.tenant_id != self.tenant_id:
                return {"error": "Source not found"}
        try:
            connector = self._get_connector(source)
            return await connector.preview(table, limit)
        except Exception as e:
            return {"error": str(e), "source_id": source_id}

    # ── SYNC ──────────────────────────────────────────────────────────────────
    async def sync(self, source_id: str, mode: str = "incremental") -> dict:
        async with AsyncSessionLocal() as db:
            source = await db.get(DataSource, source_id)
            if not source or source.tenant_id != self.tenant_id:
                return {"error": "Source not found"}
            try:
                connector = self._get_connector(source)
                result = await connector.sync(mode)
                source.last_profiled_at = utcnow()
                await db.commit()
                log.info("source_synced", source_id=source_id, mode=mode)
                return result
            except Exception as e:
                log.error("sync_error", source_id=source_id, error=str(e))
                return {"error": str(e), "source_id": source_id, "status": "failed"}

    # ── CONNECTOR FACTORY ─────────────────────────────────────────────────────
    def _get_connector(self, source: DataSource):
        t = source.source_type
        cfg = source.connection_config
        if t == SourceType.POSTGRES:
            from modules.ingestion.connectors.postgres_connector import PostgresConnector
            return PostgresConnector(cfg)
        if t in (SourceType.CSV, SourceType.EXCEL, SourceType.JSON):
            from modules.ingestion.connectors.file_connector import FileConnector
            return FileConnector(cfg, t)
        if t == SourceType.MYSQL:
            from modules.ingestion.connectors.mysql_connector import MySQLConnector
            return MySQLConnector(cfg)
        if t == SourceType.API_REST:
            from modules.ingestion.connectors.api_connector import APIConnector
            return APIConnector(cfg)
        if t == SourceType.GOOGLE_SHEETS:
            from modules.ingestion.connectors.gsheets_connector import GSheetsConnector
            return GSheetsConnector(cfg)
        raise ValueError(f"No connector implemented for: {t}")