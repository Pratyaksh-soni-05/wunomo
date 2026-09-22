"""Wunomo Projects Phase 1, part two: the per-agent monthly_token_budget
two-gate path -- tenant plan limit (services/quota_service.py's existing
get_quota_status) AND agent budget (get_agent_quota_status, new), both
must pass. Covers the gate itself (api/v1/auth.py's enforce_agent_budget,
called from chat.py and tasks.py's create_task) and the mid-task check
in task_executor.py, immediately before an LLM-adapt call.
"""
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from api.v1.auth import enforce_agent_budget
from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, LlmUsageEvent, Task, TaskShape, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus,
)
from modules.orchestration.task_executor import execute_next_step
from services.quota_service import get_agent_quota_status


async def _register(client, prefix="budget"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Token Budget Test",
        "tenant_name": f"Token Budget Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _seed_agent_token_usage(agent_id: str, tenant_id: str, tokens: int) -> None:
    """Raw input+output tokens summing to exactly `tokens` -- the
    agent-level budget is unweighted (unlike the tenant "credits"
    formula), so a single input_tokens=tokens row is exact."""
    async with AsyncSessionLocal() as db:
        db.add(LlmUsageEvent(
            id=str(uuid.uuid4()), tenant_id=tenant_id, agent_id=agent_id, request_type="test",
            provider="test", model="test", used_fallback=False,
            input_tokens=tokens, output_tokens=0, total_tokens=tokens,
            success=True, created_at=datetime.utcnow(),
        ))
        await db.commit()


async def _real_agent_id(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.tenant_id == tenant_id))
        return r.scalar_one().id


# ---------------------------------------------------------------------------
# get_agent_quota_status() / enforce_agent_budget()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_with_no_budget_is_always_ok(client):
    token, tenant_id, _ = await _register(client, "budgetA")
    agent_id = await _real_agent_id(tenant_id)
    result = await get_agent_quota_status(agent_id)
    assert result == {"resource": "agent_tokens", "used": 0, "limit": None, "percent": 0.0, "status": "ok"}
    await enforce_agent_budget(agent_id)  # must not raise


@pytest.mark.asyncio
async def test_agent_budget_exceeded_is_reported_and_blocks(client):
    token, tenant_id, _ = await _register(client, "budgetB")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={
        "name": "Nova", "monthly_token_budget": 1000,
    })
    agent_id = r.json()["id"]

    await _seed_agent_token_usage(agent_id, tenant_id, 1500)
    result = await get_agent_quota_status(agent_id)
    assert result["status"] == "exceeded"
    assert result["used"] == 1500
    assert result["limit"] == 1000

    with pytest.raises(HTTPException) as exc_info:
        await enforce_agent_budget(agent_id)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["error"] == "agent_budget_exceeded"


@pytest.mark.asyncio
async def test_agent_budget_under_limit_does_not_block(client):
    token, tenant_id, _ = await _register(client, "budgetC")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={
        "name": "Nova", "monthly_token_budget": 1000,
    })
    agent_id = r.json()["id"]

    await _seed_agent_token_usage(agent_id, tenant_id, 100)
    await enforce_agent_budget(agent_id)  # must not raise


@pytest.mark.asyncio
async def test_agent_id_none_is_a_noop_for_the_budget_gate(client):
    await enforce_agent_budget(None)  # must not raise


@pytest.mark.asyncio
async def test_real_chat_request_denied_when_the_agents_budget_is_exceeded(client, monkeypatch):
    """Gate 2 fires through the real /api/v1/chat/ endpoint, before any
    LLM call happens for the turn."""
    token, tenant_id, _ = await _register(client, "budgetD")
    agent_id = await _real_agent_id(tenant_id)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.id == agent_id))
        agent = r.scalar_one()
        agent.monthly_token_budget = 1000
        await db.commit()
    await _seed_agent_token_usage(agent_id, tenant_id, 2000)

    r = await client.post("/api/v1/chat/", json={"message": "hello"}, headers=_auth(token))
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "agent_budget_exceeded"


# ---------------------------------------------------------------------------
# Two-gate enforcement inside task execution (mid-task, before an adapt call).
# ---------------------------------------------------------------------------

async def _seed_task(tenant_id, user_id, agent_id, tool_args):
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
            description="check history", source=TaskStepSource.LLM_PLANNED,
            tool_name="get_pipeline_run_history", tool_args=tool_args,
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
async def test_task_pauses_when_the_agent_budget_is_exceeded_not_the_tenant_quota(client, monkeypatch):
    """Tenant quota is fine; the agent's own budget is what's exhausted --
    the task must still pause (two gates, either exceeded blocks), and
    the reason must name the agent budget specifically, not a stale
    domain error or the tenant-quota message."""
    token, tenant_id, user_id = await _register(client, "taskbudgetA")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={
        "name": "Nova", "monthly_token_budget": 1000,
    })
    agent_id = r.json()["id"]
    await _seed_agent_token_usage(agent_id, tenant_id, 5000)

    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, {"pipeline_id": "bad-id"})

    async def _domain_error(tenant_id, tool_name, tool_args, **kwargs):
        return {"error": "Pipeline not found"}

    async def _fail_if_adapted(*a, **k):
        raise AssertionError("must not attempt to adapt once the agent budget is exceeded")

    monkeypatch.setattr(executor_module, "_call_tool", _domain_error)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _fail_if_adapted)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "paused_quota_exceeded"
    assert "monthly token budget" in outcome["reason"]
    assert "1000" in outcome["reason"]

    task, step = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.PAUSED_QUOTA_EXCEEDED
    assert step.status == TaskStepStatus.PENDING


@pytest.mark.asyncio
async def test_task_proceeds_when_both_gates_are_under_limit(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "taskbudgetB")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={
        "name": "Nova", "monthly_token_budget": 1000,
    })
    agent_id = r.json()["id"]
    await _seed_agent_token_usage(agent_id, tenant_id, 10)

    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, {"pipeline_id": "pl-1"})

    async def _ok(tenant_id, tool_name, tool_args, **kwargs):
        return {"pipeline_id": "pl-1", "runs": []}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_succeeded"
