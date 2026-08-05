"""Item 6 stage 4: verification (Q2). Mocked at the _call_tool/
_poll_dispatch_status boundary for deterministic, fast coverage of the
state machine -- real infrastructure proof (a genuine Celery-dispatched
pipeline run, genuinely polled to a real terminal state) is in this
session's live verification, recorded in CLAUDE.md.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import execute_next_step
from models.all_models import (
    ApprovalRequest, ApprovalStatus, RunStatus, Task, TaskShape, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus, User,
)


async def _register(client, prefix="taskverify"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Verify Test",
        "tenant_name": f"Task Verify Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_task(tenant_id, user_id, steps: list[dict]):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.QUEUED, step_budget_max=20,
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


async def _all_steps(task_id):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.step_index))
        return r.scalars().all()


@pytest.mark.asyncio
async def test_async_dispatch_result_inserts_a_system_inserted_verify_step(client, monkeypatch):
    """run_pipeline is medium-risk (RISK_ACTIONS), so it goes through
    stage 5's approval gate before it can ever dispatch -- a real, correct
    interaction between the two stages, not a coincidence. Pre-seeding an
    already-APPROVED ApprovalRequest isolates this test to what it's
    actually checking: dispatch detection and verify-step insertion, not
    the approval gate itself (that's test_task_executor_approvals.py's
    job)."""
    tenant_id, user_id = await _register(client, "verifyinsert")
    task_id, (step_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "trigger the pipeline", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "run_pipeline", "tool_args": {"pipeline_id": "pl-1"}, "status": TaskStepStatus.PENDING,
    }])

    async with AsyncSessionLocal() as db:
        approval = ApprovalRequest(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, session_id=task_id,
            action_name="run_pipeline", action_args={"pipeline_id": "pl-1"}, risk_level="medium",
            status=ApprovalStatus.APPROVED, resolved_by="test-approver",
        )
        db.add(approval)
        await db.flush()
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        step = r.scalar_one()
        step.approval_request_id = approval.id
        await db.commit()

    async def _dispatch(tenant_id, tool_name, tool_args):
        return {"run_id": "run-abc", "pipeline_id": "pl-1", "status": RunStatus.PENDING, "dispatch": "queued"}

    monkeypatch.setattr(executor_module, "_call_tool", _dispatch)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_dispatched_pending_verification"

    steps = await _all_steps(task_id)
    assert len(steps) == 2
    dispatch_step, verify_step = steps[0], steps[1]
    assert dispatch_step.status == TaskStepStatus.SUCCEEDED  # it DID successfully dispatch
    assert verify_step.source == TaskStepSource.SYSTEM_INSERTED
    assert verify_step.status == TaskStepStatus.VERIFYING
    assert verify_step.depends_on_step_index == dispatch_step.step_index
    assert verify_step.step_index != dispatch_step.step_index
    assert verify_step.tool_name == "run_pipeline"
    assert verify_step.raw_result["run_id"] == "run-abc"


@pytest.mark.asyncio
async def test_verify_step_resolves_to_success_on_next_call(client, monkeypatch):
    tenant_id, user_id = await _register(client, "verifysuccess")
    task_id, (verify_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "verify the run", "source": TaskStepSource.SYSTEM_INSERTED,
        "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.VERIFYING,
        "raw_result": {"run_id": "run-abc"}, "started_at": datetime.utcnow(),
    }])

    async def _resolved_ok(tool_name, dispatch_result):
        return {"terminal": True, "success": True, "detail": "Run run-abc completed successfully."}

    monkeypatch.setattr(executor_module, "_poll_dispatch_status", _resolved_ok)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_verified_succeeded"

    task, verify_step = await _fresh(task_id, verify_id)
    assert verify_step.status == TaskStepStatus.SUCCEEDED
    assert "completed successfully" in verify_step.outcome_summary


@pytest.mark.asyncio
async def test_verify_step_resolves_to_failure_pauses_the_task(client, monkeypatch):
    tenant_id, user_id = await _register(client, "verifyfail")
    task_id, (verify_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "verify the run", "source": TaskStepSource.SYSTEM_INSERTED,
        "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.VERIFYING,
        "raw_result": {"run_id": "run-abc"}, "started_at": datetime.utcnow(),
    }])

    async def _resolved_fail(tool_name, dispatch_result):
        return {"terminal": True, "success": False, "detail": "Run run-abc failed: source not found"}

    monkeypatch.setattr(executor_module, "_poll_dispatch_status", _resolved_fail)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_verification_failed"

    task, verify_step = await _fresh(task_id, verify_id)
    assert verify_step.status == TaskStepStatus.FAILED
    assert "source not found" in verify_step.error_message
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


@pytest.mark.asyncio
async def test_unresolved_verify_step_moves_on_to_an_independent_pending_step(client, monkeypatch):
    """The concrete 'move on' proof: one call both polls the still-pending
    verify step (recording the attempt) AND makes real progress on an
    independent step, rather than blocking on it."""
    tenant_id, user_id = await _register(client, "verifymoveon")
    task_id, (verify_id, indep_id) = await _seed_task(tenant_id, user_id, [
        {"step_index": 0, "description": "verify the run", "source": TaskStepSource.SYSTEM_INSERTED,
         "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.VERIFYING,
         "raw_result": {"run_id": "run-abc"}, "started_at": datetime.utcnow()},
        {"step_index": 1, "description": "an independent step", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
         "depends_on_step_index": None},
    ])

    async def _still_pending(tool_name, dispatch_result):
        return {"terminal": False, "success": None, "detail": "still running"}

    async def _ok(tenant_id, tool_name, tool_args):
        return {"status": "healthy"}

    monkeypatch.setattr(executor_module, "_poll_dispatch_status", _still_pending)
    monkeypatch.setattr(executor_module, "_call_tool", _ok)
    monkeypatch.setattr(executor_module, "VERIFY_TIMEOUT_SECONDS", 300)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_succeeded"  # the independent step, not the verify step

    task, verify_step = await _fresh(task_id, verify_id)
    assert verify_step.status == TaskStepStatus.VERIFYING  # still unresolved
    assert verify_step.attempt_count == 1  # but it WAS polled this call
    _, indep_step = await _fresh(task_id, indep_id)
    assert indep_step.status == TaskStepStatus.SUCCEEDED
    assert task.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_unresolved_verify_with_nothing_else_to_do_stays_running_within_timeout(client, monkeypatch):
    tenant_id, user_id = await _register(client, "verifywaiting")
    task_id, (verify_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "verify the run", "source": TaskStepSource.SYSTEM_INSERTED,
        "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.VERIFYING,
        "raw_result": {"run_id": "run-abc"}, "started_at": datetime.utcnow(),
    }])

    async def _still_pending(tool_name, dispatch_result):
        return {"terminal": False, "success": None, "detail": "still running"}

    monkeypatch.setattr(executor_module, "_poll_dispatch_status", _still_pending)
    monkeypatch.setattr(executor_module, "VERIFY_TIMEOUT_SECONDS", 300)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "still_verifying"

    task = await _fresh(task_id)
    assert task.status == TaskStatus.RUNNING  # still honestly waiting, not done


@pytest.mark.asyncio
async def test_verify_timeout_with_nothing_else_to_do_completes_with_unconfirmed_steps_not_completed(client, monkeypatch):
    """The core invariant the whole design hinges on: this is the ONLY
    path that can end a task with a still-open verify step, and it must
    never be plain COMPLETED."""
    tenant_id, user_id = await _register(client, "verifytimeout")
    long_ago = datetime.utcnow() - timedelta(seconds=99999)
    task_id, (verify_id,) = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "verify the stuck run", "source": TaskStepSource.SYSTEM_INSERTED,
        "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.VERIFYING,
        "raw_result": {"run_id": "run-stuck"}, "started_at": long_ago,
    }])

    async def _still_pending(tool_name, dispatch_result):
        return {"terminal": False, "success": None, "detail": "still running"}

    monkeypatch.setattr(executor_module, "_poll_dispatch_status", _still_pending)
    monkeypatch.setattr(executor_module, "VERIFY_TIMEOUT_SECONDS", 300)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "task_completed_with_unconfirmed_steps"

    task = await _fresh(task_id)
    assert task.status == TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS
    assert task.status != TaskStatus.COMPLETED
    assert task.completed_at is not None
