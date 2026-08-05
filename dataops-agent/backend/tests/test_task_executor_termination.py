"""Item 6 stage 6: termination (Q4) -- step/wall-clock/credit caps, loop
detection, and real Cancel, including the cancel-mid-flight race proven
directly (not just asserted) via a real concurrent asyncio task, matching
the drift-test standard of proving a check can actually go red.
"""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import cancel_task, execute_next_step
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus, User


async def _register(client, prefix="taskterm"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Termination Test",
        "tenant_name": f"Task Termination Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_task(tenant_id, user_id, steps: list[dict], **task_overrides):
    defaults = {"status": TaskStatus.QUEUED, "step_budget_max": 20}
    defaults.update(task_overrides)
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            **defaults,
        )
        db.add(task)
        await db.flush()
        step_ids = []
        for s in steps:
            ts = TaskStep(id=str(uuid.uuid4()), task_id=task.id, **s)
            db.add(ts)
            step_ids.append(ts.id)
        await db.commit()
        return task.id, step_ids


async def _fresh(task_id, step_id=None):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        if step_id is None:
            return task
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        return task, r.scalar_one()


@pytest.mark.asyncio
async def test_wall_clock_cap_terminates_with_a_specific_reason(client, monkeypatch):
    tenant_id, user_id = await _register(client, "wallclock")
    task_id, (step_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow() - timedelta(hours=999))

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_wall_clock"
    assert "wall-clock" in outcome["reason"]

    task = await _fresh(task_id)
    assert task.status == TaskStatus.FAILED
    assert "wall-clock" in task.termination_reason
    assert "hour" in task.termination_reason


@pytest.mark.asyncio
async def test_step_budget_cap_terminates_with_a_specific_reason(client):
    tenant_id, user_id = await _register(client, "stepbudget")
    task_id, (step_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow(), step_budget_max=5, step_budget_used=5)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_step_budget"
    assert "5-step budget" in outcome["reason"]
    assert "5/5" in outcome["reason"]

    task = await _fresh(task_id)
    assert task.status == TaskStatus.FAILED
    assert "step budget" in task.termination_reason


@pytest.mark.asyncio
async def test_loop_detection_does_not_false_positive_on_a_normal_plan(client, monkeypatch):
    """The negative proof: a normal, varied plan must run to completion
    without ever being flagged as a loop."""
    tenant_id, user_id = await _register(client, "noloopfalse")
    task_id, step_ids = await _seed_task(tenant_id, user_id, [
        {"step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING},
        {"step_index": 1, "description": "check history for pipeline A", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "get_pipeline_run_history", "tool_args": {"pipeline_id": "pl-a"}, "status": TaskStepStatus.PENDING},
        {"step_index": 2, "description": "check freshness", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "check_freshness", "tool_args": {}, "status": TaskStepStatus.PENDING},
    ], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _ok(tenant_id, tool_name, tool_args):
        return {"status": "ok"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    for _ in range(3):
        outcome = await execute_next_step(task_id)
        assert not outcome["outcome"].startswith("terminated_")
    final = await execute_next_step(task_id)
    assert final["outcome"] == "task_completed"


@pytest.mark.asyncio
async def test_loop_detection_catches_a_real_repeated_no_progress_pattern(client):
    """The positive proof, same standard as the drift test: construct an
    actual loop (same tool, same args, no progress) and confirm it's
    caught, not just that normal tasks don't trip it."""
    tenant_id, user_id = await _register(client, "realloop")
    identical = {"tool_args": {"pipeline_id": "stuck-pl"}}
    task_id, step_ids = await _seed_task(tenant_id, user_id, [
        {"step_index": 0, "description": "check history attempt 1", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "get_pipeline_run_history", "status": TaskStepStatus.SUCCEEDED, **identical},
        {"step_index": 1, "description": "check history attempt 2", "source": TaskStepSource.HUMAN_EDITED,
         "tool_name": "get_pipeline_run_history", "status": TaskStepStatus.SUCCEEDED, **identical},
        {"step_index": 2, "description": "check history attempt 3", "source": TaskStepSource.HUMAN_EDITED,
         "tool_name": "get_pipeline_run_history", "status": TaskStepStatus.PENDING, **identical},
    ], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_loop_detected"
    assert "get_pipeline_run_history" in outcome["reason"]
    assert "3 times" in outcome["reason"]

    task = await _fresh(task_id)
    assert task.status == TaskStatus.FAILED
    assert "loop" in task.termination_reason.lower()
    # The step that was genuinely still pending never got a chance to
    # run -- the loop check fires before step selection.
    _, unrun_step = await _fresh(task_id, step_ids[2])
    assert unrun_step.status == TaskStepStatus.PENDING


@pytest.mark.asyncio
async def test_loop_detection_ignores_system_inserted_verify_steps(client):
    """Every SYSTEM_INSERTED verify step shares the same empty tool_args
    ({}) by construction -- 3 legitimate, DIFFERENT real dispatches must
    not collide into a false-positive loop just because their verify
    steps all look identical."""
    tenant_id, user_id = await _register(client, "loopverifyskip")
    task_id, step_ids = await _seed_task(tenant_id, user_id, [
        {"step_index": 0, "description": "trigger run A", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "run_pipeline", "tool_args": {"pipeline_id": "pl-a"}, "status": TaskStepStatus.SUCCEEDED},
        {"step_index": 1, "description": "verify run A", "source": TaskStepSource.SYSTEM_INSERTED,
         "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.SUCCEEDED, "depends_on_step_index": 0},
        {"step_index": 2, "description": "trigger run B", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "run_pipeline", "tool_args": {"pipeline_id": "pl-b"}, "status": TaskStepStatus.SUCCEEDED},
        {"step_index": 3, "description": "verify run B", "source": TaskStepSource.SYSTEM_INSERTED,
         "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.SUCCEEDED, "depends_on_step_index": 2},
        {"step_index": 4, "description": "trigger run C", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "run_pipeline", "tool_args": {"pipeline_id": "pl-c"}, "status": TaskStepStatus.SUCCEEDED},
        {"step_index": 5, "description": "verify run C", "source": TaskStepSource.SYSTEM_INSERTED,
         "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.SUCCEEDED, "depends_on_step_index": 4},
    ], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "task_completed"


@pytest.mark.asyncio
async def test_credit_exhaustion_pauses_not_fails(client, monkeypatch):
    tenant_id, user_id = await _register(client, "quotapause")
    task_id, (step_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check history", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_pipeline_run_history", "tool_args": {"pipeline_id": "bad-id"},
        "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _domain_error(tenant_id, tool_name, tool_args):
        return {"error": "Pipeline not found"}

    async def _quota_exceeded(tenant_id, resource):
        return {"resource": resource, "status": "exceeded", "used": 999999, "limit": 25000}

    async def _fail_if_adapted(*a, **k):
        raise AssertionError("must not attempt to adapt once quota is exceeded")

    monkeypatch.setattr(executor_module, "_call_tool", _domain_error)
    monkeypatch.setattr(executor_module, "get_quota_status", _quota_exceeded)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _fail_if_adapted)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "paused_quota_exceeded"
    assert outcome["attempt_count"] == 1

    task, step = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.PAUSED_QUOTA_EXCEEDED
    assert task.paused_at is not None
    assert step.status == TaskStepStatus.PENDING  # reset for a later pickup, not FAILED
    assert step.attempt_count == 1  # the attempt that hit the domain error genuinely happened


@pytest.mark.asyncio
async def test_resume_after_quota_pause_continues_the_same_attempt_budget_not_a_fresh_one(client, monkeypatch):
    tenant_id, user_id = await _register(client, "quotaresume")
    task_id, (step_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check history", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_pipeline_run_history", "tool_args": {"pipeline_id": "bad-id"},
        "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _domain_error(tenant_id, tool_name, tool_args):
        return {"error": "Pipeline not found"}

    async def _quota_exceeded(tenant_id, resource):
        return {"resource": resource, "status": "exceeded", "used": 999999, "limit": 25000}

    monkeypatch.setattr(executor_module, "_call_tool", _domain_error)
    monkeypatch.setattr(executor_module, "get_quota_status", _quota_exceeded)

    first = await execute_next_step(task_id)
    assert first["outcome"] == "paused_quota_exceeded"
    task = await _fresh(task_id)
    assert task.status == TaskStatus.PAUSED_QUOTA_EXCEEDED

    # Quota frees up; the step also happens to succeed on the next real attempt.
    async def _quota_ok(tenant_id, resource):
        return {"resource": resource, "status": "ok", "used": 100, "limit": 25000}

    async def _now_ok(tenant_id, tool_name, tool_args):
        return {"pipeline_id": "bad-id", "runs": []}

    monkeypatch.setattr(executor_module, "get_quota_status", _quota_ok)
    monkeypatch.setattr(executor_module, "_call_tool", _now_ok)

    second = await execute_next_step(task_id)
    assert second["outcome"] == "step_succeeded"
    # Continued from attempt 2 (attempt 1 already happened before the
    # pause), not reset to a fresh budget of 3.
    assert second["attempt_count"] == 2

    task, step = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.RUNNING
    assert step.status == TaskStepStatus.SUCCEEDED
    assert step.attempt_count == 2


@pytest.mark.asyncio
async def test_cancel_marks_cancelled_and_a_second_cancel_is_rejected(client):
    tenant_id, user_id = await _register(client, "cancelbasic")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    result = await cancel_task(task_id, cancelled_by=user_id)
    assert result["outcome"] == "cancelled"
    task = await _fresh(task_id)
    assert task.status == TaskStatus.CANCELLED
    assert task.termination_reason is not None
    assert user_id in task.termination_reason

    result2 = await cancel_task(task_id, cancelled_by=user_id)
    assert result2["outcome"] == "not_cancellable"

    # And execute_next_step correctly refuses to touch a cancelled task.
    advance_attempt = await execute_next_step(task_id)
    assert advance_attempt["outcome"] == "not_runnable"


@pytest.mark.asyncio
async def test_cancel_of_a_completed_task_is_not_cancellable(client, monkeypatch):
    tenant_id, user_id = await _register(client, "cancelcompleted")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _ok(tenant_id, tool_name, tool_args):
        return {"status": "ok"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)
    await execute_next_step(task_id)
    final = await execute_next_step(task_id)
    assert final["outcome"] == "task_completed"

    result = await cancel_task(task_id, cancelled_by=user_id)
    assert result["outcome"] == "not_cancellable"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_step_in_flight_when_cancelled_still_records_its_real_outcome_but_task_stays_cancelled(client, monkeypatch):
    """The real race, constructed directly rather than just asserted:
    a step is genuinely mid-flight (inside the real transient-retry
    backoff sleep) when a concurrent cancel() call lands. Proves what
    actually happens: the step completes and its real outcome is
    recorded, but Task.status is never stomped back from CANCELLED."""
    tenant_id, user_id = await _register(client, "cancelrace")
    task_id, (step_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "flaky call", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    calls = {"n": 0}

    async def _flaky_then_ok(tenant_id, tool_name, tool_args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated transient failure -- creates a real in-flight window")
        return {"status": "ok"}

    monkeypatch.setattr(executor_module, "_call_tool", _flaky_then_ok)
    monkeypatch.setattr(executor_module, "TRANSIENT_RETRY_BACKOFF_SECONDS", 1.5)

    # Start the step execution as a real concurrent task -- it will hit
    # the transient exception, then genuinely sleep for 1.5s before its
    # retry. While it's asleep (genuinely in flight), cancel the task.
    step_task = asyncio.create_task(execute_next_step(task_id))
    await asyncio.sleep(0.3)  # let it reach the real backoff sleep
    cancel_result = await cancel_task(task_id, cancelled_by=user_id)
    assert cancel_result["outcome"] == "cancelled"

    step_outcome = await step_task  # let the in-flight step finish for real
    assert step_outcome["outcome"] == "step_succeeded"  # it genuinely did succeed on retry

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.SUCCEEDED  # true, factual outcome recorded
    assert task.status == TaskStatus.CANCELLED  # NOT stomped back to RUNNING by the step's own completion
    assert "cannot be interrupted mid-flight" in task.termination_reason
