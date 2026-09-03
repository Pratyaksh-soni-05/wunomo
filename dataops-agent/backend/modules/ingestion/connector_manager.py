import os
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

# Canonical upload directory -- api/v1/uploads.py imports this rather than
# defining its own copy, so there's exactly one place a file a human
# actually uploaded can live. This is also what makes a file_path
# "attach-only" checkable at all (see _resolve_uploaded_file_path below) --
# an agent can reference a real upload, never an arbitrary path elsewhere
# on the container's filesystem.
UPLOAD_DIR = os.path.join(os.path.expanduser("~"), "dataops_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _resolve_uploaded_file_path(file_path: str) -> Path:
    """Resolves file_path to a real file that's actually sitting under
    UPLOAD_DIR -- i.e. something a human already put there via
    POST /api/v1/uploads/ -- raising ValueError otherwise. This is the
    entire enforcement mechanism behind "attach-only": ingest_file and
    register_data_source (both chat-callable, both LLM-supplied paths)
    can only ever reference a file that genuinely exists here, never an
    arbitrary filesystem path (e.g. a path-traversal read of something
    outside the upload directory)."""
    resolved = Path(file_path).resolve()
    upload_root = Path(UPLOAD_DIR).resolve()
    if not resolved.is_relative_to(upload_root):
        raise ValueError(
            "file_path must be a file already uploaded via POST /api/v1/uploads/, "
            "not an arbitrary path."
        )
    if not resolved.is_file():
        raise ValueError(f"No uploaded file found at {file_path}.")
    return resolved

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

# PDF/DOCX can be parsed for text (see _ingest_pdf/_ingest_docx below) but
# _get_connector has no branch for them -- registering one as a DataSource
# succeeds today and only fails later, the first time anything (sync_source,
# a scheduled pipeline run) tries to actually use it. Rejected at the one
# chokepoint both upload_and_register (api/v1/uploads.py) and the
# register_data_source chat tool funnel through, so neither path can create
# this time bomb.
_NO_CONNECTOR_TYPES = {SourceType.PDF, SourceType.DOCX}


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
        try:
            resolved_type = SourceType(source_type)
        except ValueError:
            return {"error": f"Unknown source_type: {source_type}", "status_code": 422}
        if resolved_type in _NO_CONNECTOR_TYPES:
            return {
                "error": f"{resolved_type.value} has no working connector yet -- its text can "
                         f"be extracted (see ingest_file), but there's no destination data "
                         f"model to sync or profile it into. Registering it as a source would "
                         f"succeed now and only fail later, the first time anything tries to "
                         f"sync or profile it.",
                "status_code": 422,
            }
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

    # ── REGISTER AN UPLOADED FILE (attach-only) ─────────────────────────────────
    async def register_uploaded_file(self, name: str, file_path: str) -> dict:
        """Wunomo Projects Phase 2, item 5: the chat-callable half of
        register_data_source. file_path must resolve to a real file already
        sitting under UPLOAD_DIR (see _resolve_uploaded_file_path) -- an
        agent can attach an existing upload as a source, never invent a
        source_type or connection_config the way the raw register_source()
        call still allows callers who already have real, non-agent-supplied
        values for those (api/v1/sources.py's POST /). Both are derived
        here from the real file on disk instead."""
        try:
            resolved = _resolve_uploaded_file_path(file_path)
        except ValueError as e:
            return {"error": str(e), "status_code": 422}
        ext = resolved.suffix.lower().lstrip(".")
        source_type = SUPPORTED_EXTS.get(ext)
        if source_type is None:
            return {"error": f"Unsupported file type: .{ext}", "status_code": 422}
        return await self.register_source(
            name=name, source_type=source_type.value,
            connection_config={"file_path": str(resolved), "original_name": resolved.name},
        )

    # ── INGEST FILE ───────────────────────────────────────────────────────────
    async def ingest_file(self, file_path: str, pipeline_id: Optional[str] = None) -> dict:
        # pipeline_id is unused in this method's own body -- kept only so
        # services/agent_scope.py's TOOL_SCOPE_RESOLUTION["ingest_file"] has
        # a real arg to resolve against agent_sources. Removing it would
        # silently make this tool unscopeable, not just unused.
        try:
            resolved = _resolve_uploaded_file_path(file_path)
        except ValueError as e:
            return {"file": file_path, "status": "error", "error": str(e)}
        file_path = str(resolved)
        ext = resolved.suffix.lower().lstrip(".")
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