"""Wunomo Projects Phase 2, item 5: per-source advisory locking.

services/source_lock.py's own primitive (acquire/deny/release/describe),
plus its two real chokepoints: ConnectorManager.sync (a genuine
concurrent conflict, proven via asyncio.gather + a deliberately slow
mock connector) and task_executor.py's pause/resume handling of a lock
conflict, reusing the same shape as quota_paused_attempt.
"""
import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, DataSource, SourceType, Task, TaskShape, TaskStatus,
    TaskStep, TaskStepSource, TaskStepStatus,
)
from modules.ingestion.connector_manager import ConnectorManager
from modules.orchestration.task_executor import execute_next_step
from services.source_lock import (
    SourceLockHeld, acquire_source_lock, describe_holder, format_lock_denial,
)


async def _register(client, prefix="lock"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Source Lock Test",
        "tenant_name": f"Source Lock Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _real_agent_id(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.tenant_id == tenant_id))
        return r.scalar_one().id


async def _create_source(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"test-source-{uuid.uuid4().hex[:6]}",
            source_type=SourceType.CSV, connection_config={"file_path": "/tmp/does-not-matter.csv"},
        )
        db.add(source)
        await db.commit()
        return source.id


# ---------------------------------------------------------------------------
# services/source_lock.py's own primitive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_and_release_lets_a_later_caller_in():
    source_id = str(uuid.uuid4())
    async with acquire_source_lock(source_id, agent_id=None):
        pass
    # Released on normal exit -- a fresh acquire must succeed immediately.
    async with acquire_source_lock(source_id, agent_id=None):
        pass


@pytest.mark.asyncio
async def test_second_acquire_while_held_raises_with_the_real_holder():
    source_id = str(uuid.uuid4())
    holder_agent_id = str(uuid.uuid4())
    async with acquire_source_lock(source_id, agent_id=holder_agent_id):
        with pytest.raises(SourceLockHeld) as exc_info:
            async with acquire_source_lock(source_id, agent_id="someone-else"):
                pass
        assert exc_info.value.source_id == source_id
        assert exc_info.value.holder_agent_id == holder_agent_id


@pytest.mark.asyncio
async def test_lock_releases_on_exception_not_just_normal_exit():
    source_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        async with acquire_source_lock(source_id, agent_id=None):
            raise RuntimeError("boom")
    # try/finally released it despite the exception -- must be free now.
    async with acquire_source_lock(source_id, agent_id=None):
        pass


@pytest.mark.asyncio
async def test_describe_holder_resolves_a_real_agent_name(client):
    token, tenant_id, _ = await _register(client, "describeA")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "Nova"})
    agent_id = r.json()["id"]
    async with AsyncSessionLocal() as db:
        label = await describe_holder(db, agent_id)
    assert label == "Nova"


@pytest.mark.asyncio
async def test_describe_holder_labels_a_none_agent_as_a_scheduled_run():
    async with AsyncSessionLocal() as db:
        label = await describe_holder(db, None)
    assert label == "a scheduled pipeline run"


def test_format_lock_denial_names_holder_and_time_not_the_bare_word_locked():
    msg = format_lock_denial("src-1", "Nova", "2026-09-03T09:14:00+00:00")
    assert "Nova" in msg
    assert "09:14" in msg
    assert msg.lower() != "locked"


# ---------------------------------------------------------------------------
# ConnectorManager.sync: a genuine concurrent conflict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_sync_denies_the_second_caller_with_a_legible_message(client, monkeypatch):
    """Two real, concurrently-running ConnectorManager.sync() calls on the
    same source -- proven via asyncio.gather, not a sequential fake --
    only one succeeds; the other is denied by name, not a bare "locked"."""
    token, tenant_id, _ = await _register(client, "concurrentA")
    r_nova = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "Nova"})
    r_atlas = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "Atlas"})
    nova_id, atlas_id = r_nova.json()["id"], r_atlas.json()["id"]
    source_id = await _create_source(tenant_id)

    class _SlowConnector:
        async def sync(self, mode):
            await asyncio.sleep(0.3)
            return {"status": "ok", "total_rows": 1}

    monkeypatch.setattr(ConnectorManager, "_get_connector", lambda self, source: _SlowConnector())

    results = await asyncio.gather(
        ConnectorManager(tenant_id).sync(source_id, agent_id=nova_id),
        ConnectorManager(tenant_id).sync(source_id, agent_id=atlas_id),
    )

    succeeded = [r for r in results if r.get("status") == "ok"]
    denied = [r for r in results if r.get("lock_conflict")]
    assert len(succeeded) == 1, results
    assert len(denied) == 1, results
    assert "Nova" in denied[0]["error"] or "Atlas" in denied[0]["error"]


@pytest.mark.asyncio
async def test_sync_succeeds_again_once_the_lock_frees(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "concurrentB")
    agent_id = await _real_agent_id(tenant_id)
    source_id = await _create_source(tenant_id)

    class _FastConnector:
        async def sync(self, mode):
            return {"status": "ok", "total_rows": 1}

    monkeypatch.setattr(ConnectorManager, "_get_connector", lambda self, source: _FastConnector())

    r1 = await ConnectorManager(tenant_id).sync(source_id, agent_id=agent_id)
    assert r1["status"] == "ok"
    r2 = await ConnectorManager(tenant_id).sync(source_id, agent_id=agent_id)
    assert r2["status"] == "ok"


# ---------------------------------------------------------------------------
# task_executor.py: pause on lock conflict, resume once it frees
# ---------------------------------------------------------------------------

async def _seed_task(tenant_id, user_id, agent_id, tool_name, tool_args):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.RUNNING, step_budget_max=20, started_at=datetime.utcnow(),
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="sync the warehouse", source=TaskStepSource.LLM_PLANNED,
            tool_name=tool_name, tool_args=tool_args, status=TaskStepStatus.PENDING,
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
async def test_task_step_pauses_on_lock_conflict_and_resumes_once_it_frees(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "taskLockA")
    agent_id = await _real_agent_id(tenant_id)
    # get_pipeline_run_history is view-tier (no approval gate, unlike
    # sync_source's real risk level) -- _call_tool is fully monkeypatched
    # below anyway, so only the executor's own pause/resume state machine
    # is under test here, not sync_source's actual risk tier.
    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, "get_pipeline_run_history", {"pipeline_id": "bad-id"})

    calls = {"n": 0}

    async def _lock_then_succeed(tenant_id, tool_name, tool_args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"error": "This source is currently in use by Nova (since 09:14 UTC).",
                    "source_id": "src-1", "status": "failed", "lock_conflict": True}
        return {"status": "ok", "total_rows": 1}

    monkeypatch.setattr(executor_module, "_call_tool", _lock_then_succeed)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "paused_source_locked"
    assert "in use by Nova" in outcome["reason"]

    task, step = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.PAUSED_SOURCE_LOCKED
    assert step.status == TaskStepStatus.PENDING
    assert step.attempt_count == 1

    # Resume: execute_next_step() itself flips PAUSED_SOURCE_LOCKED back to
    # RUNNING the same way it already does for PAUSED_QUOTA_EXCEEDED.
    outcome2 = await execute_next_step(task_id)
    assert outcome2["outcome"] == "step_succeeded"
    task, step = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.RUNNING
    assert step.status == TaskStepStatus.SUCCEEDED
    assert step.attempt_count == 2  # continued the same attempt budget, not a fresh one


@pytest.mark.asyncio
async def test_advance_endpoint_allows_resuming_a_source_locked_task(client, monkeypatch):
    """The manual /advance endpoint's own runnable-status check must
    accept PAUSED_SOURCE_LOCKED, the same way it already accepts
    PAUSED_QUOTA_EXCEEDED -- otherwise a paused task can never actually
    be resumed through the real API."""
    token, tenant_id, user_id = await _register(client, "taskLockB")
    agent_id = await _real_agent_id(tenant_id)
    # get_pipeline_run_history is view-tier (no approval gate, unlike
    # sync_source's real risk level) -- _call_tool is fully monkeypatched
    # below anyway, so only the executor's own pause/resume state machine
    # is under test here, not sync_source's actual risk tier.
    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, "get_pipeline_run_history", {"pipeline_id": "bad-id"})

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.status = TaskStatus.PAUSED_SOURCE_LOCKED
        await db.commit()

    async def _succeed(tenant_id, tool_name, tool_args, **kwargs):
        return {"status": "ok"}
    monkeypatch.setattr(executor_module, "_call_tool", _succeed)

    r = await client.post(f"/api/v1/tasks/{task_id}/advance", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["advance_outcome"]["outcome"] == "step_succeeded"
