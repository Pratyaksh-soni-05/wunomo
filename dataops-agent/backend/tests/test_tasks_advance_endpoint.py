"""POST /api/v1/tasks/{id}/advance -- item 6 stage 3's REST surface.
Mocked at the tool-call boundary (execute_next_step's own tier logic is
already covered directly in test_task_executor.py, and live end-to-end
in this session's live verification -- see CLAUDE.md).
"""
import uuid

import pytest
from sqlalchemy import select

import api.v1.tasks as tasks_module
import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from models.all_models import Task, User
from services.auth_service import hash_password, issue_token_for_user


async def _register(client, prefix="taskadvance"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Advance Test",
        "tenant_name": f"Task Advance Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _create_and_approve_task(client, token, monkeypatch, goal="advance test goal"):
    async def _fake_plan(tenant_id, user_id, goal, task_shape):
        return [{
            "description": "check health", "tool_name": "get_system_health",
            "tool_args": {}, "depends_on_step_index": None,
        }]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    r = await client.post(
        "/api/v1/tasks/", json={"goal": goal, "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    created = r.json()
    approved = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200
    return approved.json()


@pytest.mark.asyncio
async def test_advance_resolves_one_step_and_returns_the_outcome(client, monkeypatch):
    token, _, _ = await _register(client, "advbasic")
    task = await _create_and_approve_task(client, token, monkeypatch)

    async def _ok(tenant_id, tool_name, tool_args):
        return {"status": "healthy"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    r = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["advance_outcome"]["outcome"] == "step_succeeded"
    assert body["steps"][0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_advance_on_a_task_still_in_draft_plan_is_409(client, monkeypatch):
    async def _fake_plan(tenant_id, user_id, goal, task_shape):
        return [{"description": "x", "tool_name": "get_system_health", "tool_args": {}, "depends_on_step_index": None}]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    token, _, _ = await _register(client, "advdraft")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "x", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    created = r.json()

    r2 = await client.post(f"/api/v1/tasks/{created['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_advance_on_a_completed_task_is_409(client, monkeypatch):
    token, _, _ = await _register(client, "advdone")
    task = await _create_and_approve_task(client, token, monkeypatch)

    async def _ok(tenant_id, tool_name, tool_args):
        return {"status": "healthy"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    first = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    assert first.json()["status"] == "running"
    second = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    assert second.json()["status"] == "completed"

    third = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    assert third.status_code == 409


@pytest.mark.asyncio
async def test_only_creator_may_advance(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "advnotmine")
    task = await _create_and_approve_task(client, token, monkeypatch)

    async with AsyncSessionLocal() as db:
        other = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Other", role="owner",
            is_active=True, email_verified=True,
        )
        db.add(other)
        await db.commit()
        other_token = issue_token_for_user(other, "password")

    r = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {other_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_advance_a_nonexistent_task_is_404(client):
    token, _, _ = await _register(client, "advnotfound")
    r = await client.post(f"/api/v1/tasks/{uuid.uuid4()}/advance", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pause_reason_is_null_while_the_task_is_healthy(client, monkeypatch):
    token, _, _ = await _register(client, "advnopause")
    task = await _create_and_approve_task(client, token, monkeypatch)
    assert task["pause_reason"] is None

    async def _ok(tenant_id, tool_name, tool_args):
        return {"status": "healthy"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)
    r = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["pause_reason"] is None


@pytest.mark.asyncio
async def test_pause_reason_names_the_real_step_and_real_error(client, monkeypatch):
    token, _, _ = await _register(client, "advpausereason")
    task = await _create_and_approve_task(client, token, monkeypatch, goal="a specific real failure")

    async def _always_fails(tenant_id, tool_name, tool_args):
        raise RuntimeError("simulated: the underlying service is down")

    monkeypatch.setattr(executor_module, "_call_tool", _always_fails)
    monkeypatch.setattr(executor_module, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0)

    r = await client.post(f"/api/v1/tasks/{task['id']}/advance", headers={"Authorization": f"Bearer {token}"})
    body = r.json()
    assert body["status"] == "paused_failed_step"
    assert "check health" in body["pause_reason"]  # the real step description, not a generic label
    assert "simulated: the underlying service is down" in body["pause_reason"]  # the real error, not "step failed"
