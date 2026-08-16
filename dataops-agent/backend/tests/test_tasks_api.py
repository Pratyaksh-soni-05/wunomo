"""Integration tests for POST /api/v1/tasks/ (item 6, stage 2 - planning
phase). Covers the failure-handling contract explicitly required before
this shipped: quota is checked before the LLM call, and a
generation/validation failure persists nothing -- no Task row stuck in
draft_plan with no steps and no explanation. One real, live LLM call at
the end proves the whole path end-to-end (kept to a single call, given
this project's documented Gemini/Groq daily quota constraints).
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import modules.orchestration.task_planner as task_planner_module
from database import AsyncSessionLocal
from models.all_models import LlmUsageEvent, Task
from services.quota_service import PLANS


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _register(client, prefix="taskapi"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task API Test",
        "tenant_name": f"Task API Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _seed_llm_usage(tenant_id: str, credits: int):
    async with AsyncSessionLocal() as db:
        db.add(LlmUsageEvent(
            id=str(uuid.uuid4()), tenant_id=tenant_id, request_type="test",
            provider="test", model="test", used_fallback=False,
            input_tokens=credits, output_tokens=0, total_tokens=credits,
            success=True, created_at=utcnow(),
        ))
        await db.commit()


async def _tasks_for_tenant(tenant_id: str) -> list[Task]:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.tenant_id == tenant_id))
        return r.scalars().all()


@pytest.mark.asyncio
async def test_unknown_task_shape_is_rejected_and_nothing_is_persisted(client):
    token, tenant_id, _ = await _register(client, "taskbadshape")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "do something", "task_shape": "not_a_real_shape"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert await _tasks_for_tenant(tenant_id) == []


@pytest.mark.asyncio
async def test_empty_goal_is_rejected(client):
    token, tenant_id, _ = await _register(client, "taskemptygoal")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "   ", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert await _tasks_for_tenant(tenant_id) == []


@pytest.mark.asyncio
async def test_quota_exceeded_blocks_before_any_plan_generation_attempt(client, monkeypatch):
    """Confirms the actual ordering, not just the outcome: enforce_quota
    runs as a FastAPI dependency before the route handler body, so
    generate_plan() must never even be called once quota is exhausted."""
    token, tenant_id, _ = await _register(client, "taskquota")
    await _seed_llm_usage(tenant_id, PLANS["starter"]["ai_credits_per_month"] + 1)

    called = False

    async def _fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("generate_plan must not be called when quota is already exceeded")

    monkeypatch.setattr(task_planner_module, "generate_plan", _fail_if_called)
    # api/v1/tasks.py imports generate_plan by name, so patch it there too.
    import api.v1.tasks as tasks_module
    monkeypatch.setattr(tasks_module, "generate_plan", _fail_if_called)

    r = await client.post(
        "/api/v1/tasks/", json={"goal": "diagnose it", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 402
    assert not called
    assert await _tasks_for_tenant(tenant_id) == []


@pytest.mark.asyncio
async def test_plan_generation_failure_persists_nothing(client, monkeypatch):
    from modules.orchestration.task_planner import PlanGenerationError
    import api.v1.tasks as tasks_module

    async def _always_fails(*args, **kwargs):
        raise PlanGenerationError("simulated: LLM never produced a valid plan")

    monkeypatch.setattr(tasks_module, "generate_plan", _always_fails)

    token, tenant_id, _ = await _register(client, "taskgenfail")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "diagnose it", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422
    assert "simulated" in r.json()["detail"]
    assert await _tasks_for_tenant(tenant_id) == []


@pytest.mark.asyncio
async def test_plan_validation_failure_persists_nothing(client, monkeypatch):
    from modules.orchestration.task_planner import PlanValidationError
    import api.v1.tasks as tasks_module

    async def _always_invalid(*args, **kwargs):
        raise PlanValidationError("simulated: step referenced a disallowed tool")

    monkeypatch.setattr(tasks_module, "generate_plan", _always_invalid)

    token, tenant_id, _ = await _register(client, "taskvalfail")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "diagnose it", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422
    assert "simulated" in r.json()["detail"]
    assert await _tasks_for_tenant(tenant_id) == []


@pytest.mark.asyncio
async def test_successful_generation_persists_a_real_reviewable_plan(client, monkeypatch):
    """Mocked-LLM proof (fast, zero cost) that a successful generation
    persists exactly what the caller returned, with the fields a plan
    review needs to actually judge it -- real tool_name/tool_args per
    step, not just a description. The real-LLM proof is the test below."""
    import api.v1.tasks as tasks_module

    async def _fake_plan(tenant_id, user_id, goal, task_shape):
        return [
            {"description": "Check recent runs", "tool_name": "get_pipeline_run_history",
             "tool_args": {"pipeline_id": "pl-123", "limit": 5}, "depends_on_step_index": None},
        ]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)

    token, tenant_id, user_id = await _register(client, "taskgoodplan")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "why did the pipeline fail", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft_plan"
    assert body["plan_approved_by"] is None
    assert body["plan_edited"] is False
    assert len(body["steps"]) == 1
    step = body["steps"][0]
    assert step["tool_name"] == "get_pipeline_run_history"
    assert step["tool_args"] == {"pipeline_id": "pl-123", "limit": 5}
    assert step["source"] == "llm_planned"
    assert step["status"] == "pending"

    tasks = await _tasks_for_tenant(tenant_id)
    assert len(tasks) == 1
    assert tasks[0].user_id == user_id


@pytest.mark.asyncio
@pytest.mark.live_llm
async def test_real_live_llm_generates_a_valid_reviewable_plan(client):
    """Definitive live proof, not a mock: a real LLM call producing a real
    plan whose steps genuinely reference the diagnose_pipeline_failure
    allowlist with real, schema-valid arguments."""
    token, tenant_id, _ = await _register(client, "tasklivellm")
    r = await client.post(
        "/api/v1/tasks/",
        json={
            "goal": "Figure out why the nightly sales pipeline has been failing.",
            "task_shape": "diagnose_pipeline_failure",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "draft_plan"
    assert 1 <= len(body["steps"]) <= 8

    allowed_tools = {
        "list_pipelines", "get_pipeline_run_history", "check_freshness",
        "get_cicd_status", "get_system_health",
    }
    for step in body["steps"]:
        assert step["tool_name"] in allowed_tools
        assert step["source"] == "llm_planned"
        assert isinstance(step["tool_args"], dict)
        assert "tenant_id" not in step["tool_args"]

    tasks = await _tasks_for_tenant(tenant_id)
    assert len(tasks) == 1
