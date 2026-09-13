from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from .auth import get_current_user, require_permission, enforce_quota
from database import AsyncSessionLocal
from models.all_models import DataSource
from modules.ingestion.connector_manager import ConnectorManager
from modules.ingestion.schema_profiler import SchemaProfiler
from services.encryption_service import redact_config, REDACTED
from services import pii_classifier
from modules.governance.audit_trail import AuditTrail
from sqlalchemy.orm.attributes import flag_modified
import uuid
from datetime import datetime, timezone
def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


router = APIRouter()

class SourceCreate(BaseModel):
    name: str
    source_type: str
    connection_config: dict
    tags: Optional[list] = []
    owner: Optional[str] = None

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    connection_config: Optional[dict] = None
    tags: Optional[list] = None
    owner: Optional[str] = None
    is_active: Optional[bool] = None

class ClassificationUpdate(BaseModel):
    """Item #10 manual override of one column's sensitivity level."""
    table: str
    column: str
    sensitivity: str          # one of pii_classifier.LEVELS
    reason: Optional[str] = None

@router.get("/")
async def list_sources(user=Depends(get_current_user)):
    return await ConnectorManager(user["tenant_id"]).list_sources()

@router.post("/")
async def create_source(
    req: SourceCreate,
    _perm=Depends(require_permission("sources.create")),
    user=Depends(enforce_quota("data_sources")),
):
    return await ConnectorManager(user["tenant_id"]).register_source(
        req.name, req.source_type, req.connection_config)

@router.get("/{source_id}")
async def get_source(source_id: str, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(
            DataSource.id == source_id, DataSource.tenant_id == user["tenant_id"]))
        source = r.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        # Credentials are masked, not returned. This endpoint previously served
        # the source's real plaintext password to any authenticated user of the
        # tenant; host/port/database stay visible so the Sources edit form
        # still renders. A client wanting to change the password sends a new
        # one via PUT — it is never read back out.
        return {"id": source.id, "name": source.name, "source_type": source.source_type,
                "connection_config": redact_config(source.connection_config),
                "tags": source.tags,
                "owner": source.owner, "is_active": source.is_active,
                "last_profiled_at": source.last_profiled_at, "created_at": source.created_at}

@router.put("/{source_id}")
async def update_source(source_id: str, req: SourceUpdate, user=Depends(require_permission("sources.create"))):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(
            DataSource.id == source_id, DataSource.tenant_id == user["tenant_id"]))
        source = r.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        if req.name: source.name = req.name
        if req.connection_config:
            # GET returns credentials masked as "********". A client that reads
            # a source, edits one field, and PUTs the whole object back would
            # otherwise overwrite the real password with the mask itself and
            # permanently break the connection. Any value still equal to the
            # mask means "unchanged" — keep what's already stored.
            existing = source.connection_config or {}
            merged = dict(req.connection_config)
            for key, value in req.connection_config.items():
                if value == REDACTED and key in existing:
                    merged[key] = existing[key]
            source.connection_config = merged
        if req.tags is not None: source.tags = req.tags
        if req.owner: source.owner = req.owner
        if req.is_active is not None: source.is_active = req.is_active
        source.updated_at = datetime.utcnow()
        await db.commit()
        return {"message": "Source updated", "id": source_id}

@router.delete("/{source_id}")
async def delete_source(source_id: str, user=Depends(require_permission("sources.delete"))):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(
            DataSource.id == source_id, DataSource.tenant_id == user["tenant_id"]))
        source = r.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        await db.delete(source)
        await db.commit()
        return {"message": "Source deleted", "id": source_id}

@router.post("/{source_id}/profile")
async def profile_source(source_id: str, user=Depends(require_permission("sources.profile"))):
    return await SchemaProfiler(user["tenant_id"], source_id).profile()

@router.post("/{source_id}/sync")
async def sync_source(source_id: str, mode: str = "incremental", user=Depends(require_permission("sources.profile"))):
    return await ConnectorManager(user["tenant_id"]).sync(source_id, mode)

@router.get("/{source_id}/preview")
async def preview(source_id: str, table: str = "main", limit: int = 50, user=Depends(get_current_user)):
    return await ConnectorManager(user["tenant_id"]).preview(source_id, table, limit)

@router.post("/{source_id}/drift")
async def detect_drift(source_id: str, user=Depends(require_permission("sources.profile"))):
    return await SchemaProfiler(user["tenant_id"], source_id).detect_drift()

@router.put("/{source_id}/classification")
async def classify_column(source_id: str, req: ClassificationUpdate,
                          user=Depends(require_permission("sources.classify"))):
    """Item #10: manually set a column's sensitivity (none/pii/phi).

    Lives beside PUT /{source_id} rather than inside it because the two carry
    different authority: editing a source's name or tags is `sources.create`,
    but lowering a column from pii to none removes masking from every preview,
    prompt and transform output for it, so it has its own capability
    (`sources.classify`, builders only) and its own audit action. The override
    is marked source="manual" and survives re-profiling
    (pii_classifier.merge_manual_overrides).
    """
    level = (req.sensitivity or "").strip().lower()
    if level not in pii_classifier.LEVELS:
        raise HTTPException(status_code=422,
                            detail=f"sensitivity must be one of {list(pii_classifier.LEVELS)}")
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(
            DataSource.id == source_id, DataSource.tenant_id == user["tenant_id"]))
        source = r.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        snapshot = dict(source.schema_snapshot or {})
        info = snapshot.get(req.table)
        cols = info.get("columns") if isinstance(info, dict) else None
        target = next((c for c in cols or [] if c.get("column_name") == req.column), None)
        if target is None:
            raise HTTPException(status_code=404,
                                detail=f"Column {req.table}.{req.column} not in schema snapshot; profile the source first")
        previous = target.get("sensitivity", "none")
        target["sensitivity"] = level
        target["sensitivity_source"] = "manual"
        target["sensitivity_reason"] = (req.reason or f"manually set by {user['email']}")[:200]
        # JSON column: SQLAlchemy does not see in-place mutation of a nested dict.
        source.schema_snapshot = snapshot
        flag_modified(source, "schema_snapshot")
        source.updated_at = datetime.utcnow()
        await db.commit()

    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="source.column_classified",
        resource_type="source", resource_id=source_id,
        payload={"table": req.table, "column": req.column,
                 "previous": previous, "new": level, "reason": req.reason},
    )
    return {"message": "Column classification updated", "id": source_id,
            "table": req.table, "column": req.column,
            "previous": previous, "sensitivity": level, "source": "manual"}
