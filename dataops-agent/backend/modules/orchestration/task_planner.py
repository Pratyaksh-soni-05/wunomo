"""LLM-driven plan generation for item 6 (long-running AXIOM tasks) --
stage 2, see docs/PRODUCT_AUDIT.md section 1.9 for the full design this
implements.

Deliberately narrow (amendment 4): each TaskShape is bound to a small,
fixed allowlist of real, already-registered agent tools, not the full
ALL_TOOLS surface -- the planning LLM is never asked to invent a step
using a tool outside that list, and validate_step_plan() rejects it if it
tries anyway (fail-closed, matching this codebase's TOOL_CAPABILITIES
convention). The same validate_step_plan() is also the validator
api/v1/tasks.py's PATCH /tasks/{id}/steps calls on a human-edited plan --
one function, not two independently-maintained copies that could drift,
so a human editing a plan is held to exactly the rules the planner itself
is bound by.
"""
import json

from agent.tools import ALL_TOOLS
from langchain_core.messages import SystemMessage, HumanMessage
from models.all_models import TaskShape
from services.llm_service import invoke_llm

# tenant_id/user_id/session_id/task_id are always force-injected server-side
# at execution time (agent_node's existing convention in dataops_agent.py,
# extended to task_id in _call_tool() for task execution) -- never asked of
# the planning LLM, never accepted in a persisted or human-edited
# TaskStep.tool_args.
_SERVER_INJECTED_ARGS = {"tenant_id", "user_id", "session_id", "task_id"}

MAX_PLAN_STEPS = 8
_MAX_GENERATION_ATTEMPTS = 2

# The narrow v1 task-shape -> allowed-tool mapping (amendment 4). Every
# name here must be a real tool in agent.tools.ALL_TOOLS -- guarded by
# _validate_allowlist_at_import_time() below, same fail-closed-at-boot
# pattern as dataops_agent.py's TOOL_CAPABILITIES assertion.
TASK_SHAPE_ALLOWED_TOOLS: dict[TaskShape, list[str]] = {
    TaskShape.DIAGNOSE_PIPELINE_FAILURE: [
        "list_pipelines", "get_pipeline_run_history", "check_freshness", "get_cicd_status", "get_system_health",
    ],
    TaskShape.INVESTIGATE_INCIDENT: [
        "list_open_incidents", "triage_incident", "resolve_incident", "list_pipelines", "get_pipeline_run_history",
    ],
    TaskShape.SYNC_PROFILE_QUALITY: [
        "list_data_sources", "sync_source", "profile_schema", "run_quality_checks", "get_quality_report",
    ],
}


class PlanGenerationError(Exception):
    """The LLM call itself (or its output) never produced a valid plan,
    even after the one corrective retry. Nothing is persisted when this
    is raised -- see api/v1/tasks.py's POST /tasks/."""


class PlanValidationError(Exception):
    """A step list (LLM-generated or human-edited) fails structural
    validation: bad tool name, args outside the tool's real schema,
    missing required args, empty/oversized plan, or a forward-referencing
    dependency."""


def tool_by_name(name: str):
    return next((t for t in ALL_TOOLS if t.name == name), None)


def tool_schema_for_prompt(tool_name: str) -> dict:
    """A tool's arg schema with server-injected args stripped -- neither
    the planning LLM nor a human editor should ever be asked for (or
    allowed to supply) tenant_id/user_id/session_id."""
    tool_obj = tool_by_name(tool_name)
    if tool_obj is None:
        return {}
    return {name: schema for name, schema in tool_obj.args.items() if name not in _SERVER_INJECTED_ARGS}


def validate_step_plan(task_shape: TaskShape, steps: list) -> None:
    """Raises PlanValidationError with a specific, actionable reason on
    the first violation found. This is the single validator both plan
    generation and PATCH /tasks/{id}/steps call -- see module docstring."""
    allowed_tools = set(TASK_SHAPE_ALLOWED_TOOLS.get(task_shape, []))

    if not isinstance(steps, list) or not steps:
        raise PlanValidationError("A plan must be a non-empty list of steps.")
    if len(steps) > MAX_PLAN_STEPS:
        raise PlanValidationError(f"A plan may have at most {MAX_PLAN_STEPS} steps (got {len(steps)}).")

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanValidationError(f"Step {i}: must be an object.")

        tool_name = step.get("tool_name")
        if not tool_name:
            raise PlanValidationError(f"Step {i}: missing tool_name.")
        if tool_name not in allowed_tools:
            raise PlanValidationError(
                f"Step {i}: tool '{tool_name}' is not permitted for shape "
                f"'{task_shape.value}' (allowed: {sorted(allowed_tools)})."
            )

        tool_args = step.get("tool_args")
        if tool_args is None:
            tool_args = {}
        if not isinstance(tool_args, dict):
            raise PlanValidationError(f"Step {i}: tool_args must be a JSON object.")

        schema = tool_schema_for_prompt(tool_name)
        unknown_args = set(tool_args) - set(schema)
        if unknown_args:
            raise PlanValidationError(
                f"Step {i}: unknown argument(s) for '{tool_name}': {sorted(unknown_args)}."
            )
        missing_required = {
            name for name, spec in schema.items()
            if "default" not in spec and name not in tool_args
        }
        if missing_required:
            raise PlanValidationError(
                f"Step {i}: '{tool_name}' is missing required argument(s): {sorted(missing_required)}."
            )

        depends_on = step.get("depends_on_step_index")
        if depends_on is not None and (not isinstance(depends_on, int) or not (0 <= depends_on < i)):
            raise PlanValidationError(f"Step {i}: depends_on_step_index must reference an earlier step.")

        if not step.get("description"):
            raise PlanValidationError(f"Step {i}: missing a human-readable description.")


def _build_prompt(goal: str, task_shape: TaskShape) -> str:
    allowed_tools = TASK_SHAPE_ALLOWED_TOOLS[task_shape]
    tool_lines = []
    for name in allowed_tools:
        tool_obj = tool_by_name(name)
        schema = tool_schema_for_prompt(name)
        tool_lines.append(f"- {name}: {tool_obj.description}\n  arguments (JSON schema): {json.dumps(schema)}")
    return (
        f"Goal: {goal}\n\n"
        f'This task is scoped to the "{task_shape.value}" shape. You may ONLY use these tools:\n'
        + "\n".join(tool_lines)
        + "\n\nProduce a JSON array of steps, in execution order, to achieve the goal. "
        'Each step is an object: {"description": "<one sentence, human-readable>", '
        '"tool_name": "<one of the tools above>", "tool_args": {<only the arguments '
        'shown in that tool\'s schema above>}, "depends_on_step_index": <int index of an '
        "earlier step this one needs, or null>}.\n"
        f"Use at most {MAX_PLAN_STEPS} steps. Never include tenant_id, user_id, or "
        "session_id in tool_args -- those are supplied automatically. "
        "Return ONLY the JSON array, no other text."
    )


async def generate_plan(
    tenant_id: str, user_id: str, goal: str, task_shape: TaskShape, task_id: str | None = None,
) -> list:
    """Real LLM call -- the caller (api/v1/tasks.py) is responsible for
    checking quota before calling this. One automatic corrective retry on
    a malformed/invalid response (LLM JSON output is occasionally flaky
    in a way a stricter reprompt reliably fixes) before raising
    PlanGenerationError -- never loops, never returns a partially-valid
    plan. invoke_llm() already logs usage and normalizes structured
    content internally (see services/llm_service.py).

    task_id is optional and purely for cost attribution (it's generated by
    the caller before the Task row itself exists, precisely so this call's
    usage can be tagged with it) -- a caller that doesn't have one yet
    (or a test) can omit it; log_llm_usage() just logs task_id=None. If
    this call succeeds but the plan it produced still fails validation
    (PlanGenerationError below), the real llm_usage_events row(s) already
    written will carry a task_id whose Task was never persisted -- see
    api/v1/tasks.py's create_task(), which discards the plan entirely on
    that path. That's expected, not a bug: the spend was real even though
    the task never was."""
    system_prompt = (
        "You are AXIOM's task planner. You output ONLY a JSON array matching "
        "the requested schema -- no prose, no markdown fences, no explanation."
    )
    user_message = _build_prompt(goal, task_shape)
    last_error = None

    for attempt in range(_MAX_GENERATION_ATTEMPTS):
        prompt = user_message if attempt == 0 else (
            f"{user_message}\n\nYour previous response was invalid: {last_error}. "
            "Return ONLY a valid JSON array matching the schema."
        )
        try:
            raw = await invoke_llm(
                [SystemMessage(content=system_prompt), HumanMessage(content=prompt)],
                tenant_id=tenant_id, user_id=user_id, task_id=task_id, request_type="task_planning",
            )
        except Exception as exc:
            last_error = f"LLM call failed: {exc}"
            continue

        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            steps = json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = f"response was not valid JSON ({exc})"
            continue

        try:
            validate_step_plan(task_shape, steps)
        except PlanValidationError as exc:
            last_error = str(exc)
            continue

        return steps

    raise PlanGenerationError(f"Failed to generate a valid plan after {_MAX_GENERATION_ATTEMPTS} attempts: {last_error}")


def _validate_allowlist_at_import_time() -> None:
    """Fail-closed at boot, same pattern as dataops_agent.py's
    TOOL_CAPABILITIES assertion -- a shape referencing a tool that doesn't
    exist (typo, renamed tool) must crash the process, not silently
    produce a planner that can never succeed."""
    real_tool_names = {t.name for t in ALL_TOOLS}
    for shape, tools in TASK_SHAPE_ALLOWED_TOOLS.items():
        unknown = set(tools) - real_tool_names
        assert not unknown, f"TASK_SHAPE_ALLOWED_TOOLS['{shape.value}'] references non-existent tool(s): {unknown}"


_validate_allowlist_at_import_time()
