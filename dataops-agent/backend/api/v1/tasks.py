"""Item 6 (long-running AXIOM tasks) -- stage 2, the planning phase. See
docs/PRODUCT_AUDIT.md section 1.9 for the full design.

Task creation/viewing/cancelling of one's own task needs no capability
gate beyond authentication -- the same access chat already has. Nothing
executes at this stage; enforcement of what a task's steps are actually
allowed to *do* is a stage-3 concern (per-step, at execution time, per
amendment 3 -- role is re-read fresh right before each step runs, never
cached here).
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, AgentInstanceStatus, RUNNABLE_TASK_STATUSES, TERMINAL_TASK_STATUSES, Task, TaskShape,
    TaskStatus, TaskStep, TaskStepSource, TaskStepStatus,
)
from modules.orchestration.task_planner import (
    PlanGenerationError, PlanValidationError, generate_plan, validate_step_plan, validate_step_plan_scope,
)
from services.rbac import has_permission

from .auth import enforce_agent_budget, enforce_quota, get_current_user, require_permission

router = APIRouter()

# Fixed default for stage 2 -- real step/wall-clock/credit budgeting is a
# stage-6 (termination) concern; this just needs a non-null value the
# schema requires today.
DEFAULT_STEP_BUDGET_MAX = 20


class CreateTaskRequest(BaseModel):
    goal: str
    task_shape: str
    # Item 46: the chat session this task was started from, if any - was
    # declared on the Task model/migration from the start but never
    # actually wired up anywhere (found while investigating item 4).
    # Optional because "+ New Task" on the bare Tasks list genuinely has
    # no session to attribute.
    originating_session_id: Optional[str] = None


class StepInput(BaseModel):
    description: str
    tool_name: str
    tool_args: dict = {}
    depends_on_step_index: int | None = None


class EditStepsRequest(BaseModel):
    steps: list[StepInput]


def _serialize_step(step: TaskStep) -> dict:
    return {
        "id": step.id,
        "step_index": step.step_index,
        "description": step.description,
        "source": step.source.value,
        "tool_name": step.tool_name,
        "tool_args": step.tool_args,
        "depends_on_step_index": step.depends_on_step_index,
        "status": step.status.value,
        "attempt_count": step.attempt_count,
        "error_message": step.error_message,
        "outcome_summary": step.outcome_summary,
        "approval_request_id": step.approval_request_id,
    }


def _pause_reason(task: Task, steps: list[TaskStep]) -> str | None:
    """Computed at read time from the real, already-persisted step data --
    never a separate stored field to drift out of sync. 'Step 3 failed' is
    useless; this surfaces which step, its own description, and the real
    underlying error every time, not a generic wrapper message."""
    if task.status != TaskStatus.PAUSED_FAILED_STEP:
        return None
    failed = next((s for s in sorted(steps, key=lambda s: s.step_index) if s.status == TaskStepStatus.FAILED), None)
    if failed is None:
        return None
    return f'Step {failed.step_index} ("{failed.description}") failed after {failed.attempt_count} attempt(s): {failed.error_message}'


def _completion_note(task: Task, steps: list[TaskStep]) -> str | None:
    """Same computed-at-read-time principle as _pause_reason, for the
    other honest-not-clean terminal status (Q2): a task can finish with a
    dispatched step it was never able to confirm. 'Completed' alone would
    be a false clean success; this names the step and says plainly that
    the underlying operation's real outcome is still unknown."""
    if task.status != TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS:
        return None
    unresolved = next(
        (s for s in sorted(steps, key=lambda s: s.step_index) if s.status == TaskStepStatus.VERIFYING), None,
    )
    if unresolved is None:
        return None
    return (
        f'Completed with unconfirmed steps — step {unresolved.step_index} '
        f'("{unresolved.description}") could not be confirmed within the verification window '
        f'and was not re-checked further. The dispatched operation may still be running or may '
        f'have already finished; check its real status directly.'
    )


def _approval_pending_reason(task: Task, steps: list[TaskStep]) -> str | None:
    """Same principle again, for the mid-task approval gate (Q5) -- names
    the blocked step and its risk level, not just 'needs approval'."""
    if task.status != TaskStatus.PAUSED_NEEDS_APPROVAL:
        return None
    blocked = next(
        (s for s in sorted(steps, key=lambda s: s.step_index) if s.status == TaskStepStatus.BLOCKED_APPROVAL), None,
    )
    if blocked is None:
        return None
    return f'Step {blocked.step_index} ("{blocked.description}") is waiting for approval to run "{blocked.tool_name}".'


def _expiry_reason(task: Task) -> str | None:
    """A task that sat paused for approval past the timeout with no
    decision -- distinct from a generic failure, per explicit
    requirement: honest about *why* it stopped, not a bare status code."""
    if task.status != TaskStatus.EXPIRED:
        return None
    paused_at = task.paused_at.isoformat() if task.paused_at else "an unknown time"
    return (
        f"Expired waiting for approval — paused at {paused_at}, no decision was made "
        f"within the approval window. Start a new task to try again."
    )


def _quota_paused_reason(task: Task, steps: list[TaskStep]) -> str | None:
    """Q4: credit exhaustion pauses (resumable) rather than fails -- names
    the step waiting on quota, distinct from every other pause reason."""
    if task.status != TaskStatus.PAUSED_QUOTA_EXCEEDED:
        return None
    blocked = next(
        (s for s in sorted(steps, key=lambda s: s.step_index) if s.status == TaskStepStatus.PENDING and s.attempt_count),
        None,
    )
    if blocked is None:
        return "Paused: tenant AI-credit quota exhausted. Resumable once quota is available again."
    return (
        f'Step {blocked.step_index} ("{blocked.description}") is paused after attempt {blocked.attempt_count} '
        f'because the tenant\'s AI-credit quota is exhausted. Resumable once quota is available again.'
    )


def _source_locked_reason(task: Task, steps: list[TaskStep]) -> str | None:
    """Wunomo Projects Phase 2, item 5: a source lock conflict pauses
    (resumable) rather than fails, same shape as _quota_paused_reason
    above -- names the step and the real "in use by X since HH:MM"
    message the lock itself produced, not a generic "locked"."""
    if task.status != TaskStatus.PAUSED_SOURCE_LOCKED:
        return None
    blocked = next(
        (s for s in sorted(steps, key=lambda s: s.step_index) if s.status == TaskStepStatus.PENDING and s.attempt_count),
        None,
    )
    if blocked is None:
        return "Paused: the source this step needs is in use by another caller. Resumable once it frees."
    return (
        f'Step {blocked.step_index} ("{blocked.description}") is paused after attempt {blocked.attempt_count}: '
        f'{blocked.error_message}'
    )


def _serialize_task(task: Task, steps: list[TaskStep]) -> dict:
    return {
        "id": task.id,
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "goal": task.goal,
        "task_shape": task.task_shape.value,
        "status": task.status.value,
        "pause_reason": _pause_reason(task, steps),
        "completion_note": _completion_note(task, steps),
        "approval_pending_reason": _approval_pending_reason(task, steps),
        "expiry_reason": _expiry_reason(task),
        "quota_paused_reason": _quota_paused_reason(task, steps),
        "source_locked_reason": _source_locked_reason(task, steps),
        # Real, persisted (not computed) -- set once, at the moment of a
        # cap-triggered stop or a cancel; see the Task model docstring.
        "termination_reason": task.termination_reason,
        "paused_at": task.paused_at.isoformat() if task.paused_at else None,
        "plan_approved_by": task.plan_approved_by,
        "plan_approved_at": task.plan_approved_at.isoformat() if task.plan_approved_at else None,
        "plan_edited": bool(task.plan_edited),
        "step_budget_max": task.step_budget_max,
        "step_budget_used": task.step_budget_used,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "steps": [_serialize_step(s) for s in sorted(steps, key=lambda s: s.step_index)],
    }


def _serialize_task_summary(task: Task) -> dict:
    """List view -- no step list (avoids an N+1 join for something the
    list screen doesn't need; GET /{id} returns the full detail)."""
    return {
        "id": task.id,
        "user_id": task.user_id,
        "goal": task.goal,
        "task_shape": task.task_shape.value,
        "status": task.status.value,
        "plan_edited": bool(task.plan_edited),
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


@router.get("/")
async def list_tasks(current_user: dict = Depends(get_current_user)):
    """Your own tasks always; every tenant member's if you hold
    tasks.manage_all (Owner/Admin) -- mirrors Team's own cross-member
    visibility precedent, since a task's goal/steps can be as sensitive
    as anything else a member does in this product."""
    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]
    can_view_all = has_permission(current_user.get("role"), "tasks.manage_all")

    async with AsyncSessionLocal() as db:
        query = select(Task).where(Task.tenant_id == tenant_id)
        if not can_view_all:
            query = query.where(Task.user_id == user_id)
        query = query.order_by(Task.created_at.desc())
        r = await db.execute(query)
        tasks = r.scalars().all()

    return [_serialize_task_summary(t) for t in tasks]


# Registered before /{task_id} deliberately -- FastAPI matches routes in
# registration order, and a path parameter would otherwise swallow these
# literal segments.
@router.get("/all")
async def list_all_tenant_tasks(current_user: dict = Depends(require_permission("tasks.manage_all"))):
    """Hard-gated (403 for anyone without tasks.manage_all), unlike GET /
    above, which is a soft per-caller visibility filter -- this is the
    real, binary-testable endpoint stage 7 promised so tasks.manage_all
    could leave test_permission_matrix.py's exemption list like every
    other capability. Every tenant task, not just the caller's own --
    for the Owner/Admin cross-member monitoring view."""
    tenant_id = current_user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Task).where(Task.tenant_id == tenant_id).order_by(Task.created_at.desc())
        )
        tasks = r.scalars().all()
    return [_serialize_task_summary(t) for t in tasks]


@router.get("/counts")
async def task_counts(current_user: dict = Depends(get_current_user)):
    """One real number: how many tasks (own, or every tenant task if you
    hold tasks.manage_all) are not yet in a terminal state -- running,
    queued, or waiting on you. Real or absent was the explicit
    requirement for the topbar counter this backs; this endpoint is what
    makes that number real. TERMINAL_TASK_STATUSES (models/all_models.py)
    is "anything not in this set needs a human's attention or is actively
    working" -- shared with api/v1/agents.py's offboard check (2026-09-04)
    so both agree on what "done" means, rather than each defining it."""
    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]
    can_view_all = has_permission(current_user.get("role"), "tasks.manage_all")

    async with AsyncSessionLocal() as db:
        query = select(Task.status).where(Task.tenant_id == tenant_id)
        if not can_view_all:
            query = query.where(Task.user_id == user_id)
        r = await db.execute(query)
        statuses = r.scalars().all()

    active = sum(1 for s in statuses if s not in TERMINAL_TASK_STATUSES)
    return {"active": active}


@router.get("/{task_id}")
async def get_task(task_id: str, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]
    can_view_all = has_permission(current_user.get("role"), "tasks.manage_all")

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
        task = r.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task.user_id != user_id and not can_view_all:
            raise HTTPException(status_code=403, detail="You don't have permission to view this task.")

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()

        from services.quota_service import get_task_cost
        cost = await get_task_cost(db, tenant_id, task_id)

    return {**_serialize_task(task, steps), "cost": cost}


@router.post("/")
async def create_task(body: CreateTaskRequest, current_user: dict = Depends(enforce_quota("ai_credits"))):
    """Generates and persists a real plan. Quota is checked (via the
    dependency above) before the LLM call ever runs, same order as chat.
    On any generation/validation failure, nothing is persisted -- a clean
    error, not a Task row stuck in draft_plan with no steps and no
    explanation."""
    try:
        task_shape = TaskShape(body.task_shape)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task_shape '{body.task_shape}'. Valid: {[s.value for s in TaskShape]}",
        )

    if not body.goal or not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal must not be empty.")

    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]

    # Generated before generate_plan() runs (not after, at Task-construction
    # time) so the planning LLM call can be tagged with the real task_id for
    # cost attribution -- Task.id has no DB-side default that would force
    # this ordering (it's a plain client-generated uuid4, same as always),
    # so this is a pure reorder, not a behavior change to ID assignment. If
    # the plan fails generation/validation below, this id is never written
    # to `tasks` -- the real, already-logged llm_usage_events row(s) for
    # this attempt end up carrying a task_id with no matching Task, which
    # is expected (see generate_plan()'s docstring), not a bug.
    task_id = str(uuid.uuid4())

    # Wunomo Projects Phase 1: resolve the tenant's real agent BEFORE
    # planning, not after -- generate_plan() uses it to list only the
    # agent's in-scope sources in the prompt and to reject a plan that
    # already names an out-of-scope source (both a cost optimisation
    # only, per CLAUDE.md's rule; see validate_step_plan_scope's own
    # docstring). task_executor's real enforcement (_caller_still_
    # authorized, the pre-_call_tool() check) is also keyed off this
    # same agent_id on the persisted Task row below -- without either,
    # every task keeps agent_id=None and both stay permanently inert.
    # Same "oldest ACTIVE agent for the tenant" convention chat.py's own
    # resolution uses, for the same reason: exactly one agent exists per
    # tenant until Phase 1's hiring ships.
    async with AsyncSessionLocal() as agent_db:
        r = await agent_db.execute(select(AgentInstance).where(
            AgentInstance.tenant_id == tenant_id, AgentInstance.status == AgentInstanceStatus.ACTIVE,
        ).order_by(AgentInstance.created_at.asc()).limit(1))
        agent_row = r.scalar_one_or_none()
    agent_id = agent_row.id if agent_row is not None else None

    # Gate 2 of the two-gate token-budget path (Wunomo Projects Phase 1,
    # part two) - before the real planning LLM call, same reasoning as
    # chat.py's own placement of this check.
    await enforce_agent_budget(agent_id)

    try:
        steps = await generate_plan(tenant_id, user_id, body.goal, task_shape, task_id=task_id, agent_id=agent_id)
    except (PlanGenerationError, PlanValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not generate a valid plan: {exc}")

    async with AsyncSessionLocal() as db:
        task = Task(
            id=task_id,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            goal=body.goal,
            task_shape=task_shape,
            status=TaskStatus.DRAFT_PLAN,
            step_budget_max=DEFAULT_STEP_BUDGET_MAX,
            originating_session_id=body.originating_session_id,
        )
        db.add(task)
        await db.flush()

        task_steps = []
        for i, step in enumerate(steps):
            ts = TaskStep(
                id=str(uuid.uuid4()),
                task_id=task.id,
                step_index=i,
                description=step["description"],
                source=TaskStepSource.LLM_PLANNED,
                tool_name=step["tool_name"],
                tool_args=step.get("tool_args") or {},
                depends_on_step_index=step.get("depends_on_step_index"),
                status=TaskStepStatus.PENDING,
            )
            db.add(ts)
            task_steps.append(ts)

        await db.commit()
        await db.refresh(task)
        for ts in task_steps:
            await db.refresh(ts)

    return _serialize_task(task, task_steps)


def _step_content_key(description, tool_name, tool_args, depends_on_step_index) -> tuple:
    """Order-independent comparison key for detecting whether a step's
    content genuinely changed between the persisted plan and an incoming
    edit."""
    return (description, tool_name, json.dumps(tool_args or {}, sort_keys=True), depends_on_step_index)


@router.patch("/{task_id}/steps")
async def edit_task_steps(task_id: str, body: EditStepsRequest, current_user: dict = Depends(get_current_user)):
    """Full-replacement edit of the step list. Only valid while the task
    is still draft_plan (409 otherwise) and only by the task's own
    creator (403 otherwise) -- a plan describes what will run under its
    creator's role at execution time (amendment 3), so nobody else edits
    it on their behalf. Reuses validate_step_plan(), the exact validator
    plan generation is bound by, so an edit can never smuggle in a tool
    the planner itself couldn't have proposed. Never touches
    plan_approved_by/plan_approved_at -- editing must never implicitly
    approve; that's the sole job of POST /{id}/approve-plan."""
    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]
    incoming_steps = [s.model_dump() for s in body.steps]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
        task = r.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="Only the task's creator may edit its plan.")
        if task.status != TaskStatus.DRAFT_PLAN:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot edit a plan once it has left draft_plan (current status: {task.status.value}).",
            )

        try:
            validate_step_plan(task.task_shape, incoming_steps)
            if task.agent_id is not None:
                # Cost optimisation only, same as plan generation's own
                # use of this check (see validate_step_plan_scope's
                # docstring) -- a human editing in a source the agent
                # isn't scoped to is just as much "a plan that cannot
                # succeed" as the planner proposing one.
                await validate_step_plan_scope(db, task.agent_id, incoming_steps)
        except PlanValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        r = await db.execute(
            select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.step_index)
        )
        existing_steps = r.scalars().all()
        existing_keys = [
            _step_content_key(s.description, s.tool_name, s.tool_args, s.depends_on_step_index)
            for s in existing_steps
        ]
        existing_sources = [s.source for s in existing_steps]

        any_change = len(incoming_steps) != len(existing_steps)
        planned_steps = []
        for i, step in enumerate(incoming_steps):
            new_key = _step_content_key(
                step["description"], step["tool_name"],
                step.get("tool_args") or {}, step.get("depends_on_step_index"),
            )
            if i < len(existing_keys) and new_key == existing_keys[i]:
                source = existing_sources[i]
            else:
                source = TaskStepSource.HUMAN_EDITED
                any_change = True
            planned_steps.append((step, source))

        # Full replacement, per the locked design -- simpler than an
        # in-place diff/update, and this is a positional (not
        # content-based) comparison, so a pure reorder of otherwise
        # identical steps is treated as an edit too, not a no-op.
        for s in existing_steps:
            await db.delete(s)
        await db.flush()

        task_steps = []
        for i, (step, source) in enumerate(planned_steps):
            ts = TaskStep(
                id=str(uuid.uuid4()), task_id=task.id, step_index=i,
                description=step["description"], source=source,
                tool_name=step["tool_name"], tool_args=step.get("tool_args") or {},
                depends_on_step_index=step.get("depends_on_step_index"),
                status=TaskStepStatus.PENDING,
            )
            db.add(ts)
            task_steps.append(ts)

        if any_change:
            task.plan_edited = True

        await db.commit()
        await db.refresh(task)
        for ts in task_steps:
            await db.refresh(ts)

    return _serialize_task(task, task_steps)


async def _load_own_draft_plan_task(db, task_id: str, tenant_id: str, user_id: str) -> Task:
    """Shared load+authorize for approve-plan/reject-plan: 404 if the task
    doesn't exist in this tenant, 403 if it's not yours, 409 if it has
    already left draft_plan. Same creator-only rule as PATCH /steps --
    the plan describes what will run under its creator's role."""
    r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
    task = r.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.user_id != user_id:
        raise HTTPException(status_code=403, detail="Only the task's creator may act on its plan.")
    if task.status != TaskStatus.DRAFT_PLAN:
        raise HTTPException(
            status_code=409,
            detail=f"This plan is no longer awaiting a decision (current status: {task.status.value}).",
        )
    return task


@router.post("/{task_id}/approve-plan")
async def approve_task_plan(task_id: str, current_user: dict = Depends(get_current_user)):
    """The only code path that ever sets plan_approved_by/plan_approved_at
    -- approves the plan exactly as it currently stands (whatever's
    persisted right now, original or already-edited). Transitions to
    QUEUED, not RUNNING: the approval-to-pickup window is real and
    permanent (stage 3's executor hasn't shipped yet, but even once it
    has, queue depth/worker restarts/credit checks make this a genuine,
    ongoing state, not just a stage-2-vs-3 build artifact)."""
    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]

    async with AsyncSessionLocal() as db:
        task = await _load_own_draft_plan_task(db, task_id, tenant_id, user_id)

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()
        if not steps:
            raise HTTPException(status_code=409, detail="Cannot approve a plan with no steps.")

        task.status = TaskStatus.QUEUED
        task.plan_approved_by = user_id
        task.plan_approved_at = datetime.utcnow()

        await db.commit()
        await db.refresh(task)
        for s in steps:
            await db.refresh(s)

    return _serialize_task(task, steps)


@router.post("/{task_id}/reject-plan")
async def reject_task_plan(task_id: str, current_user: dict = Depends(get_current_user)):
    """Terminal for this Task row -- rejecting doesn't leave a mutable
    draft to retry, it ends this attempt. Trying again means creating a
    new task, so the response says so explicitly rather than a bare 200
    with no next step, per explicit instruction."""
    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]

    async with AsyncSessionLocal() as db:
        task = await _load_own_draft_plan_task(db, task_id, tenant_id, user_id)
        task.status = TaskStatus.PLAN_REJECTED
        await db.commit()
        await db.refresh(task)

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()

    return {
        **_serialize_task(task, steps),
        "message": "Plan rejected. Start a new task to try again.",
    }


@router.post("/{task_id}/advance")
async def advance_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """Manually drives one step of execution (stage 3) -- creator-only,
    matching edit/approve/reject's rule. No automatic scheduling exists
    yet (deliberately out of stage 3's scope), so this is currently the
    only way a QUEUED/RUNNING task actually progresses. Delegates to
    execute_next_step(), which resolves exactly one step to a terminal
    state -- including whatever retries/adaptation its failure tier
    calls for -- before returning."""
    from modules.orchestration.task_executor import execute_next_step

    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
        task = r.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="Only the task's creator may advance it.")
        if task.status not in RUNNABLE_TASK_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Task is not runnable (current status: {task.status.value}).",
            )

    step_outcome = await execute_next_step(task_id)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()

    return {**_serialize_task(task, steps), "advance_outcome": step_outcome}


class ResolveStepRequest(BaseModel):
    notes: str = ""


@router.post("/{task_id}/resume")
async def resume_task_endpoint(
    task_id: str, body: ResolveStepRequest, current_user: dict = Depends(require_permission("approvals.manage")),
):
    """Approves the blocked step and continues execution -- gated by
    approvals.manage (Owner/Admin), the same capability that already
    reviews every other risk-gated action in this product, deliberately
    NOT creator-only (unlike edit/approve-plan/advance): a task's own
    creator approving their own risky step would defeat the point of
    requiring a second set of eyes. Tenant-scoped independently of the
    executor's own logic, since that layer has no HTTP-level identity."""
    from modules.orchestration.task_executor import resume_task

    tenant_id = current_user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Task not found.")

    result = await resume_task(task_id, resolved_by=current_user["sub"], notes=body.notes)
    if result["outcome"] == "not_resumable":
        raise HTTPException(
            status_code=409, detail=f"Task is not awaiting approval (current status: {result['status']}).",
        )
    if result["outcome"] == "expired":
        raise HTTPException(status_code=409, detail="This approval has expired. Start a new task to try again.")

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()

    return {**_serialize_task(task, steps), "resume_outcome": result}


@router.post("/{task_id}/reject-step")
async def reject_task_step_endpoint(
    task_id: str, body: ResolveStepRequest, current_user: dict = Depends(require_permission("approvals.manage")),
):
    """Declines the blocked step outright -- same gate as resume, same
    reasoning (not creator-only)."""
    from modules.orchestration.task_executor import reject_task_step

    tenant_id = current_user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Task not found.")

    result = await reject_task_step(task_id, resolved_by=current_user["sub"], notes=body.notes)
    if result["outcome"] == "not_resumable":
        raise HTTPException(
            status_code=409, detail=f"Task is not awaiting approval (current status: {result['status']}).",
        )
    if result["outcome"] == "expired":
        raise HTTPException(status_code=409, detail="This approval has expired. Start a new task to try again.")

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()

    return {**_serialize_task(task, steps), "reject_outcome": result}


@router.post("/{task_id}/cancel")
async def cancel_task_endpoint(task_id: str, current_user: dict = Depends(get_current_user)):
    """Creator OR approvals.manage (Owner/Admin) may cancel -- unlike
    resume/reject-step (approvals.manage only, since a creator approving
    their own risky step defeats the point) or edit/approve-plan
    (creator only), stopping your own task or stopping a runaway one you
    have governance authority over are both legitimate. Honest about the
    one thing it can't do: a step already executing in a concurrent
    request cannot be interrupted -- see cancel_task()'s docstring and
    CLAUDE.md for the live-proved race."""
    from modules.orchestration.task_executor import cancel_task

    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
        task = r.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task.user_id != user_id and not has_permission(current_user.get("role"), "approvals.manage"):
            raise HTTPException(status_code=403, detail="Only the task's creator or a manager may cancel it.")

    result = await cancel_task(task_id, cancelled_by=user_id)
    if result["outcome"] == "not_cancellable":
        raise HTTPException(
            status_code=409, detail=f"Task cannot be cancelled (current status: {result['status']}).",
        )

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        steps = r.scalars().all()

    return {**_serialize_task(task, steps), "cancel_outcome": result}
