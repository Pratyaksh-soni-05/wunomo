"""POST /api/v1/tasks/{id}/cancel -- item 6 stage 6's REST surface.
Creator OR approvals.manage may cancel (unlike resume/reject-step, which
are approvals.manage-only, and edit/approve-plan, which are creator-only)
-- stopping your own task or stopping a runaway one you have governance
authority over are both legitimate.
"""
import uuid

import pytest
from sqlalchemy import select

import api.v1.tasks as tasks_module
from database import AsyncSessionLocal
from models.all_models import Task, User
from services.auth_service import hash_password, issue_token_for_user


async def _register(client, prefix="taskcancelapi"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Cancel API Test",
        "tenant_name": f"Task Cancel API Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _member(tenant_id, role):
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name=role, role=role,
            is_active=True, email_verified=True,
        )
        db.add(user)
        await db.commit()
        return issue_token_for_user(user, "password"), user.id


async def _create_task(client, token, monkeypatch, goal="cancel api test"):
    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None, agent_id=None):
        return [{
            "description": "check health", "tool_name": "get_system_health",
            "tool_args": {}, "depends_on_step_index": None,
        }]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    r = await client.post(
        "/api/v1/tasks/", json={"goal": goal, "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return r.json()


@pytest.mark.asyncio
async def test_creator_can_cancel_their_own_task(client, monkeypatch):
    token, _, _ = await _register(client, "cancelcreator")
    task = await _create_task(client, token, monkeypatch)

    r = await client.post(f"/api/v1/tasks/{task['id']}/cancel", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["termination_reason"] is not None


@pytest.mark.asyncio
async def test_admin_can_cancel_someone_elses_task(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "cancelbyowner")
    task = await _create_task(client, token, monkeypatch)
    admin_token, admin_id = await _member(tenant_id, "admin")

    r = await client.post(f"/api/v1/tasks/{task['id']}/cancel", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_an_unrelated_member_cannot_cancel_someone_elses_task(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "cancelnotmine")
    task = await _create_task(client, token, monkeypatch)
    analyst_token, _ = await _member(tenant_id, "data_analyst")  # no approvals.manage, not the creator

    r = await client.post(f"/api/v1/tasks/{task['id']}/cancel", headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cancelling_a_nonexistent_task_is_404(client):
    token, _, _ = await _register(client, "cancel404")
    r = await client.post(f"/api/v1/tasks/{uuid.uuid4()}/cancel", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancelling_an_already_cancelled_task_is_409(client, monkeypatch):
    token, _, _ = await _register(client, "cancel409")
    task = await _create_task(client, token, monkeypatch)

    r1 = await client.post(f"/api/v1/tasks/{task['id']}/cancel", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200
    r2 = await client.post(f"/api/v1/tasks/{task['id']}/cancel", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409
