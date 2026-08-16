"""Item 6 (long-running AXIOM tasks) -- stage 3 (execution core) + stage 4
(verification, Q2). See docs/PRODUCT_AUDIT.md section 1.9 for the design.

execute_next_step(task_id) advances a QUEUED/RUNNING task by exactly one
unit of work per call -- either resolving a step to a terminal state
(SUCCEEDED or FAILED, including whatever retries/adaptation its failure
tier calls for), or re-polling a step that's still VERIFYING. Directly
callable (tests, live verification, manual driving via
POST /tasks/{id}/advance); no automatic Celery scheduling is wired yet
(deliberately out of scope -- see CLAUDE.md).

Failure tiers (Q1), in the order a step's attempts are classified:
  - PERMISSION: the fresh per-step role/is_active re-check (amendment 3)
    fails. Never retried -- retrying a deterministic denial wastes
    nothing but time, and the caller needs to know now, not after a
    pointless wait. Counts as exactly 1 attempt.
  - TRANSIENT: the tool call raised a real exception. One bounded retry
    with a short backoff, same arguments, no LLM involved.
  - DOMAIN: the tool call returned cleanly but its own result dict
    contains an "error" key (this codebase's established convention for
    a tool signaling a real, structured failure -- "Pipeline not found",
    etc.). Gets exactly one LLM-adapt attempt: the real error is shown to
    the LLM, which may propose different arguments (or leave them
    unchanged if it can't improve on them).
A step gets at most 3 total attempts (1 initial + up to 2 recovery
attempts: one transient-retry OR one domain-adapt, whichever applies,
and a final attempt if the first recovery attempt also failed). At most
one LLM-adapt call is ever made per step, regardless of how many
attempts it takes. Once budget is exhausted, the step is marked FAILED
with the real underlying error message and the task pauses
(PAUSED_FAILED_STEP) -- never abandoned, never silently continued.

Verification (Q2): if a dispatching step's tool call succeeds
*structurally* but its result looks like an async dispatch (a real,
recognized shape -- currently only run_pipeline's
{"status": RunStatus.PENDING, "run_id": ...}), the dispatching step is
marked SUCCEEDED (it genuinely did dispatch) and a NEW, separate
TaskStep is appended with source=SYSTEM_INSERTED, depending on the
dispatching step's index -- never a status recycled onto the same step,
so a plan review can always tell what AXIOM planned from what the system
added (amendment 3's sibling requirement for stage 4). That new step is
polled on each subsequent call, purely against real elapsed wall-clock
time (VERIFY_TIMEOUT_SECONDS, measured from the step's own started_at,
which shares Task.started_at's clock -- no separate timer for stage 6's
eventual wall-clock cap to forget about), never against step_budget_used
or the 3-attempt tier budget -- those govern retrying a tool call, not
watching one that already succeeded at dispatch time.

Completion is honest by construction: the "no pending steps left, mark
COMPLETED" branch is only reachable when zero steps are still
VERIFYING. If the only thing left unresolved is a timed-out verify step,
the task goes to COMPLETED_WITH_UNCONFIRMED_STEPS instead -- never a
clean COMPLETED that silently ignores it.
"""
import asyncio
import json
import uuid
from datetime import datetime

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select, func

from database import AsyncSessionLocal
from agent.personality import get_risk_level
from modules.governance.policy_engine import PolicyEngine
from modules.orchestration.task_planner import tool_by_name, tool_schema_for_prompt
from models.all_models import (
    ApprovalRequest, ApprovalStatus, RunStatus, Task, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus, User,
)
from services.llm_service import invoke_llm
from services.quota_service import get_quota_status
from services.rbac import TOOL_CAPABILITIES, has_permission

MAX_ATTEMPTS_PER_STEP = 3  # 1 initial + up to 2 recovery attempts
TRANSIENT_RETRY_BACKOFF_SECONDS = 2
VERIFY_TIMEOUT_SECONDS = 300  # real wall-clock budget for a dispatched step to reach a terminal state
APPROVAL_PAUSE_TIMEOUT_HOURS = 48  # Q5 amendment: a paused-for-approval task doesn't wait forever
MAX_TASK_WALL_CLOCK_HOURS = 4  # Q4: real elapsed time since Task.started_at, covers time spent verifying too
LOOP_DETECTION_THRESHOLD = 3  # same (tool, args) signature attempted this many times = no progress, not persistence

TIER_PERMISSION = "permission"
TIER_TRANSIENT = "transient"
TIER_DOMAIN = "domain"

# Tools this codebase can genuinely verify the async result of.
# run_pipeline (DAGManager.trigger_run()) is the only real async-dispatching
# tool in the whole registry today -- confirmed by reading every tool in
# agent/tools/*.py, not assumed. It is deliberately NOT in any
# TASK_SHAPE_ALLOWED_TOOLS entry yet: exposing a real, mutating,
# fire-and-forget tool to the planner with no per-step approval gate
# (that's stage 5) would be a real safety regression against the whole
# reason item 6 was built before item 7. This mechanism is real and
# tested against the real run_pipeline/Celery/PipelineRun infrastructure
# (see CLAUDE.md's live-verification note), just not reachable through
# the locked planner allowlists until stage 5 exists.
_VERIFIABLE_TOOLS = {"run_pipeline"}

log = structlog.get_logger()


async def _caller_still_authorized(db, task: Task, tool_name: str) -> tuple[bool, str | None]:
    """Fresh, per-step re-read of the task's initiating user's
    is_active/role -- never trusts anything cached on Task (there is
    nothing to trust; Task carries no role column by design, see
    amendment 3). Mirrors get_current_user()'s own per-request re-read
    for REST, applied here at the step-execution boundary instead."""
    r = await db.execute(select(User.is_active, User.role).where(User.id == task.user_id))
    row = r.first()
    if row is None or not row.is_active:
        return False, "the initiating user's account is no longer active"
    capability = TOOL_CAPABILITIES.get(tool_name)
    if capability is None or not has_permission(row.role, capability):
        return False, f"the initiating user's role ('{row.role}') no longer has permission to use '{tool_name}'"
    return True, None



# Deterministic argument resolution (Tier 1, 2026-08 — see
# docs/context/SESSION_LOG.md for the full diagnosis). Which target arg
# key maps to which discovery tool's output is explicit and small rather
# than a generic "find any list of dicts" scan, so a name collision across
# unrelated entity types (a source and a pipeline sharing a name) can't
# cross-contaminate a resolution. Extend this dict, not the matching
# logic, when a new discovery tool + entity type is added. Field names
# genuinely differ per tool (confirmed by reading each one, not assumed):
# list_data_sources/list_pipelines wrap in {"sources"/"pipelines": [...]},
# id key "id", name key "name"; list_open_incidents returns a bare list
# (cap_tool_result only wraps empty results), id key "incident_id", name
# key "title" — not "id"/"name" like the other two.
_ARG_RESOLUTION_SOURCES = {
    "source_id": {"discovery_tool": "list_data_sources", "list_key": "sources", "id_key": "id", "name_key": "name"},
    "pipeline_id": {"discovery_tool": "list_pipelines", "list_key": "pipelines", "id_key": "id", "name_key": "name"},
    "incident_id": {"discovery_tool": "list_open_incidents", "list_key": None, "id_key": "incident_id", "name_key": "title"},
}


async def _resolve_step_args(db, task_id: str, step: TaskStep) -> dict:
    """Tier 1 (deterministic): the task planner generates a step's entire
    tool_args upfront, before any earlier step has actually run — it
    structurally cannot know a real ID a prior discovery step (e.g.
    list_data_sources) hasn't fetched yet, so it writes a plausible-looking
    placeholder instead (e.g. "sales_orders_source_id"), which then fails
    every time. This replaces that placeholder with the real ID by
    matching the target entity's name/title against THIS step's own
    human-readable description — no LLM call, and more reliable than one,
    since it reads the actual fetched record rather than guessing from a
    schema + error message. Falls through untouched (Tier 2's
    _adapt_step_args gets a shot on failure) for any arg not covered by
    _ARG_RESOLUTION_SOURCES, or where the match is ambiguous (0 or 2+
    candidates) — never guesses between multiple plausible matches.

    Callers are responsible for never invoking this on a human-edited step
    (source == HUMAN_EDITED) — a human who typed a specific value meant
    that value, deterministic "correction" or not. Also relied on for
    idempotency: both call sites additionally guard so a given step's args
    are resolved at most once, ever (see the risk-tier split in
    execute_next_step) — this function itself doesn't re-check that, its
    callers own that guarantee.
    """
    tool_args = dict(step.tool_args or {})
    description = (step.description or "").lower()
    resolved = dict(tool_args)

    for arg_key, spec in _ARG_RESOLUTION_SOURCES.items():
        if arg_key not in tool_args:
            continue
        r = await db.execute(
            select(TaskStep).where(
                TaskStep.task_id == task_id,
                TaskStep.tool_name == spec["discovery_tool"],
                TaskStep.status == TaskStepStatus.SUCCEEDED,
            )
        )
        discovery_steps = r.scalars().all()

        candidates = set()
        for ds in discovery_steps:
            raw = ds.raw_result
            records = raw if spec["list_key"] is None else (raw or {}).get(spec["list_key"])
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                name, rid = rec.get(spec["name_key"]), rec.get(spec["id_key"])
                if name and rid and str(name).lower() in description:
                    candidates.add(rid)

        if len(candidates) == 1:
            resolved[arg_key] = candidates.pop()
        # 0 or 2+ candidates: leave as-is, Tier 2 gets a shot on failure.

    return resolved


async def _adapt_step_args(
    tenant_id: str, user_id: str, description: str, tool_name: str, tool_args: dict, error_message: str,
) -> dict:
    """One LLM call: shows the real failure to the model and asks for
    corrected arguments. Falls back to the original arguments (a no-op
    "adaptation") if the LLM's response isn't a usable JSON object, or if
    the tenant is out of AI-credit quota -- adaptation is a nice-to-have
    recovery step, not something that should itself crash a task."""
    quota = await get_quota_status(tenant_id, "ai_credits")
    if quota["status"] == "exceeded":
        return tool_args

    schema = tool_schema_for_prompt(tool_name)
    prompt = (
        f'A task step just failed. Step: "{description}"\n'
        f"Tool: {tool_name}\n"
        f"Arguments used: {json.dumps(tool_args)}\n"
        f"Real error returned: {error_message}\n\n"
        f"Tool argument schema: {json.dumps(schema)}\n\n"
        "Propose corrected arguments as a JSON object matching the schema above that "
        "might succeed instead, based on the real error. If you cannot improve on the "
        "original arguments (the error isn't something adjusting arguments would fix), "
        "return the original arguments unchanged. Return ONLY a JSON object, no other text."
    )
    try:
        raw = await invoke_llm(
            [SystemMessage(content="You output ONLY a JSON object, no prose, no markdown fences."),
             HumanMessage(content=prompt)],
            tenant_id=tenant_id, user_id=user_id, request_type="task_step_adapt",
        )
        text = raw.strip().strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        adapted = json.loads(text)
        if isinstance(adapted, dict):
            return adapted
    except Exception:
        pass
    return tool_args


async def _call_tool(tenant_id: str, tool_name: str, tool_args: dict) -> dict:
    """Invokes the real registered tool directly (not through the agent's
    ToolNode/LangGraph machinery -- there's no LLM reasoning a task step
    needs to trigger the call itself, the plan already decided that).
    tenant_id is force-injected here, same convention agent_node uses for
    real chat tool calls -- never trusted from tool_args."""
    tool_obj = tool_by_name(tool_name)
    result = await tool_obj.ainvoke({**tool_args, "tenant_id": tenant_id})
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {"raw": result}
    return result


def _outcome_summary(tool_name: str, result: dict) -> str:
    """Capped, human-readable summary -- this, not the raw result, is
    what a resumed/adjacent step's context replays (amendment 2)."""
    text = json.dumps(result)
    if len(text) > 500:
        text = text[:500] + "...(truncated)"
    return f"{tool_name} succeeded: {text}"


def _looks_like_async_dispatch(tool_name: str, result: dict) -> bool:
    """True only for a real, recognized dispatch shape -- never a guess
    based on generic keys, since a false positive here would insert a
    verify step that can never resolve."""
    if tool_name == "run_pipeline" and isinstance(result, dict):
        return result.get("status") == RunStatus.PENDING and bool(result.get("run_id"))
    return False


async def _poll_dispatch_status(tool_name: str, dispatch_result: dict) -> dict:
    """Checks the REAL current state of a previously-dispatched operation.
    Returns {"terminal": bool, "success": bool | None, "detail": str}."""
    if tool_name == "run_pipeline":
        from models.all_models import PipelineRun
        run_id = dispatch_result.get("run_id")
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = r.scalar_one_or_none()
        if run is None:
            return {"terminal": True, "success": False, "detail": f"Run {run_id} record no longer exists."}
        if run.status == RunStatus.SUCCESS:
            return {"terminal": True, "success": True, "detail": f"Run {run_id} completed successfully."}
        if run.status == RunStatus.FAILED:
            return {"terminal": True, "success": False, "detail": f"Run {run_id} failed: {run.error_message}"}
        return {"terminal": False, "success": None, "detail": f"Run {run_id} is still {run.status}."}
    return {"terminal": True, "success": True, "detail": "Unrecognized dispatch type; treated as resolved."}


def _set_task_status_unless_cancelled(task: Task, new_status: TaskStatus) -> bool:
    """The one guard that makes cancel_task() mean something: a step
    already in flight when cancellation is requested cannot be
    interrupted (there's no cooperative-cancellation plumbing here, and a
    concurrent DB write can't stop an already-running `await`), so it
    runs to completion and its own real outcome is still honestly
    recorded -- but that completion must never silently overwrite a
    task-level CANCELLED back to RUNNING/COMPLETED/FAILED/etc. Every
    task.status write in this module goes through this function instead
    of a bare assignment. Returns whether the write was applied."""
    if task.status == TaskStatus.CANCELLED:
        return False
    task.status = new_status
    return True


def _check_wall_clock_cap(task: Task) -> str | None:
    if task.started_at is None:
        return None
    elapsed_hours = (datetime.utcnow() - task.started_at).total_seconds() / 3600
    if elapsed_hours > MAX_TASK_WALL_CLOCK_HOURS:
        return (
            f"Stopped: exceeded the {MAX_TASK_WALL_CLOCK_HOURS}-hour wall-clock budget "
            f"(started at {task.started_at.isoformat()}, running for {elapsed_hours:.1f}h)."
        )
    return None


def _check_step_budget_cap(task: Task) -> str | None:
    used = task.step_budget_used or 0
    if used >= task.step_budget_max:
        return f"Stopped: exceeded the {task.step_budget_max}-step budget (used {used}/{task.step_budget_max})."
    return None


def _check_for_loop(all_steps: dict) -> str | None:
    """A "loop" in this execution model can only mean the PLAN itself
    contains the same (tool, args) pair repeated with no real reason --
    steps are fixed at plan time, nothing re-plans mid-execution the way
    a live agent conversation might. Counts ALL occurrences, not just
    already-attempted ones -- a plan authored with 3 identical steps is
    already a bad plan before any of them run; waiting for 2 real wasted
    attempts before catching the 3rd would defeat the point. Excludes
    SYSTEM_INSERTED verify steps: every one of them shares the same empty
    tool_args ({}) by construction (see the dispatching-step success
    branch above), so 3 legitimate, different real dispatches would
    otherwise collide into a false positive -- this check is about
    whether the AUTHORED plan repeats itself, not system bookkeeping."""
    counts: dict[tuple, int] = {}
    for s in all_steps.values():
        if not s.tool_name or s.source == TaskStepSource.SYSTEM_INSERTED:
            continue
        sig = (s.tool_name, json.dumps(s.tool_args or {}, sort_keys=True))
        counts[sig] = counts.get(sig, 0) + 1
    for (tool_name, args_json), count in counts.items():
        if count >= LOOP_DETECTION_THRESHOLD:
            return (
                f"Stopped: detected a loop — '{tool_name}' called {count} times with "
                f"materially the same arguments ({args_json}) and no progress."
            )
    return None


async def _notify_task_stopped(task: Task, title: str, message: str, severity: str = "medium") -> None:
    """Stage 7: 'give it a task and walk away' only works if something
    tells you when it's done or needs you. Fires at the transitions that
    genuinely warrant it -- every terminal state, plus mid-task approval
    (someone needs to act) -- never for the retry-prone pauses
    (PAUSED_FAILED_STEP, PAUSED_QUOTA_EXCEEDED) that are already visible
    the moment anyone checks the Tasks screen and would otherwise spam on
    every failed attempt. Best-effort, matching this module's own
    NotificationService contract: a delivery failure must never break
    the actual state transition it's describing."""
    try:
        from modules.reporting.notification_service import NotificationService
        await NotificationService(task.tenant_id).send_alert(
            channel="both", severity=severity, title=title, message=message,
            metadata={"task_id": task.id, "status": task.status.value},
        )
    except Exception as exc:
        log.warning("task_notification_failed", task_id=task.id, error=str(exc))


async def execute_next_step(task_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED_QUOTA_EXCEEDED):
            return {"outcome": "not_runnable", "status": task.status.value}

        if task.status in (TaskStatus.QUEUED, TaskStatus.PAUSED_QUOTA_EXCEEDED):
            _set_task_status_unless_cancelled(task, TaskStatus.RUNNING)
            task.started_at = task.started_at or datetime.utcnow()
            await db.commit()

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        all_steps = {s.step_index: s for s in r.scalars().all()}

        # --- Termination caps (Q4), checked before any new work happens
        # this call. Each produces a distinguishable real reason, not just
        # "task stopped" -- FAILED is reused (was otherwise unused by this
        # module) for all three; PAUSED_QUOTA_EXCEEDED (credit exhaustion)
        # is handled separately, inside the attempt loop below, since it's
        # resumable rather than terminal. ---
        wall_clock_reason = _check_wall_clock_cap(task)
        if wall_clock_reason:
            _set_task_status_unless_cancelled(task, TaskStatus.FAILED)
            task.termination_reason = wall_clock_reason
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(task, "Task stopped", wall_clock_reason, severity="high")
            return {"outcome": "terminated_wall_clock", "reason": wall_clock_reason}

        step_budget_reason = _check_step_budget_cap(task)
        if step_budget_reason:
            _set_task_status_unless_cancelled(task, TaskStatus.FAILED)
            task.termination_reason = step_budget_reason
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(task, "Task stopped", step_budget_reason, severity="high")
            return {"outcome": "terminated_step_budget", "reason": step_budget_reason}

        loop_reason = _check_for_loop(all_steps)
        if loop_reason:
            _set_task_status_unless_cancelled(task, TaskStatus.FAILED)
            task.termination_reason = loop_reason
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(task, "Task stopped", loop_reason, severity="high")
            return {"outcome": "terminated_loop_detected", "reason": loop_reason}

        # --- Priority 1: resolve a step that's already dispatched and
        # waiting on real-world confirmation (Q2). At most one call's
        # worth of work happens here before this function either returns
        # or falls through to try independent forward progress. ---
        verifying = next((s for s in all_steps.values() if s.status == TaskStepStatus.VERIFYING), None)
        verify_elapsed = None
        if verifying is not None:
            poll = await _poll_dispatch_status(verifying.tool_name, verifying.raw_result or {})
            verifying.attempt_count = (verifying.attempt_count or 0) + 1
            verify_elapsed = (datetime.utcnow() - verifying.started_at).total_seconds() if verifying.started_at else 0.0

            if poll["terminal"] and poll["success"]:
                verifying.status = TaskStepStatus.SUCCEEDED
                verifying.outcome_summary = poll["detail"]
                verifying.completed_at = datetime.utcnow()
                await db.commit()
                return {"outcome": "step_verified_succeeded", "step_id": verifying.id, "detail": poll["detail"]}

            if poll["terminal"] and not poll["success"]:
                verifying.status = TaskStepStatus.FAILED
                verifying.error_message = poll["detail"]
                verifying.completed_at = datetime.utcnow()
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
                return {"outcome": "step_verification_failed", "step_id": verifying.id, "reason": poll["detail"]}

            # Not yet terminal -- persist the poll attempt either way, then
            # decide below whether anything independent can still proceed
            # in this same call (the "move on" path), or whether this is
            # genuinely the only thing left (handled after the pending-step
            # search finds nothing runnable).
            await db.commit()

        # --- Priority 2: make progress on a runnable PENDING step, "move
        # on" from an unresolved verify step per Q2 whenever independent
        # work exists rather than blocking on it needlessly. ---
        pending = sorted(
            (s for s in all_steps.values() if s.status == TaskStepStatus.PENDING),
            key=lambda s: s.step_index,
        )
        step = None
        for candidate in pending:
            dep = candidate.depends_on_step_index
            if dep is None or (dep in all_steps and all_steps[dep].status == TaskStepStatus.SUCCEEDED):
                step = candidate
                break

        if step is None:
            # Nothing independent to run. Either genuinely done, still
            # honestly waiting on verification, or stuck on a dependency.
            if verifying is not None:
                if verify_elapsed is not None and verify_elapsed > VERIFY_TIMEOUT_SECONDS:
                    # The ONLY invariant that matters here: this branch is
                    # the sole path into COMPLETED_WITH_UNCONFIRMED_STEPS,
                    # and plain COMPLETED below is only reachable when
                    # `verifying` was None to begin with -- a task can
                    # never report clean success while a dispatched step
                    # remains unconfirmed.
                    _set_task_status_unless_cancelled(task, TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS)
                    task.completed_at = datetime.utcnow()
                    await db.commit()
                    await _notify_task_stopped(
                        task, "Task completed with unconfirmed steps",
                        f'Step {verifying.step_index} ("{verifying.description}") could not be confirmed '
                        f"within the verification window.", severity="medium",
                    )
                    return {
                        "outcome": "task_completed_with_unconfirmed_steps",
                        "step_id": verifying.id, "elapsed_seconds": verify_elapsed,
                    }
                await db.commit()
                return {"outcome": "still_verifying", "step_id": verifying.id, "elapsed_seconds": verify_elapsed}
            if pending:
                # Every remaining pending step is blocked on a dependency
                # that never succeeded -- shouldn't be reachable given we
                # pause the whole task on the first real failure, but
                # guarded rather than assumed.
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
                return {"outcome": "blocked_on_dependency"}
            _set_task_status_unless_cancelled(task, TaskStatus.COMPLETED)
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(
                task, "Task completed", f'Task "{task.goal}" completed successfully.', severity="low",
            )
            return {"outcome": "task_completed"}

        authorized, denial_reason = await _caller_still_authorized(db, task, step.tool_name)
        if not authorized:
            step.attempt_count += 1
            step.status = TaskStepStatus.FAILED
            step.error_message = f"Blocked: {denial_reason}."
            step.started_at = step.started_at or datetime.utcnow()
            step.completed_at = datetime.utcnow()
            _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
            await db.commit()
            return {
                "outcome": "blocked_permission", "step_id": step.id,
                "attempt_count": step.attempt_count, "reason": denial_reason,
            }

        # Mid-task approval gate (Q5): risk tier is read from the same
        # RISK_ACTIONS map chat's own approval gate uses (agent/
        # personality.py) -- one source of truth, not a parallel
        # classification a task could silently drift from. Tasks have no
        # operation_mode concept (there's no human present each turn to
        # have granted one), so gating is unconditional on tier: medium
        # or high always requires approval, low never does.
        if get_risk_level(step.tool_name) in ("medium", "high") and step.approval_request_id is None:
            # Tier 1 resolution — must happen before the ApprovalRequest is
            # created, not after: what gets displayed on the approval card
            # (action_args below, and the same TaskStep row the step-
            # timeline table renders) has to already be the real, final
            # value the tool will actually be called with. Resolving later
            # (e.g. lazily in resume_task) would mean approving one thing
            # and executing another. Guarded by approval_request_id is None
            # above (this whole block only runs once per step, ever) and
            # by risk tier here in _resolve_step_args's sibling call below
            # — together these guarantee a step's args are resolved
            # exactly once, never re-touched on a resume.
            if step.source != TaskStepSource.HUMAN_EDITED:
                step.tool_args = await _resolve_step_args(db, task_id, step)
            approval = await PolicyEngine(task.tenant_id).create_request(
                user_id=task.user_id, session_id=task.id, action_name=step.tool_name,
                action_args=step.tool_args or {}, risk_level=get_risk_level(step.tool_name),
                reason=f'Task step "{step.description}" requires approval before it can run.',
            )
            step.approval_request_id = approval["approval_id"]
            step.status = TaskStepStatus.BLOCKED_APPROVAL
            _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_NEEDS_APPROVAL)
            task.paused_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(
                task, "Task needs approval",
                f'Step {step.step_index} ("{step.description}") needs approval to run "{step.tool_name}".',
                severity="medium",
            )
            return {
                "outcome": "blocked_needs_approval", "step_id": step.id,
                "approval_request_id": approval["approval_id"], "risk_level": approval["risk_level"],
            }

        if step.approval_request_id is not None:
            r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
            approval_req = r.scalar_one_or_none()
            if approval_req is None or approval_req.status == ApprovalStatus.PENDING:
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_NEEDS_APPROVAL)
                await db.commit()
                return {"outcome": "still_blocked_needs_approval", "step_id": step.id}
            if approval_req.status == ApprovalStatus.REJECTED:
                step.status = TaskStepStatus.FAILED
                step.error_message = f"Step rejected: {approval_req.resolution_note or 'no reason given'}."
                step.completed_at = datetime.utcnow()
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
                return {"outcome": "step_rejected", "step_id": step.id, "reason": step.error_message}
            # APPROVED (or, defensively, any other resolved state) -- fall
            # through to real execution below. This is the resume path:
            # the tool call that follows is a genuine, fresh call -- not a
            # cached replay -- so it re-validates its own preconditions
            # and, one line above, _caller_still_authorized() already
            # re-validated the initiating user's authority for real.

        # Tier 1 resolution for auto-run (low-risk) steps — the sibling of
        # the approval-gate call above. Explicitly excludes medium/high
        # risk here (rather than relying on "they never reach this branch
        # unresolved" implicitly) so a step's args are resolved at exactly
        # one of these two call sites, never both: a medium/high-risk step
        # was already resolved before its approval card rendered, and must
        # not be silently re-resolved on the resume pass just because it
        # happens to also have attempt_count == 0 here.
        if (
            (step.attempt_count or 0) == 0
            and get_risk_level(step.tool_name) not in ("medium", "high")
            and step.source != TaskStepSource.HUMAN_EDITED
        ):
            step.tool_args = await _resolve_step_args(db, task_id, step)

        step.status = TaskStepStatus.RUNNING
        step.started_at = step.started_at or datetime.utcnow()
        tenant_id, task_user_id = task.tenant_id, task.user_id
        tool_name, tool_args, step_id = step.tool_name, dict(step.tool_args or {}), step.id
        description = step.description
        # Resuming after a credit-exhaustion pause continues the SAME
        # attempt budget rather than granting a fresh 3 -- attempt_count
        # already reflects any attempt that happened before the pause
        # (see the quota_paused branch below).
        starting_attempt = (step.attempt_count or 0) + 1
        await db.commit()

    # The attempt loop runs outside any single DB transaction -- each
    # tool call and the (possible) LLM-adapt call open their own sessions
    # internally, matching this codebase's established pattern.
    last_error = None
    adapted_once = False
    quota_paused_attempt = None
    current_args = tool_args
    for attempt in range(starting_attempt, MAX_ATTEMPTS_PER_STEP + 1):
        try:
            result = await _call_tool(tenant_id, tool_name, current_args)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS_PER_STEP:
                await asyncio.sleep(TRANSIENT_RETRY_BACKOFF_SECONDS)
            continue

        if isinstance(result, dict) and result.get("error"):
            last_error = str(result["error"])
            if attempt < MAX_ATTEMPTS_PER_STEP and not adapted_once:
                # Credit exhaustion pauses the task instead of silently
                # degrading to an unadapted retry (Q4) -- the only real
                # LLM spend anywhere in step execution is this adapt call,
                # so this is the one place quota needs to be checked.
                quota = await get_quota_status(tenant_id, "ai_credits")
                if quota["status"] == "exceeded":
                    quota_paused_attempt = attempt
                    break
                current_args = await _adapt_step_args(
                    tenant_id, task_user_id, description, tool_name, current_args, last_error,
                )
                adapted_once = True
            continue

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
            step = r.scalar_one()
            step.status = TaskStepStatus.SUCCEEDED
            step.attempt_count = attempt
            step.tool_args = current_args
            step.raw_result = result
            step.outcome_summary = _outcome_summary(tool_name, result)
            step.completed_at = datetime.utcnow()

            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one()
            task.step_budget_used = (task.step_budget_used or 0) + 1

            outcome = {"outcome": "step_succeeded", "step_id": step_id, "attempt_count": attempt}

            if tool_name in _VERIFIABLE_TOOLS and _looks_like_async_dispatch(tool_name, result):
                # A genuinely new step, source=SYSTEM_INSERTED, appended
                # with a fresh unused step_index (existing steps are never
                # renumbered) and depending on the dispatching step's own
                # index -- never a status recycled onto the dispatching
                # step itself, so the timeline can always tell what AXIOM
                # planned from what the system added (amendment 3).
                r2 = await db.execute(select(func.max(TaskStep.step_index)).where(TaskStep.task_id == task_id))
                max_index = r2.scalar_one()
                verify_step = TaskStep(
                    id=str(uuid.uuid4()), task_id=task_id, step_index=(max_index or 0) + 1,
                    description=f'Verify that "{description}" reached a final state.',
                    source=TaskStepSource.SYSTEM_INSERTED,
                    tool_name=tool_name,  # what kind of dispatch to poll, not a tool to call again
                    tool_args={},
                    depends_on_step_index=step.step_index,
                    status=TaskStepStatus.VERIFYING,
                    raw_result=result,  # carries run_id etc. -- what _poll_dispatch_status reads
                    started_at=datetime.utcnow(),
                )
                db.add(verify_step)
                await db.flush()
                outcome["outcome"] = "step_dispatched_pending_verification"
                outcome["verify_step_id"] = verify_step.id

            await db.commit()

        return outcome

    if quota_paused_attempt is not None:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
            step = r.scalar_one()
            # This attempt genuinely happened and hit a real domain error
            # -- it counts. Back to PENDING (not FAILED): resuming picks up
            # at starting_attempt = attempt_count + 1, the SAME budget,
            # never a fresh 3.
            step.attempt_count = quota_paused_attempt
            step.error_message = last_error
            step.status = TaskStepStatus.PENDING

            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one()
            if _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_QUOTA_EXCEEDED):
                task.paused_at = datetime.utcnow()
            await db.commit()

        return {
            "outcome": "paused_quota_exceeded", "step_id": step_id,
            "attempt_count": quota_paused_attempt, "reason": last_error,
        }

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        step = r.scalar_one()
        step.status = TaskStepStatus.FAILED
        step.attempt_count = MAX_ATTEMPTS_PER_STEP
        step.error_message = last_error
        step.completed_at = datetime.utcnow()

        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
        await db.commit()

    return {
        "outcome": "step_failed", "step_id": step_id,
        "attempt_count": MAX_ATTEMPTS_PER_STEP, "reason": last_error,
    }


def _is_approval_expired(task: Task) -> bool:
    if task.paused_at is None:
        return False
    elapsed_hours = (datetime.utcnow() - task.paused_at).total_seconds() / 3600
    return elapsed_hours > APPROVAL_PAUSE_TIMEOUT_HOURS


async def resume_task(task_id: str, resolved_by: str, notes: str = "") -> dict:
    """Approves the blocked step's ApprovalRequest, then re-enters the
    normal execution pipeline for real -- this is deliberately NOT a
    special "continue" code path with its own logic. Everything that
    makes resume safe falls out of execute_next_step()'s existing,
    already-proven behavior: _caller_still_authorized() re-validates the
    initiating user's role/is_active fresh (Q5's authority requirement),
    and the tool call that follows is a genuine new call, not a cached
    replay, so it re-validates its own real-world preconditions (Q5's
    precondition requirement). Nothing here holds any in-memory state --
    a worker/backend restart between pause and resume changes nothing,
    since every fact this function reads comes from the DB."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status != TaskStatus.PAUSED_NEEDS_APPROVAL:
            return {"outcome": "not_resumable", "status": task.status.value}

        if _is_approval_expired(task):
            _set_task_status_unless_cancelled(task, TaskStatus.EXPIRED)
            await db.commit()
            await _notify_task_stopped(
                task, "Task expired",
                f'Task "{task.goal}" expired waiting for approval.', severity="medium",
            )
            return {"outcome": "expired"}

        r = await db.execute(
            select(TaskStep).where(
                TaskStep.task_id == task_id, TaskStep.status == TaskStepStatus.BLOCKED_APPROVAL,
            )
        )
        step = r.scalar_one_or_none()
        if step is None or step.approval_request_id is None:
            return {"outcome": "no_blocked_step"}

        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval_req = r.scalar_one()
        approval_req.status = ApprovalStatus.APPROVED
        approval_req.resolved_by = resolved_by
        approval_req.resolved_at = datetime.utcnow()
        approval_req.resolution_note = notes

        step.status = TaskStepStatus.PENDING
        _set_task_status_unless_cancelled(task, TaskStatus.RUNNING)
        await db.commit()

    return await execute_next_step(task_id)


async def reject_task_step(task_id: str, resolved_by: str, notes: str = "") -> dict:
    """Declines the blocked step outright -- no re-entry into execution,
    since there's nothing to re-attempt. Reuses the existing
    PAUSED_FAILED_STEP pause/pause_reason machinery rather than inventing
    a parallel one for "rejected" specifically."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status != TaskStatus.PAUSED_NEEDS_APPROVAL:
            return {"outcome": "not_resumable", "status": task.status.value}

        if _is_approval_expired(task):
            _set_task_status_unless_cancelled(task, TaskStatus.EXPIRED)
            await db.commit()
            await _notify_task_stopped(
                task, "Task expired",
                f'Task "{task.goal}" expired waiting for approval.', severity="medium",
            )
            return {"outcome": "expired"}

        r = await db.execute(
            select(TaskStep).where(
                TaskStep.task_id == task_id, TaskStep.status == TaskStepStatus.BLOCKED_APPROVAL,
            )
        )
        step = r.scalar_one_or_none()
        if step is None or step.approval_request_id is None:
            return {"outcome": "no_blocked_step"}

        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval_req = r.scalar_one()
        approval_req.status = ApprovalStatus.REJECTED
        approval_req.resolved_by = resolved_by
        approval_req.resolved_at = datetime.utcnow()
        approval_req.resolution_note = notes

        step.status = TaskStepStatus.FAILED
        step.error_message = f"Step rejected: {notes or 'no reason given'}."
        step.completed_at = datetime.utcnow()
        _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
        await db.commit()

    return {"outcome": "step_rejected", "step_id": step.id}


_NON_CANCELLABLE_STATUSES = (
    TaskStatus.COMPLETED, TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS,
    TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.PLAN_REJECTED, TaskStatus.EXPIRED,
)


async def cancel_task(task_id: str, cancelled_by: str) -> dict:
    """Marks the task CANCELLED immediately. Honest about what this can
    and cannot do: a step already in flight (its tool call already
    started in a concurrent request) cannot be interrupted -- there is no
    cooperative-cancellation plumbing in this codebase, and a plain DB
    write from a separate request has no way to stop an already-running
    `await` somewhere else. What IS guaranteed: every place
    execute_next_step() finishes a step goes through
    _set_task_status_unless_cancelled() before writing Task.status, so a
    step that finishes AFTER this call still gets its own real,
    factual outcome recorded (it may have genuinely succeeded), but the
    task-level status can never be silently stomped back from CANCELLED
    to RUNNING/COMPLETED/etc. -- see CLAUDE.md for the live-proved race."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status in _NON_CANCELLABLE_STATUSES:
            return {"outcome": "not_cancellable", "status": task.status.value}

        was_running = task.status == TaskStatus.RUNNING
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        task.termination_reason = (
            f"Cancelled by user {cancelled_by}."
            + (
                " A step may have been executing at the moment cancellation was requested; it "
                "cannot be interrupted mid-flight and may have completed after this task was "
                "cancelled -- check each step's own status for what actually happened."
                if was_running else ""
            )
        )
        await db.commit()
        await _notify_task_stopped(task, "Task cancelled", task.termination_reason, severity="low")

    return {"outcome": "cancelled"}
