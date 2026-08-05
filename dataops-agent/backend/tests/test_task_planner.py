"""Unit tests for modules/orchestration/task_planner.py's validate_step_plan()
-- the one validator both plan generation and PATCH /tasks/{id}/steps call
(see the module docstring). No LLM calls in this file; that's covered
separately (live, quota-conscious) in test_tasks_api.py.
"""
import pytest

from modules.orchestration.task_planner import (
    MAX_PLAN_STEPS, PlanValidationError, TASK_SHAPE_ALLOWED_TOOLS, validate_step_plan,
)
from models.all_models import TaskShape

SHAPE = TaskShape.DIAGNOSE_PIPELINE_FAILURE  # read-only allowlist, no server-injected args to worry about


def _step(**overrides) -> dict:
    base = {
        "description": "Check pipeline run history",
        "tool_name": "get_pipeline_run_history",
        "tool_args": {"pipeline_id": "pl-1"},
        "depends_on_step_index": None,
    }
    base.update(overrides)
    return base


def test_a_valid_plan_passes():
    validate_step_plan(SHAPE, [_step()])  # must not raise


def test_empty_plan_is_rejected():
    with pytest.raises(PlanValidationError, match="non-empty"):
        validate_step_plan(SHAPE, [])


def test_oversized_plan_is_rejected():
    steps = [_step(description=f"step {i}") for i in range(MAX_PLAN_STEPS + 1)]
    with pytest.raises(PlanValidationError, match="at most"):
        validate_step_plan(SHAPE, steps)


def test_tool_outside_the_shapes_allowlist_is_rejected():
    """A tool real elsewhere in the system, but not permitted for THIS
    shape, must still be rejected -- the allowlist is per-shape, not a
    check that the tool exists somewhere in ALL_TOOLS."""
    with pytest.raises(PlanValidationError, match="not permitted"):
        validate_step_plan(SHAPE, [_step(tool_name="sync_source", tool_args={"source_id": "s-1"})])


def test_nonexistent_tool_name_is_rejected():
    with pytest.raises(PlanValidationError, match="not permitted"):
        validate_step_plan(SHAPE, [_step(tool_name="delete_everything", tool_args={})])


def test_server_injected_args_are_never_valid_in_tool_args():
    """tenant_id must never be accepted as an LLM- or human-supplied
    argument -- it's force-injected server-side at execution time."""
    with pytest.raises(PlanValidationError, match="unknown argument"):
        validate_step_plan(SHAPE, [_step(tool_args={"pipeline_id": "pl-1", "tenant_id": "sneaky"})])


def test_unknown_argument_name_is_rejected():
    with pytest.raises(PlanValidationError, match="unknown argument"):
        validate_step_plan(SHAPE, [_step(tool_args={"pipeline_id": "pl-1", "made_up_arg": "x"})])


def test_missing_required_argument_is_rejected():
    with pytest.raises(PlanValidationError, match="missing required"):
        validate_step_plan(SHAPE, [_step(tool_args={})])  # pipeline_id is required


def test_optional_argument_may_be_omitted():
    """get_pipeline_run_history's `limit` has a default -- a plan that
    omits it must still validate."""
    validate_step_plan(SHAPE, [_step(tool_args={"pipeline_id": "pl-1"})])


def test_depends_on_step_index_must_reference_an_earlier_step():
    steps = [_step(), _step(depends_on_step_index=1)]  # step 1 depending on itself
    with pytest.raises(PlanValidationError, match="depends_on_step_index"):
        validate_step_plan(SHAPE, steps)


def test_depends_on_step_index_forward_reference_is_rejected():
    steps = [_step(depends_on_step_index=1), _step()]  # step 0 depending on a later step
    with pytest.raises(PlanValidationError, match="depends_on_step_index"):
        validate_step_plan(SHAPE, steps)


def test_valid_backward_dependency_is_accepted():
    steps = [_step(), _step(depends_on_step_index=0)]
    validate_step_plan(SHAPE, steps)  # must not raise


def test_missing_description_is_rejected():
    with pytest.raises(PlanValidationError, match="description"):
        validate_step_plan(SHAPE, [_step(description="")])


def test_every_shape_allowlist_references_only_real_tools():
    """Mirrors the module's own import-time assertion as a normal,
    discoverable pytest failure rather than only a boot-time crash."""
    from agent.tools import ALL_TOOLS
    real_names = {t.name for t in ALL_TOOLS}
    for shape, tools in TASK_SHAPE_ALLOWED_TOOLS.items():
        unknown = set(tools) - real_names
        assert not unknown, f"{shape.value}: {unknown}"
