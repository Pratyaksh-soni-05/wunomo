"""Wunomo Projects Phase 4, slice 14: per-agent scheduled work -- a
ScheduledAgentTask fires a fixed tool call on a cron schedule, with no
LLM replanning (see that model's own docstring, models/all_models.py,
for the full design).

validate_schedule_can_run() is the single source of truth for "can this
schedule actually fire right now" -- called identically at creation
(api/v1/agents.py), at reactivation (same file), and by the beat tick
immediately before every firing (fire_scheduled_task, below). Reactivating
a deactivated schedule therefore re-runs the exact same check creation
did: turning it back on with the cause unfixed fails at the click, not
at the next 3am firing.
"""
import uuid
from datetime import datetime

import structlog
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, AgentInstanceStatus, ScheduledAgentTask, Task, TaskShape, TaskStatus,
    TaskStep, TaskStepSource, TaskStepStatus, TERMINAL_TASK_STATUSES, User,
)
from modules.orchestration.task_planner import PlanValidationError, validate_step_plan
from services.agent_scope import missing_sources_for_tool_call
from services.rbac import TOOL_CAPABILITIES, has_permission

log = structlog.get_logger()

# Matches api/v1/tasks.py's DEFAULT_STEP_BUDGET_MAX -- a schedule's Task
# has exactly one fixed step, so this ceiling is never actually
# approached; kept identical rather than invented separately so a
# scheduled task's budget behaves the same as any other task's if that
# default is ever revisited.
DEFAULT_STEP_BUDGET_MAX = 20


class ScheduleValidationError(Exception):
    """Raised by validate_schedule_can_run with a specific .cause
    ("invalid_plan" | "owner_inactive" | "owner_permission" |
    "agent_offboarded" | "source_missing") and a .message that names the
    real fix -- same "answer what do I do now" requirement as slice 9's
    denial UI, not just "why it stopped."."""
    def __init__(self, cause: str, message: str):
        self.cause = cause
        self.message = message
        super().__init__(message)


async def validate_schedule_can_run(
    db, *, agent_id: str, owner_user_id: str, task_shape: TaskShape,
    tool_name: str, tool_args: dict, description: str,
) -> None:
    """Raises ScheduleValidationError on the first check that fails,
    otherwise returns None. In order:

    1. Structural (validate_step_plan, pure/no DB) -- catches a typo'd
       tool_name or malformed/missing args. Can only genuinely fail here
       at creation time in practice (tool_name/tool_args are immutable
       once a schedule exists, and TASK_SHAPE_ALLOWED_TOOLS doesn't
       change at runtime) -- still re-run at reactivate/fire time for
       real parity with "the same validation," not a curated subset.
    2. The owner is still an active account.
    3. The owner's CURRENT role still has permission for tool_name
       (TOOL_CAPABILITIES/has_permission -- the same map task_executor.py's
       own _caller_still_authorized() checks per step, so a schedule can
       never run something a live task with the same owner couldn't).
    4. This agent is still ACTIVE (not offboarded).
    5. Every source-shaped arg in tool_args still references a source
       that exists (missing_sources_for_tool_call -- a check
       agent_scope_denial_reason() deliberately never does; see that
       function's own docstring for why a schedule's fixed, reused-for-
       months args need it when a human/LLM-driven task's freshly
       resolved ones never have)."""
    try:
        validate_step_plan(task_shape, [{
            "tool_name": tool_name, "tool_args": tool_args,
            "description": description, "depends_on_step_index": None,
        }])
    except PlanValidationError as exc:
        raise ScheduleValidationError("invalid_plan", str(exc)) from exc

    r = await db.execute(select(User.is_active, User.role, User.email).where(User.id == owner_user_id))
    owner = r.first()
    if owner is None or not owner.is_active:
        raise ScheduleValidationError(
            "owner_inactive",
            "This schedule's owner is no longer an active member of this workspace. "
            "Fix: reactivate their account, or delete this schedule and create a new one under an active owner.",
        )

    capability = TOOL_CAPABILITIES.get(tool_name)
    if capability is None or not has_permission(owner.role, capability):
        raise ScheduleValidationError(
            "owner_permission",
            f"This schedule's owner ({owner.email}) no longer has permission to use '{tool_name}' "
            f"(current role: {owner.role}). Fix: restore their role, or delete this schedule and "
            f"create a new one under a user who has permission.",
        )

    r = await db.execute(select(AgentInstance.status, AgentInstance.name).where(AgentInstance.id == agent_id))
    agent = r.first()
    if agent is None or agent.status != AgentInstanceStatus.ACTIVE:
        agent_name = agent.name if agent else agent_id
        raise ScheduleValidationError(
            "agent_offboarded",
            f"'{agent_name}' has been offboarded and can no longer run this schedule. "
            f"Fix: delete this schedule, or create a new one under a different agent.",
        )

    missing_args = await missing_sources_for_tool_call(db, tool_name, tool_args)
    if missing_args:
        raise ScheduleValidationError(
            "source_missing",
            f"'{tool_name}' argument(s) {sorted(missing_args)} reference a source that no longer exists. "
            f"Fix: delete this schedule and create a new one pointing at a valid source.",
        )


async def _notify_schedule_deactivated(schedule: ScheduledAgentTask, cause: str, message: str) -> None:
    """One-time, at the moment of deactivation -- no dedup machinery
    needed the way _notify_scope_denial_once (task_executor.py) needs one
    (Wunomo Projects Phase 2 frontend, slice 9): a schedule only ever
    transitions active=True -> False once per cause, since the beat tick
    never re-checks or re-fires an inactive schedule -- the state flip
    itself is the dedup guard. Best-effort, matching every other
    notification call site in this codebase: a delivery failure must
    never break the actual deactivation it's describing."""
    try:
        from modules.reporting.notification_service import NotificationService
        await NotificationService(schedule.tenant_id).send_alert(
            channel="both", severity="medium",
            title="Schedule deactivated",
            message=f'Schedule "{schedule.description}" was deactivated: {message}',
            metadata={"schedule_id": schedule.id, "agent_id": schedule.agent_id, "cause": cause},
        )
    except Exception as exc:
        log.warning("schedule_deactivation_notification_failed", schedule_id=schedule.id, error=str(exc))


async def deactivate_schedule(db, schedule: ScheduledAgentTask, cause: str, message: str) -> None:
    """The one place active gets set False -- called both by
    fire_scheduled_task (below, the beat-tick path) and by
    offboard_agent (api/v1/agents.py) when an agent with active
    schedules is offboarded, so the two triggers this slice defines
    (owner loses access, agent is offboarded) share one real
    implementation of "what deactivating means," not two that could
    drift. Caller commits db afterward -- both call sites already have
    other writes in the same transaction."""
    schedule.active = False
    schedule.deactivation_reason = message
    await _notify_schedule_deactivated(schedule, cause, message)


async def fire_scheduled_task(schedule_id: str) -> dict:
    """The real per-schedule work dispatched by check_scheduled_agent_tasks
    (services/tasks.py) -- one Celery subtask per due schedule, the same
    dispatch-not-inline pattern check_scheduled_pipelines/
    advance_active_tasks already established (item 74's own lesson: never
    do the real work inline in the beat tick itself).

    Skips (no Task created, no notification -- this is normal, expected
    behavior, not a failure) while a previous Task from this same
    schedule is still non-terminal: without this, a daily schedule
    hitting an approval gate every run would stack a second, third,
    fourth pending approval before the first's 48-hour window even
    closes."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ScheduledAgentTask).where(ScheduledAgentTask.id == schedule_id))
        schedule = r.scalar_one_or_none()
        if schedule is None or not schedule.active:
            return {"outcome": "not_found_or_inactive"}

        r = await db.execute(select(Task.id).where(
            Task.originating_schedule_id == schedule.id, Task.status.notin_(TERMINAL_TASK_STATUSES),
        ))
        if r.first() is not None:
            return {"outcome": "skipped_overlap"}

        try:
            await validate_schedule_can_run(
                db, agent_id=schedule.agent_id, owner_user_id=schedule.created_by_user_id,
                task_shape=schedule.task_shape, tool_name=schedule.tool_name,
                tool_args=schedule.tool_args or {}, description=schedule.description,
            )
        except ScheduleValidationError as exc:
            await deactivate_schedule(db, schedule, exc.cause, exc.message)
            await db.commit()
            log.info("scheduled_task_deactivated", schedule_id=schedule.id, cause=exc.cause)
            return {"outcome": "deactivated", "cause": exc.cause}

        # QUEUED, not DRAFT_PLAN: creating this schedule (a human explicitly
        # choosing this exact agent/tool/args/cadence) already was the
        # approval moment -- there is no separate plan for a human to
        # review here, and requiring a fresh approval click per firing
        # would defeat "give it a task and walk away" scheduling entirely.
        # advance_active_tasks' existing 60s beat tick (already live, Wunomo
        # Projects Phase 3/slice 10) picks up QUEUED tasks on its own; no
        # new execution-side code is needed for this task to actually run.
        task = Task(
            id=str(uuid.uuid4()), tenant_id=schedule.tenant_id, user_id=schedule.created_by_user_id,
            agent_id=schedule.agent_id, originating_schedule_id=schedule.id,
            goal=schedule.description, task_shape=schedule.task_shape, status=TaskStatus.QUEUED,
            step_budget_max=DEFAULT_STEP_BUDGET_MAX,
        )
        db.add(task)
        await db.flush()
        db.add(TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0, description=schedule.description,
            source=TaskStepSource.SCHEDULED, tool_name=schedule.tool_name,
            tool_args=schedule.tool_args or {}, status=TaskStepStatus.PENDING,
        ))
        schedule.last_fired_at = datetime.utcnow()
        await db.commit()
        log.info("scheduled_task_fired", schedule_id=schedule.id, task_id=task.id)
        return {"outcome": "fired", "task_id": task.id}
