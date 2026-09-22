"""Wunomo Projects Phase 4, item 2: task cost on the task detail screen.
An agent that works unattended (item 71's auto-advance loop) should
show what it spent while nobody was watching -- GET /api/v1/tasks/{id}
now includes a "cost" object aggregated from LlmUsageEvent, reusing the
existing credits_for_event formula (the same unit Billing already
shows).
"""
import uuid
from datetime import datetime

import pytest

from database import AsyncSessionLocal
from models.all_models import LlmUsageEvent
from services.quota_service import credits_for_event, get_task_cost


async def _register(client, prefix="taskcost"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Cost Test",
        "tenant_name": f"Task Cost Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _create_mocked_task(client, token, monkeypatch, goal="test goal"):
    import api.v1.tasks as tasks_module

    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None, agent_id=None):
        return [{
            "description": "check history", "tool_name": "get_pipeline_run_history",
            "tool_args": {"pipeline_id": "pl-1"}, "depends_on_step_index": None,
        }]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    r = await client.post(
        "/api/v1/tasks/", json={"goal": goal, "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _log_usage(tenant_id, task_id, input_tokens, output_tokens, reasoning_tokens=0):
    async with AsyncSessionLocal() as db:
        db.add(LlmUsageEvent(
            id=str(uuid.uuid4()), tenant_id=tenant_id, task_id=task_id, request_type="test",
            provider="test", model="test", used_fallback=False,
            input_tokens=input_tokens, output_tokens=output_tokens, reasoning_tokens=reasoning_tokens,
            total_tokens=input_tokens + output_tokens, success=True, created_at=datetime.utcnow(),
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_get_task_cost_aggregates_real_usage_events(client):
    token, tenant_id, _ = await _register(client, "costaggregate")
    task_id = str(uuid.uuid4())
    await _log_usage(tenant_id, task_id, input_tokens=100, output_tokens=50, reasoning_tokens=10)
    await _log_usage(tenant_id, task_id, input_tokens=200, output_tokens=30, reasoning_tokens=0)

    async with AsyncSessionLocal() as db:
        cost = await get_task_cost(db, tenant_id, task_id)

    assert cost["llm_calls"] == 2
    assert cost["input_tokens"] == 300
    assert cost["output_tokens"] == 80
    assert cost["reasoning_tokens"] == 10
    assert cost["total_tokens"] == 380
    assert cost["credits"] == credits_for_event(300, 80)


@pytest.mark.asyncio
async def test_get_task_cost_is_zero_for_a_task_with_no_llm_usage(client):
    token, tenant_id, _ = await _register(client, "costzero")
    async with AsyncSessionLocal() as db:
        cost = await get_task_cost(db, tenant_id, str(uuid.uuid4()))
    assert cost == {
        "llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "reasoning_tokens": 0, "total_tokens": 0, "credits": 0,
    }


@pytest.mark.asyncio
async def test_get_task_cost_is_tenant_scoped(client):
    """A usage event logged under a different tenant must never be
    counted, even if it somehow shared the same task_id."""
    token_a, tenant_a, _ = await _register(client, "costtenanta")
    token_b, tenant_b, _ = await _register(client, "costtenantb")
    shared_task_id = str(uuid.uuid4())
    await _log_usage(tenant_a, shared_task_id, input_tokens=1000, output_tokens=1000)

    async with AsyncSessionLocal() as db:
        cost_b = await get_task_cost(db, tenant_b, shared_task_id)
    assert cost_b["llm_calls"] == 0
    assert cost_b["credits"] == 0


@pytest.mark.asyncio
async def test_get_task_endpoint_includes_real_cost(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "costendpoint")
    created = await _create_mocked_task(client, token, monkeypatch)
    task_id = created["id"]
    await _log_usage(tenant_id, task_id, input_tokens=500, output_tokens=200)

    r = await client.get(f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    cost = r.json()["cost"]
    assert cost["llm_calls"] == 1
    assert cost["input_tokens"] == 500
    assert cost["output_tokens"] == 200
    assert cost["credits"] == credits_for_event(500, 200)


@pytest.mark.asyncio
async def test_get_task_endpoint_reports_zero_cost_for_a_fresh_task(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "costfresh")
    created = await _create_mocked_task(client, token, monkeypatch)

    r = await client.get(f"/api/v1/tasks/{created['id']}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["cost"]["credits"] == 0
