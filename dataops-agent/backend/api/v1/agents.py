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

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from .auth import get_current_user, require_permission
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, AgentSource, ChannelAgent,
    DataSource, OperationMode, PersonalityMode, Project, ProjectAgent, ScheduledAgentTask,
    Task, TaskShape, TERMINAL_TASK_STATUSES,
)
from modules.orchestration.scheduled_tasks import ScheduleValidationError, deactivate_schedule, validate_schedule_can_run
from services.llm_service import SUPPORTED_MODEL_OVERRIDES
from services.quota_service import get_agent_quota_status
from services.settings_service import get_ai_model_override

log = structlog.get_logger()

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


# ---------------------------------------------------------------------------
# Scheduled work (Wunomo Projects Phase 4, slice 14) -- backend only, per
# explicit scope; the schedule-management UI on the agent detail page is
# its own later slice. A fixed tool call on a cron schedule, never
# replanned -- see ScheduledAgentTask's own docstring (models/all_models.py)
# for the full design.
# ---------------------------------------------------------------------------

class ScheduleCreate(BaseModel):
    task_shape: str
    description: str
    tool_name: str
    tool_args: dict = {}
    schedule_cron: str


def _serialize_schedule(schedule: ScheduledAgentTask) -> dict:
    return {
        "id": schedule.id,
        "agent_id": schedule.agent_id,
        "created_by_user_id": schedule.created_by_user_id,
        "task_shape": schedule.task_shape.value,
        "description": schedule.description,
        "tool_name": schedule.tool_name,
        "tool_args": schedule.tool_args,
        "schedule_cron": schedule.schedule_cron,
        "active": schedule.active,
        "deactivation_reason": schedule.deactivation_reason,
        "last_fired_at": schedule.last_fired_at.isoformat() if schedule.last_fired_at else None,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
    }


async def _get_schedule(db, tenant_id: str, agent_id: str, schedule_id: str) -> ScheduledAgentTask:
    r = await db.execute(select(ScheduledAgentTask).where(
        ScheduledAgentTask.id == schedule_id, ScheduledAgentTask.agent_id == agent_id,
        ScheduledAgentTask.tenant_id == tenant_id,
    ))
    schedule = r.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return schedule


@router.post("/{agent_id}/schedules")
async def create_schedule(agent_id: str, body: ScheduleCreate, user=Depends(require_permission("agents.manage"))):
    """Validated at creation, not discovered at the next 3am firing
    (explicit requirement): reuses validate_schedule_can_run (modules/
    orchestration/scheduled_tasks.py) -- the same function reactivation
    and every firing re-run -- so a typo'd tool_name, a malformed/missing
    arg, or an arg already pointing at a deleted source is rejected right
    here, at the click.

    The agent-offboarded check happens twice, deliberately: once here
    with creation-appropriate wording ("can't schedule an offboarded
    agent"), and once inside validate_schedule_can_run with deactivation-
    appropriate wording ("delete this schedule...") -- the latter would
    be nonsensical advice for a schedule that doesn't exist yet, so it
    can never actually be the message a caller sees at creation time; it
    only ever fires for real at reactivation/firing, once a schedule
    exists to delete."""
    tenant_id = user["tenant_id"]
    owner_user_id = user["sub"]

    try:
        task_shape = TaskShape(body.task_shape)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task_shape '{body.task_shape}'. Valid: {[s.value for s in TaskShape]}",
        )
    if not body.description or not body.description.strip():
        raise HTTPException(status_code=400, detail="description must not be empty.")
    if not body.schedule_cron or not body.schedule_cron.strip():
        raise HTTPException(status_code=400, detail="schedule_cron must not be empty.")
    try:
        from croniter import croniter
        croniter(body.schedule_cron)
    except (ValueError, KeyError):
        raise HTTPException(status_code=400, detail=f"'{body.schedule_cron}' is not a valid cron expression.")

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(
            AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
        ))
        agent = r.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found.")
        if agent.status != AgentInstanceStatus.ACTIVE:
            raise HTTPException(status_code=409, detail=f"'{agent.name}' has been offboarded and cannot be scheduled.")

        try:
            await validate_schedule_can_run(
                db, agent_id=agent_id, owner_user_id=owner_user_id, task_shape=task_shape,
                tool_name=body.tool_name, tool_args=body.tool_args or {}, description=body.description,
            )
        except ScheduleValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.message)

        schedule = ScheduledAgentTask(
            id=str(uuid.uuid4()), tenant_id=tenant_id, agent_id=agent_id, created_by_user_id=owner_user_id,
            task_shape=task_shape, description=body.description, tool_name=body.tool_name,
            tool_args=body.tool_args or {}, schedule_cron=body.schedule_cron, active=True,
        )
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)

    return _serialize_schedule(schedule)


@router.get("/{agent_id}/schedules")
async def list_schedules(agent_id: str, user=Depends(require_permission("agents.manage"))):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(
            AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
        ))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Agent not found.")

        r = await db.execute(
            select(ScheduledAgentTask)
            .where(ScheduledAgentTask.agent_id == agent_id, ScheduledAgentTask.tenant_id == tenant_id)
            .order_by(ScheduledAgentTask.created_at.desc())
        )
        schedules = r.scalars().all()

    return {"agent_id": agent_id, "schedules": [_serialize_schedule(s) for s in schedules]}


@router.post("/{agent_id}/schedules/{schedule_id}/reactivate")
async def reactivate_schedule(agent_id: str, schedule_id: str, user=Depends(require_permission("agents.manage"))):
    """Re-runs the identical validate_schedule_can_run() check creation
    and every firing use (explicit requirement): if the cause that
    deactivated this schedule is still true, reactivation fails the same
    way, right here, rather than silently re-arming a schedule that will
    just get deactivated again at its next due tick. Idempotent on an
    already-active schedule, matching grant_source's own "safe to click
    twice" convention."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        schedule = await _get_schedule(db, tenant_id, agent_id, schedule_id)
        if schedule.active:
            return _serialize_schedule(schedule)

        try:
            await validate_schedule_can_run(
                db, agent_id=schedule.agent_id, owner_user_id=schedule.created_by_user_id,
                task_shape=schedule.task_shape, tool_name=schedule.tool_name,
                tool_args=schedule.tool_args or {}, description=schedule.description,
            )
        except ScheduleValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.message)

        schedule.active = True
        schedule.deactivation_reason = None
        await db.commit()
        await db.refresh(schedule)

    return _serialize_schedule(schedule)


@router.delete("/{agent_id}/schedules/{schedule_id}")
async def delete_schedule(agent_id: str, schedule_id: str, user=Depends(require_permission("agents.manage"))):
    """The real fix a deactivation notification points at for two of its
    three causes (agent offboarded, source deleted) -- neither is fixable
    via reactivation, since there's no edit endpoint to point at instead.
    Any Task this schedule already created keeps its own record/goal/steps
    untouched, only losing the back-reference (originating_schedule_id
    ON DELETE SET NULL, models/all_models.py)."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        schedule = await _get_schedule(db, tenant_id, agent_id, schedule_id)
        await db.delete(schedule)
        await db.commit()

    return {"schedule_id": schedule_id, "deleted": True}


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
    a display label. Four things happen together, atomically:

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
    4. Deactivates this agent's active ScheduledAgentTask rows (Wunomo
       Projects Phase 4, slice 14), each with a one-time notification --
       see the code below for why this is deactivate-with-notification,
       not a block like point 1's non-terminal-task check.

    Deliberately NOT done here: agent_sources rows are preserved (no
    security reason to drop them -- dispatch is blocked at the status
    layer regardless of what's granted), and the agent's name stays
    blocked from reuse (hire_agent()'s duplicate-name check has no status
    filter) so a new unrelated agent can never inherit an offboarded
    one's name in old channel history.

    Deliberate design choice (Wunomo Projects Phase 2 frontend, slice 6,
    explicit user decision): offboarding is never BLOCKED by a channel
    where this agent is the sole member -- that would risk making
    offboarding a heavily-used agent effectively impossible, and breaks
    from every other precedent this build already set (agent_sources,
    channel history, project membership are all preserved through
    offboarding, never used to gate it). Instead: a channel left with zero
    active agents is a normal, recoverable state (the same shape as a
    project with zero agents), surfaced to the user via
    GET /api/v1/channels/'s agent_count field and a real, actionable
    message in chat.py rather than a bare "please @mention" that would be
    misleading with nobody left to mention. Logged here (channel_left_
    without_agent) purely for operator visibility, not as a gate."""
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

        r = await db.execute(select(ChannelAgent.channel_id).where(ChannelAgent.agent_id == agent_id))
        member_channel_ids = [row[0] for row in r.all()]
        if member_channel_ids:
            r = await db.execute(
                select(ChannelAgent.channel_id, func.count(ChannelAgent.id))
                .join(AgentInstance, AgentInstance.id == ChannelAgent.agent_id)
                .where(
                    ChannelAgent.channel_id.in_(member_channel_ids),
                    AgentInstance.status == AgentInstanceStatus.ACTIVE,
                )
                .group_by(ChannelAgent.channel_id)
            )
            for left_channel_id, active_count in r.all():
                if active_count == 1:
                    log.warning(
                        "channel_left_without_agent", channel_id=left_channel_id,
                        offboarded_agent_id=agent_id, offboarded_agent_name=agent.name,
                    )

        await db.execute(delete(ChannelAgent).where(ChannelAgent.agent_id == agent_id))
        agent.status = AgentInstanceStatus.OFFBOARDED

        # 4. Any of this agent's active schedules (Wunomo Projects Phase 4,
        # slice 14) are deactivated with a notification, not preserved
        # silently and not used to block offboarding -- a schedule is
        # standing configuration, dormant between firings, the same shape
        # as agent_sources/channel membership/project membership above
        # (all preserved through offboarding, never gate it), not the
        # live in-flight execution the non-terminal-task block above
        # exists to protect. Blocking on "a schedule exists" would risk
        # the same "offboarding a heavily-used agent becomes effectively
        # impossible" trap slice 6's own channel decision explicitly
        # avoided. A schedule-created Task that happens to be RUNNING at
        # this exact moment is already covered by the non-terminal-task
        # block above, unchanged -- this only handles the standing
        # configuration, not in-flight work.
        r = await db.execute(select(ScheduledAgentTask).where(
            ScheduledAgentTask.agent_id == agent_id, ScheduledAgentTask.active.is_(True),
        ))
        for schedule in r.scalars().all():
            await deactivate_schedule(
                db, schedule, "agent_offboarded",
                f"'{agent.name}' has been offboarded and can no longer run this schedule. "
                f"Fix: delete this schedule, or create a new one under a different agent.",
            )

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


@router.get("/selectable")
async def list_selectable_agents(user=Depends(get_current_user)):
    """Any authenticated tenant member, not agents.manage -- deliberately
    lighter than GET / below. The module docstring's reasoning for the
    agents.manage gate is about EDITING (which sources an agent can reach,
    hiring a new one) being a permission-boundary/org-structural action;
    reading who exists, to pick one for a task or a channel, isn't that --
    anyone can already start a task or create a channel with no capability
    gate at all, so gating the picker that populates those actions more
    strictly than the actions themselves is a mismatch, not a deliberate
    boundary. Confirmed live (Wunomo Projects Phase 4): a data_analyst
    calling GET / gets a real 403, which meant the channel-creation
    modal's own agent picker (chat/page.tsx's agentsQuery) has been coming
    up empty for every non-Owner/Admin role since channels shipped --
    fixed here by repointing that query at this endpoint instead of
    loosening GET /'s own gate. Excludes monthly_token_budget (stays
    behind agents.manage) and OFFBOARDED agents (picking one to run new
    work makes no sense). Sources are included, not just a count -- two
    bulk queries total (agents, then one AgentSource+DataSource join
    batched by agent_id IN (...)), not one per agent, same no-N+1 shape as
    the task rail's own list_active_tasks()."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(
            AgentInstance.tenant_id == tenant_id, AgentInstance.status == AgentInstanceStatus.ACTIVE,
        ).order_by(AgentInstance.created_at.asc()))
        agents = r.scalars().all()
        agent_ids = [a.id for a in agents]

        sources_by_agent: dict[str, list[dict]] = {aid: [] for aid in agent_ids}
        if agent_ids:
            r = await db.execute(
                select(AgentSource.agent_id, DataSource.id, DataSource.name)
                .join(DataSource, DataSource.id == AgentSource.source_id)
                .where(AgentSource.agent_id.in_(agent_ids))
            )
            for agent_id, source_id, source_name in r.all():
                sources_by_agent[agent_id].append({"id": source_id, "name": source_name})

    return {"agents": [
        {"id": a.id, "name": a.name, "sources": sources_by_agent[a.id]}
        for a in agents
    ]}


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
