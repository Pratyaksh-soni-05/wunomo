from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import DataSource
from modules.ingestion.connector_manager import ConnectorManager
from modules.ingestion.schema_profiler import SchemaProfiler
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

@router.get("/")
async def list_sources(user=Depends(get_current_user)):
    return await ConnectorManager(user["tenant_id"]).list_sources()

@router.post("/")
async def create_source(req: SourceCreate, user=Depends(get_current_user)):
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
        return {"id": source.id, "name": source.name, "source_type": source.source_type,
                "connection_config": source.connection_config, "tags": source.tags,
                "owner": source.owner, "is_active": source.is_active,
                "last_profiled_at": source.last_profiled_at, "created_at": source.created_at}

@router.put("/{source_id}")
async def update_source(source_id: str, req: SourceUpdate, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(
            DataSource.id == source_id, DataSource.tenant_id == user["tenant_id"]))
        source = r.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        if req.name: source.name = req.name
        if req.connection_config: source.connection_config = req.connection_config
        if req.tags is not None: source.tags = req.tags
        if req.owner: source.owner = req.owner
        if req.is_active is not None: source.is_active = req.is_active
        source.updated_at = datetime.utcnow()
        await db.commit()
        return {"message": "Source updated", "id": source_id}

@router.delete("/{source_id}")
async def delete_source(source_id: str, user=Depends(get_current_user)):
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
async def profile_source(source_id: str, user=Depends(get_current_user)):
    return await SchemaProfiler(user["tenant_id"], source_id).profile()

@router.post("/{source_id}/sync")
async def sync_source(source_id: str, mode: str = "incremental", user=Depends(get_current_user)):
    return await ConnectorManager(user["tenant_id"]).sync(source_id, mode)

@router.get("/{source_id}/preview")
async def preview(source_id: str, table: str = "main", limit: int = 50, user=Depends(get_current_user)):
    return await ConnectorManager(user["tenant_id"]).preview(source_id, table, limit)

@router.post("/{source_id}/drift")
async def detect_drift(source_id: str, user=Depends(get_current_user)):
    return await SchemaProfiler(user["tenant_id"], source_id).detect_drift()