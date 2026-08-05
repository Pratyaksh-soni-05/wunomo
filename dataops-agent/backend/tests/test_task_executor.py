"""Item 6 stage 3: the execution core's failure-tier state machine. These
tests mock at the _call_tool/_adapt_step_args boundary -- the honest way
to deterministically exercise each tier's logic (real timing/network
flakiness isn't safely reproducible on demand). Live proof against real
tools, a real deleted pipeline, and a real mid-task role demotion lives
in test_task_executor_live.py -- see that file for what's actually live
vs. a test double, stated explicitly.
"""
import uuid

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import execute_next_step
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus, User


async def _register(client, prefix="taskexec"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Exec Test",
        "tenant_name": f"Task Exec Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_queued_task(tenant_id: str, user_id: str, tool_name="get_pipeline_run_history", tool_args=None):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.QUEUED, step_budget_max=20,
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="check history", source=TaskStepSource.LLM_PLANNED,
            tool_name=tool_name, tool_args=tool_args or {"pipeline_id": "pl-1"},
            status=TaskStepStatus.PENDING,
        )
        db.add(step)
        await db.commit()
        return task.id, step.id


async def _fresh(task_id, step_id):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        step = r.scalar_one()
        return task, step


@pytest.mark.asyncio
async def test_step_succeeds_on_first_attempt(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execsuccess")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)

    async def _fake_call_tool(tenant_id, tool_name, tool_args):
        return {"pipeline_id": "pl-1", "runs": []}

    monkeypatch.setattr(executor_module, "_call_tool", _fake_call_tool)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_succeeded"
    assert outcome["attempt_count"] == 1

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.SUCCEEDED
    assert step.attempt_count == 1
    assert task.status == TaskStatus.RUNNING
    assert task.step_budget_used == 1


@pytest.mark.asyncio
async def test_permission_denied_blocks_immediately_attempt_count_one_no_tool_call(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execperm")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id, tool_name="check_freshness", tool_args={})

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run when the role check fails")

    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    # check_freshness requires "sources.profile" -- demote to viewer (only "view").
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    assert outcome["attempt_count"] == 1

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert step.attempt_count == 1
    assert "permission" in step.error_message.lower() or "no longer" in step.error_message.lower()
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


@pytest.mark.asyncio
async def test_deactivated_user_blocks_the_next_step(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execdeactivated")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run once the user is deactivated")

    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.is_active = False
        await db.commit()

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    task, step = await _fresh(task_id, step_id)
    assert "no longer active" in step.error_message


@pytest.mark.asyncio
async def test_transient_exception_gets_one_retry_then_succeeds_no_llm(client, monkeypatch):
    tenant_id, user_id = await _register(client, "exectransient")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)

    calls = {"n": 0}

    async def _flaky_then_ok(tenant_id, tool_name, tool_args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated transient network blip")
        return {"pipeline_id": "pl-1", "runs": []}

    async def _fail_if_adapted(*a, **k):
        raise AssertionError("a transient exception must never trigger an LLM-adapt call")

    monkeypatch.setattr(executor_module, "_call_tool", _flaky_then_ok)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _fail_if_adapted)
    monkeypatch.setattr(executor_module, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0)  # don't slow the test down

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_succeeded"
    assert outcome["attempt_count"] == 2
    assert calls["n"] == 2

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.SUCCEEDED
    assert step.attempt_count == 2


@pytest.mark.asyncio
async def test_transient_exception_exhausts_budget_and_pauses(client, monkeypatch):
    tenant_id, user_id = await _register(client, "exectransientfail")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)

    async def _always_raises(tenant_id, tool_name, tool_args):
        raise TimeoutError("simulated persistent timeout")

    monkeypatch.setattr(executor_module, "_call_tool", _always_raises)
    monkeypatch.setattr(executor_module, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_failed"
    assert outcome["attempt_count"] == 3
    assert "TimeoutError" in outcome["reason"]

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert step.attempt_count == 3
    assert "simulated persistent timeout" in step.error_message
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


@pytest.mark.asyncio
async def test_domain_error_triggers_exactly_one_adapt_call_then_succeeds(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execdomain")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id, tool_args={"pipeline_id": "bad-id"})

    calls = {"n": 0}
    adapt_calls = {"n": 0}

    async def _not_found_then_ok(tenant_id, tool_name, tool_args):
        calls["n"] += 1
        if tool_args.get("pipeline_id") == "bad-id":
            return {"error": "Pipeline not found"}
        return {"pipeline_id": tool_args["pipeline_id"], "runs": []}

    async def _fake_adapt(tenant_id, user_id, description, tool_name, tool_args, error_message):
        adapt_calls["n"] += 1
        assert "Pipeline not found" in error_message
        return {"pipeline_id": "corrected-id"}

    monkeypatch.setattr(executor_module, "_call_tool", _not_found_then_ok)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _fake_adapt)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_succeeded"
    assert adapt_calls["n"] == 1
    assert calls["n"] == 2

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.SUCCEEDED
    assert step.tool_args == {"pipeline_id": "corrected-id"}


@pytest.mark.asyncio
async def test_domain_error_adapt_still_fails_exhausts_budget_with_one_adapt_call_only(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execdomainfail")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id, tool_args={"pipeline_id": "gone-forever"})

    adapt_calls = {"n": 0}

    async def _always_not_found(tenant_id, tool_name, tool_args):
        return {"error": "Pipeline not found"}

    async def _fake_adapt(tenant_id, user_id, description, tool_name, tool_args, error_message):
        adapt_calls["n"] += 1
        return tool_args  # can't actually fix a genuinely deleted pipeline

    monkeypatch.setattr(executor_module, "_call_tool", _always_not_found)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _fake_adapt)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_failed"
    assert outcome["attempt_count"] == 3
    assert adapt_calls["n"] == 1  # never called a second time even though 3 attempts happened

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert "Pipeline not found" in step.error_message
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


@pytest.mark.asyncio
async def test_task_completes_only_once_no_pending_steps_remain(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execcomplete")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)

    async def _ok(tenant_id, tool_name, tool_args):
        return {"pipeline_id": "pl-1", "runs": []}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    first = await execute_next_step(task_id)
    assert first["outcome"] == "step_succeeded"
    task, _ = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.RUNNING  # not yet detected as complete

    second = await execute_next_step(task_id)
    assert second["outcome"] == "task_completed"
    task, _ = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_a_non_runnable_task_is_a_safe_noop(client, monkeypatch):
    tenant_id, user_id = await _register(client, "execnotrunnable")
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.DRAFT_PLAN, step_budget_max=20,
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "not_runnable"
    assert outcome["status"] == "draft_plan"
