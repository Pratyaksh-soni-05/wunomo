"""Wunomo Projects Phase 3, slice 10: services/task_lock.py's own
primitive, plus execute_next_step()'s use of it (item 73 -- the
pre-existing double-execution race for two concurrent calls on the
same task_id, now fixed).
"""
import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus
from modules.orchestration.task_executor import execute_next_step
from services.task_lock import TaskLockHeld, acquire_task_lock


async def _register(client, prefix="tasklock"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Lock Test",
        "tenant_name": f"Task Lock Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_task(tenant_id, user_id):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.RUNNING, step_budget_max=20, started_at=datetime.utcnow(),
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="check health", source=TaskStepSource.LLM_PLANNED,
            tool_name="get_system_health", tool_args={}, status=TaskStepStatus.PENDING,
        )
        db.add(step)
        await db.commit()
        return task.id


# ---------------------------------------------------------------------------
# services/task_lock.py's own primitive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_and_release_lets_a_later_caller_in():
    task_id = str(uuid.uuid4())
    async with acquire_task_lock(task_id):
        pass
    async with acquire_task_lock(task_id):
        pass


@pytest.mark.asyncio
async def test_second_acquire_while_held_raises_task_lock_held():
    task_id = str(uuid.uuid4())
    async with acquire_task_lock(task_id):
        with pytest.raises(TaskLockHeld):
            async with acquire_task_lock(task_id):
                pass


@pytest.mark.asyncio
async def test_lock_releases_on_exception_not_just_normal_exit():
    task_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        async with acquire_task_lock(task_id):
            raise RuntimeError("boom")
    async with acquire_task_lock(task_id):
        pass


# ---------------------------------------------------------------------------
# execute_next_step()'s use of the lock: a genuine concurrent conflict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_advance_calls_on_the_same_task_never_both_run_the_step(client, monkeypatch):
    """Item 73, proven live via asyncio.gather (not a sequential fake):
    two real, concurrently-running execute_next_step() calls on the same
    task_id -- exactly a beat tick racing a human /advance click, or two
    overlapping human clicks -- must never both call the step's tool.
    Before the task lock, both could read the step as PENDING and both
    proceed; now exactly one does."""
    tenant_id, user_id = await _register(client, "concurrentadvance")
    task_id = await _seed_task(tenant_id, user_id)

    calls = []

    async def _slow_ok(tenant_id, tool_name, tool_args, **kwargs):
        calls.append(1)
        await asyncio.sleep(0.3)
        return {"status": "ok"}

    import modules.orchestration.task_executor as executor_module
    monkeypatch.setattr(executor_module, "_call_tool", _slow_ok)

    results = await asyncio.gather(execute_next_step(task_id), execute_next_step(task_id))

    outcomes = {r.get("outcome") for r in results}
    assert "task_busy" in outcomes, results
    assert "step_succeeded" in outcomes, results
    # The real proof: the tool itself was only actually invoked once,
    # not twice -- outcomes alone could theoretically both say
    # step_succeeded if the lock silently didn't apply.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_lock_is_released_after_one_call_so_the_next_one_succeeds(client, monkeypatch):
    tenant_id, user_id = await _register(client, "sequentialadvance")
    task_id = await _seed_task(tenant_id, user_id)

    import modules.orchestration.task_executor as executor_module
    async def _ok(tenant_id, tool_name, tool_args, **kwargs):
        return {"status": "ok"}
    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    r1 = await execute_next_step(task_id)
    assert r1["outcome"] == "step_succeeded"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
    assert task.status != TaskStatus.CANCELLED  # sanity: task still real

    r2 = await execute_next_step(task_id)
    assert r2["outcome"] == "task_completed"
