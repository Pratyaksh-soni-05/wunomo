"""Item 6 (long-running AXIOM tasks) -- stage 3, the execution core. See
docs/PRODUCT_AUDIT.md section 1.9 for the design this implements (Q1's
failure-tier policy, amendment 3's per-step fresh role re-check).

execute_next_step(task_id) advances a QUEUED/RUNNING task by exactly one
step, resolving that step to a terminal state (SUCCEEDED or FAILED)
internally -- including whatever retries/adaptation its failure tier
calls for -- before returning. It is directly callable (tests, live
verification, manual driving via POST /tasks/{id}/advance) and is the
whole of what "let a step run" means in this codebase; no automatic
Celery scheduling is wired yet (deliberately out of stage 3's scope --
see CLAUDE.md).

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
"""
import asyncio
import json
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from database import AsyncSessionLocal
from modules.orchestration.task_planner import tool_by_name, tool_schema_for_prompt
from models.all_models import Task, TaskStatus, TaskStep, TaskStepStatus, User
from services.llm_service import invoke_llm
from services.quota_service import get_quota_status
from services.rbac import TOOL_CAPABILITIES, has_permission

MAX_ATTEMPTS_PER_STEP = 3  # 1 initial + up to 2 recovery attempts
TRANSIENT_RETRY_BACKOFF_SECONDS = 2

TIER_PERMISSION = "permission"
TIER_TRANSIENT = "transient"
TIER_DOMAIN = "domain"


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


async def execute_next_step(task_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            return {"outcome": "not_runnable", "status": task.status.value}

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        all_steps = {s.step_index: s for s in r.scalars().all()}
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

        if task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.RUNNING
            task.started_at = task.started_at or datetime.utcnow()

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
            await db.commit()

        return {"outcome": "step_succeeded", "step_id": step_id, "attempt_count": attempt}

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
