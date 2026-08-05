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


async def execute_next_step(task_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            return {"outcome": "not_runnable", "status": task.status.value}

        if task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.RUNNING
            task.started_at = task.started_at or datetime.utcnow()
            await db.commit()

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        all_steps = {s.step_index: s for s in r.scalars().all()}

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
                task.status = TaskStatus.PAUSED_FAILED_STEP
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
                    task.status = TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS
                    task.completed_at = datetime.utcnow()
                    await db.commit()
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
                task.status = TaskStatus.PAUSED_FAILED_STEP
                await db.commit()
                return {"outcome": "blocked_on_dependency"}
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await db.commit()
            return {"outcome": "task_completed"}

        authorized, denial_reason = await _caller_still_authorized(db, task, step.tool_name)
        if not authorized:
            step.attempt_count += 1
            step.status = TaskStepStatus.FAILED
            step.error_message = f"Blocked: {denial_reason}."
            step.started_at = step.started_at or datetime.utcnow()
            step.completed_at = datetime.utcnow()
            task.status = TaskStatus.PAUSED_FAILED_STEP
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
            approval = await PolicyEngine(task.tenant_id).create_request(
                user_id=task.user_id, session_id=task.id, action_name=step.tool_name,
                action_args=step.tool_args or {}, risk_level=get_risk_level(step.tool_name),
                reason=f'Task step "{step.description}" requires approval before it can run.',
            )
            step.approval_request_id = approval["approval_id"]
            step.status = TaskStepStatus.BLOCKED_APPROVAL
            task.status = TaskStatus.PAUSED_NEEDS_APPROVAL
            task.paused_at = datetime.utcnow()
            await db.commit()
            return {
                "outcome": "blocked_needs_approval", "step_id": step.id,
                "approval_request_id": approval["approval_id"], "risk_level": approval["risk_level"],
            }

        if step.approval_request_id is not None:
            r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
            approval_req = r.scalar_one_or_none()
            if approval_req is None or approval_req.status == ApprovalStatus.PENDING:
                task.status = TaskStatus.PAUSED_NEEDS_APPROVAL
                await db.commit()
                return {"outcome": "still_blocked_needs_approval", "step_id": step.id}
            if approval_req.status == ApprovalStatus.REJECTED:
                step.status = TaskStepStatus.FAILED
                step.error_message = f"Step rejected: {approval_req.resolution_note or 'no reason given'}."
                step.completed_at = datetime.utcnow()
                task.status = TaskStatus.PAUSED_FAILED_STEP
                await db.commit()
                return {"outcome": "step_rejected", "step_id": step.id, "reason": step.error_message}
            # APPROVED (or, defensively, any other resolved state) -- fall
            # through to real execution below. This is the resume path:
            # the tool call that follows is a genuine, fresh call -- not a
            # cached replay -- so it re-validates its own preconditions
            # and, one line above, _caller_still_authorized() already
            # re-validated the initiating user's authority for real.

        step.status = TaskStepStatus.RUNNING
        step.started_at = step.started_at or datetime.utcnow()
        tenant_id, task_user_id = task.tenant_id, task.user_id
        tool_name, tool_args, step_id = step.tool_name, dict(step.tool_args or {}), step.id
        description = step.description
        await db.commit()

    # The attempt loop runs outside any single DB transaction -- each
    # tool call and the (possible) LLM-adapt call open their own sessions
    # internally, matching this codebase's established pattern.
    last_error = None
    adapted_once = False
    current_args = tool_args
    for attempt in range(1, MAX_ATTEMPTS_PER_STEP + 1):
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

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        step = r.scalar_one()
        step.status = TaskStepStatus.FAILED
        step.attempt_count = MAX_ATTEMPTS_PER_STEP
        step.error_message = last_error
        step.completed_at = datetime.utcnow()

        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.status = TaskStatus.PAUSED_FAILED_STEP
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
            task.status = TaskStatus.EXPIRED
            await db.commit()
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
        task.status = TaskStatus.RUNNING
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
            task.status = TaskStatus.EXPIRED
            await db.commit()
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
        task.status = TaskStatus.PAUSED_FAILED_STEP
        await db.commit()

    return {"outcome": "step_rejected", "step_id": step.id}
