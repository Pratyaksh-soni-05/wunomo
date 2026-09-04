"""Wunomo Projects Phase 1: agent source-scope management (part one) and
hiring (part two).

Fixes the real, previously-logged UX gap (GOTCHAS.md) -- a source
connected after an agent already exists was invisible to that agent, with
no way to grant it access. hire_agent() below is the second real consumer
of that same grant logic (source assignment at hire time reuses
_grant_source_within_session, not a second implementation).

Employee-type lock: AgentEmployeeType today only has DATAOPS as a real,
backed value (see its own docstring in models/all_models.py) -- hiring
validates the requested type against the real enum explicitly and
rejects anything else with a clear message, so "never imply a Coming
Soon employee is available" (the proposal's own rule for the frontend
hire screen) holds at the API boundary too, not only in the UI.

Role-gated to agents.manage (Owner/Admin, see services/rbac.py) -- the
same tier as team.manage/settings.manage. A Data Engineer can trigger
sync_source on a source their agent is already scoped to, but editing
WHICH sources an agent can reach, or hiring a new agent at all, is a
permission-boundary/org-structural action, not an operational one.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from .auth import require_permission
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, AgentSource, ChannelAgent,
    DataSource, OperationMode, PersonalityMode, Project, ProjectAgent, Task, TERMINAL_TASK_STATUSES,
)
from services.llm_service import SUPPORTED_MODEL_OVERRIDES
from services.quota_service import get_agent_quota_status
from services.settings_service import get_ai_model_override

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


async def _grant_source_within_session(db, agent_id: str, source_id: str) -> None:
    """The actual grant write, reusable inside an already-open session --
    both grant_source() (its own request) and hire_agent() (source
    assignment at hire time, part of one atomic create) go through this,
    so there's one real implementation of "what granting means," not a
    second one that could quietly drift from the first. Idempotent, same
    as grant_source()'s own contract."""
    r = await db.execute(select(AgentSource).where(
        AgentSource.agent_id == agent_id, AgentSource.source_id == source_id,
    ))
    if r.scalar_one_or_none() is None:
        db.add(AgentSource(id=str(uuid.uuid4()), agent_id=agent_id, source_id=source_id))


@router.post("/{agent_id}/sources/{source_id}")
async def grant_source(agent_id: str, source_id: str, user=Depends(require_permission("agents.manage"))):
    """Idempotent: granting an already-granted source is a no-op success,
    not a 409 -- matches the "safe to click twice" convention the rest of
    this codebase's admin actions already follow."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        agent, source = await _get_agent_and_source(db, tenant_id, agent_id, source_id)
        await _grant_source_within_session(db, agent_id, source_id)
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


@router.get("/{agent_id}/quota")
async def get_agent_quota(agent_id: str, user=Depends(require_permission("agents.manage"))):
    """Read side for the agent detail screen's budget card (Wunomo
    Projects Phase 2 frontend, slice 4) -- get_agent_quota_status() has
    existed since Phase 1 part two as an internal enforcement gate (chat
    turn start, task creation, mid-task before an adapt call); this is
    its first read-only exposure so a human can see the same number the
    gate itself checks, not just the static budget set at hire time."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(
            AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
        ))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Agent not found.")

    quota = await get_agent_quota_status(agent_id)
    return {"agent_id": agent_id, **quota}


@router.post("/{agent_id}/offboard")
async def offboard_agent(agent_id: str, user=Depends(require_permission("agents.manage"))):
    """Sets AgentInstanceStatus.OFFBOARDED -- a real, enforced state, not
    a display label. Three things happen together, atomically:

    1. Blocked (409) while any of this agent's tasks is non-terminal
       (TERMINAL_TASK_STATUSES, models/all_models.py -- shared with
       api/v1/tasks.py's own /counts endpoint so both agree on "done").
       Names the first such task so the caller knows exactly what to
       resolve (cancel it, wait for it to finish) before retrying.
       PAUSED_NEEDS_APPROVAL tasks are already non-terminal, so a pending
       approval blocks offboarding too, with no separate check needed.
    2. Removes this agent's channel_agents rows -- without this,
       services/channel_routing.py's resolve_mentioned_agent() and
       channel_agent_members() would still resolve it (neither filters
       on status independently; the status filter added there in this
       same change only excludes non-ACTIVE agents that are STILL
       members). ChatMessage rows keep their attribution regardless
       (agent_id is FK-less by existing convention) -- history is never
       touched here.
    3. Sets status = OFFBOARDED. Enforced at every real dispatch point:
       chat's and task creation's own agent-resolution queries already
       filter ACTIVE; task_executor.py's _caller_still_authorized() now
       re-checks it per step, the same way it re-checks the initiating
       user's is_active.

    Deliberately NOT done here: agent_sources rows are preserved (no
    security reason to drop them -- dispatch is blocked at the status
    layer regardless of what's granted), and the agent's name stays
    blocked from reuse (hire_agent()'s duplicate-name check has no status
    filter) so a new unrelated agent can never inherit an offboarded
    one's name in old channel history."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(
            AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
        ))
        agent = r.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found.")
        if agent.status == AgentInstanceStatus.OFFBOARDED:
            return {"agent_id": agent_id, "agent_name": agent.name, "status": agent.status.value}

        r = await db.execute(
            select(Task.id, Task.status).where(Task.agent_id == agent_id, Task.status.notin_(TERMINAL_TASK_STATUSES))
        )
        blocking_task = r.first()
        if blocking_task is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"Cannot offboard '{agent.name}': task {blocking_task.id} is still "
                        f"{blocking_task.status.value}. Resolve or cancel it first."
                    ),
                    "task_id": blocking_task.id,
                },
            )

        await db.execute(delete(ChannelAgent).where(ChannelAgent.agent_id == agent_id))
        agent.status = AgentInstanceStatus.OFFBOARDED
        await db.commit()
        await db.refresh(agent)

    return {"agent_id": agent_id, "agent_name": agent.name, "status": agent.status.value}


# ---------------------------------------------------------------------------
# Hiring (Wunomo Projects Phase 1, part two)
# ---------------------------------------------------------------------------

class AgentHire(BaseModel):
    name: str
    employee_type: str = "dataops"
    project_id: Optional[str] = None
    source_ids: list[str] = []
    monthly_token_budget: Optional[int] = None
    personality: str = "engineer"
    operation_mode: str = "assisted"
    model: Optional[str] = None


@router.post("/")
async def hire_agent(body: AgentHire, user=Depends(require_permission("agents.manage"))):
    tenant_id = user["tenant_id"]

    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty.")

    try:
        employee_type = AgentEmployeeType(body.employee_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Employee type '{body.employee_type}' isn't available yet — "
                f"available: {[e.value for e in AgentEmployeeType]}."
            ),
        )
    try:
        personality = PersonalityMode(body.personality)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown personality '{body.personality}'.")
    try:
        operation_mode = OperationMode(body.operation_mode)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown operation_mode '{body.operation_mode}'.")

    model = body.model
    if model is not None and model not in SUPPORTED_MODEL_OVERRIDES:
        raise HTTPException(status_code=422, detail=f"Unsupported model '{model}'. Allowed: {SUPPORTED_MODEL_OVERRIDES}")
    if model is None:
        # Same seeding rule the Phase 0 backfill migration used for AXIOM:
        # the tenant's current model override becomes a newly-created
        # agent's STARTING value, not a live reference that keeps
        # tracking the tenant setting afterward.
        model = await get_ai_model_override(tenant_id) or SUPPORTED_MODEL_OVERRIDES[0]

    if body.monthly_token_budget is not None and body.monthly_token_budget <= 0:
        raise HTTPException(status_code=400, detail="monthly_token_budget must be a positive number of tokens.")

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(AgentInstance).where(
            AgentInstance.tenant_id == tenant_id, AgentInstance.name == body.name.strip(),
        ))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"An agent named '{body.name}' already exists.")

        if body.project_id is not None:
            r = await db.execute(select(Project).where(Project.id == body.project_id, Project.tenant_id == tenant_id))
            if r.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Project not found.")

        source_rows = []
        for source_id in body.source_ids:
            r = await db.execute(select(DataSource).where(DataSource.id == source_id, DataSource.tenant_id == tenant_id))
            source = r.scalar_one_or_none()
            if source is None:
                raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
            source_rows.append(source)

        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=body.name.strip(),
            employee_type=employee_type, personality=personality, operation_mode=operation_mode,
            model=model, monthly_token_budget=body.monthly_token_budget, status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        await db.flush()

        if body.project_id is not None:
            db.add(ProjectAgent(id=str(uuid.uuid4()), project_id=body.project_id, agent_id=agent.id))

        for source in source_rows:
            await _grant_source_within_session(db, agent.id, source.id)

        await db.commit()
        await db.refresh(agent)

    return {
        "id": agent.id, "name": agent.name, "employee_type": agent.employee_type.value,
        "personality": agent.personality.value, "operation_mode": agent.operation_mode.value,
        "model": agent.model, "project_id": body.project_id,
        "sources": [{"id": s.id, "name": s.name} for s in source_rows],
        "monthly_token_budget": agent.monthly_token_budget,
        "status": agent.status.value,
    }


@router.get("/")
async def list_agents(user=Depends(require_permission("agents.manage"))):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(AgentInstance).where(AgentInstance.tenant_id == tenant_id)
            .order_by(AgentInstance.created_at.asc())
        )
        agents = r.scalars().all()
    return {"agents": [
        {
            "id": a.id, "name": a.name, "employee_type": a.employee_type.value,
            "status": a.status.value, "monthly_token_budget": a.monthly_token_budget,
        }
        for a in agents
    ]}
