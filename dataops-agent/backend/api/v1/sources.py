import asyncio

import asyncpg
import pymysql
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from .auth import get_current_user, require_permission, enforce_quota
from database import AsyncSessionLocal
from models.all_models import DataSource
from modules.ingestion.connector_manager import ConnectorManager, _points_at_app_database
from modules.ingestion.connectors.mysql_connector import MySQLConnector
from modules.ingestion.connectors.postgres_connector import PostgresConnector
from modules.ingestion.schema_profiler import SchemaProfiler
import uuid
from datetime import datetime, timezone
def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


router = APIRouter()

# Slice 5 (Wunomo Projects Phase 2 frontend): a real connect-before-you-save
# check, tested only for postgres/mysql today -- the two types where a wrong
# credential or Hard Rule 4's localhost trap is both likely and expensive to
# discover later. csv/excel/api_rest/google_sheets are untested at
# registration (a known gap, not an assumed capability -- see GOTCHAS.md).
TEST_CONNECTION_TIMEOUT_SECONDS = 8

class SourceCreate(BaseModel):
    name: str
    source_type: str
    connection_config: dict
    tags: Optional[list] = []
    owner: Optional[str] = None


class TestConnectionRequest(BaseModel):
    source_type: str
    connection_config: dict

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
async def create_source(
    req: SourceCreate,
    _perm=Depends(require_permission("sources.create")),
    user=Depends(enforce_quota("data_sources")),
):
    return await ConnectorManager(user["tenant_id"]).register_source(
        req.name, req.source_type, req.connection_config)

@router.post("/test-connection")
async def test_connection(req: TestConnectionRequest, user=Depends(require_permission("sources.create"))):
    """Runs BEFORE a source is saved, through the exact same connector
    classes (PostgresConnector/MySQLConnector) and the exact same
    connection-construction code (_dsn()/_get_connection()) that a real
    sync uses via ConnectorManager._get_connector() -- never a second,
    ad-hoc asyncpg/pymysql connect (Hard Rule 1's own reasoning: one real
    connection path, not two that can silently drift apart). The only
    difference from a real sync is which connector *method* gets called:
    list_tables() (added to MySQLConnector alongside this endpoint,
    mirroring Postgres's own) instead of sync()/get_schema() -- a real
    connect-and-read-one-thing, without sync()'s per-table row counts,
    which would make "test before you save" needlessly slow.

    Only postgres/mysql are covered -- csv/excel/api_rest/google_sheets
    report a clear 422, not a silent green check (a known, explicit gap,
    not an assumed capability)."""
    if req.source_type not in ("postgres", "mysql"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Connection testing isn't available for '{req.source_type}' yet -- "
                "only postgres and mysql are tested at registration today."
            ),
        )

    host = req.connection_config.get("host")
    if host == "localhost":
        return {
            "ok": False, "reason": "host_is_localhost",
            "message": (
                'Host is "localhost" -- inside Docker that means this backend container '
                'itself, not the real database service. If this source runs in this same '
                'docker-compose stack, use "postgres" (the service name) instead; '
                "otherwise use the database's real external hostname."
            ),
        }

    # Same guard register_source() applies at creation time (imported, not
    # re-implemented -- one real comparison, not two that can drift). Without
    # this, testing a connection to the app's own control-plane database
    # would report a real "Connected" success, only for the actual Create
    # to then be silently refused -- a test result that lies about whether
    # saving will work is worse than no test at all.
    if _points_at_app_database(req.source_type, req.connection_config):
        return {
            "ok": False, "reason": "points_at_app_database",
            "message": (
                "This connection points at the application's own internal database, "
                "which holds every tenant's data. It can be reached, but registering it "
                "as a source is not allowed."
            ),
        }

    connector = PostgresConnector(req.connection_config) if req.source_type == "postgres" \
        else MySQLConnector(req.connection_config)

    try:
        tables = await asyncio.wait_for(connector.list_tables(), timeout=TEST_CONNECTION_TIMEOUT_SECONDS)
        return {"ok": True, "tables_found": len(tables)}
    except asyncio.TimeoutError:
        return {
            "ok": False, "reason": "timeout",
            "message": (
                f"Connection attempt timed out after {TEST_CONNECTION_TIMEOUT_SECONDS}s. "
                "Check that the host is reachable from inside this backend's own network "
                "(a wrong host that fails fast reports a different, more specific error; "
                "a timeout usually means the host exists but nothing is answering)."
            ),
        }
    except KeyError as e:
        return {"ok": False, "reason": "missing_field", "message": f"connection_config is missing required field: {e}."}
    except asyncpg.exceptions.InvalidPasswordError as e:
        return {"ok": False, "reason": "auth_rejected", "message": str(e)}
    except asyncpg.exceptions.InvalidCatalogNameError as e:
        return {"ok": False, "reason": "database_not_found", "message": str(e)}
    except pymysql.err.OperationalError as e:
        code, msg = (e.args[0], e.args[1]) if len(e.args) >= 2 else (None, str(e))
        if code == 1045:
            return {"ok": False, "reason": "auth_rejected", "message": msg}
        if code == 1049:
            return {"ok": False, "reason": "database_not_found", "message": msg}
        return {"ok": False, "reason": "connection_failed", "message": msg}
    except (OSError, asyncpg.exceptions.PostgresError) as e:
        return {"ok": False, "reason": "connection_failed", "message": f"{type(e).__name__}: {e}"}
    except Exception as e:
        return {"ok": False, "reason": "unknown", "message": f"{type(e).__name__}: {e}"}


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
async def update_source(source_id: str, req: SourceUpdate, user=Depends(require_permission("sources.create"))):
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