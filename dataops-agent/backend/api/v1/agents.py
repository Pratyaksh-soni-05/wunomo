"""Wunomo Projects Phase 1: agent source-scope management.

Fixes the real, previously-logged UX gap (GOTCHAS.md) -- a source
connected after an agent already exists was invisible to that agent, with
no way to grant it access. Deliberately minimal: just grant/revoke on an
existing agent's existing sources. Creating/naming/scoping-at-hire-time a
NEW agent is Phase 1 part two (hiring), not this file.

Role-gated to agents.manage (Owner/Admin, see services/rbac.py) -- the
same tier as team.manage/settings.manage. A Data Engineer can trigger
sync_source on a source their agent is already scoped to, but editing
WHICH sources an agent can reach is a permission-boundary edit, not an
operational action.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from .auth import require_permission
from database import AsyncSessionLocal
from models.all_models import AgentInstance, AgentSource, DataSource

router = APIRouter()


async def _get_agent_and_source(db, tenant_id: str, agent_id: str, source_id: str):
    """Tenant-scoped lookup of both rows -- neither the agent nor the
    source may belong to another tenant, even if the caller somehow
    knows a real id for one. Returns (agent, source); raises 404 on
    either being missing or cross-tenant."""
    r = await db.execute(select(AgentInstance).where(
        AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
    ))
    agent = r.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")

    r = await db.execute(select(DataSource).where(
        DataSource.id == source_id, DataSource.tenant_id == tenant_id,
    ))
    source = r.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    return agent, source


@router.post("/{agent_id}/sources/{source_id}")
async def grant_source(agent_id: str, source_id: str, user=Depends(require_permission("agents.manage"))):
    """Idempotent: granting an already-granted source is a no-op success,
    not a 409 -- matches the "safe to click twice" convention the rest of
    this codebase's admin actions already follow."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        agent, source = await _get_agent_and_source(db, tenant_id, agent_id, source_id)

        r = await db.execute(select(AgentSource).where(
            AgentSource.agent_id == agent_id, AgentSource.source_id == source_id,
        ))
        if r.scalar_one_or_none() is None:
            db.add(AgentSource(id=str(uuid.uuid4()), agent_id=agent_id, source_id=source_id))
            await db.commit()

    return {"agent_id": agent_id, "agent_name": agent.name, "source_id": source_id, "source_name": source.name, "granted": True}


@router.delete("/{agent_id}/sources/{source_id}")
async def revoke_source(agent_id: str, source_id: str, user=Depends(require_permission("agents.manage"))):
    """Idempotent: revoking a source that was never granted (or already
    revoked) is a no-op success, not a 404 -- the end state the caller
    wants (this agent cannot reach this source) is already true."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        agent, source = await _get_agent_and_source(db, tenant_id, agent_id, source_id)
        await db.execute(delete(AgentSource).where(
            AgentSource.agent_id == agent_id, AgentSource.source_id == source_id,
        ))
        await db.commit()

    return {"agent_id": agent_id, "agent_name": agent.name, "source_id": source_id, "source_name": source.name, "granted": False}


@router.get("/{agent_id}/sources")
async def list_agent_sources(agent_id: str, user=Depends(require_permission("agents.manage"))):
    """Read side of the same management surface -- without this, granting
    is a write-only operation nobody can inspect before or after."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(
            AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
        ))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Agent not found.")

        r = await db.execute(
            select(DataSource.id, DataSource.name)
            .join(AgentSource, AgentSource.source_id == DataSource.id)
            .where(AgentSource.agent_id == agent_id)
        )
        sources = [{"id": sid, "name": name} for sid, name in r.all()]

    return {"agent_id": agent_id, "sources": sources}
