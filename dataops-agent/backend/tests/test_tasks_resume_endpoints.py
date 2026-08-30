"""POST /api/v1/tasks/{id}/resume and .../reject-step -- item 6 stage 5's
REST surface. Deliberately gated by approvals.manage (Owner/Admin), NOT
creator-only like edit/approve-plan/advance -- a task's own creator
approving their own risky step would defeat the point of a second set of
eyes.
"""
import uuid

import pytest
from sqlalchemy import select

import api.v1.tasks as tasks_module
import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from models.all_models import User
from services.auth_service import hash_password, issue_token_for_user


async def _register(client, prefix="taskresumeapi"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Resume API Test",
        "tenant_name": f"Task Resume API Corp {uuid.uuid4().hex[:6]}",
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


async def _create_task_with_blocked_step(client, owner_token, monkeypatch, goal="approval api test"):
    """A real approved sync_profile_quality plan whose sole step
    (sync_source) is medium-risk and blocks on real approval."""
    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None):
        return [{
            "description": "sync a source", "tool_name": "sync_source",
            "tool_args": {"source_id": "src-1"}, "depends_on_step_index": None,
        }]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    r = await client.post(
        "/api/v1/tasks/", json={"goal": goal, "task_shape": "sync_profile_quality"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    created = r.json()
    approved = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert approved.status_code == 200

    advanced = await client.post(
        f"/api/v1/tasks/{created['id']}/advance", headers={"Authorization": f"Bearer {owner_token}"},
    )
    body = advanced.json()
    assert body["advance_outcome"]["outcome"] == "blocked_needs_approval"
    return body


@pytest.mark.asyncio
async def test_resume_requires_approvals_manage_not_creator_status(client, monkeypatch):
    owner_token, tenant_id, owner_id = await _register(client, "resumeapigate")
    task = await _create_task_with_blocked_step(client, owner_token, monkeypatch)

    # A Data Analyst (real role, no approvals.manage) -- even though this
    # IS a genuine tenant member -- must be blocked.
    analyst_token, _ = await _member(tenant_id, "data_analyst")
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/resume", json={"notes": "go ahead"},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_resume_by_a_real_admin_approves_and_continues(client, monkeypatch):
    owner_token, tenant_id, owner_id = await _register(client, "resumeapiok")
    task = await _create_task_with_blocked_step(client, owner_token, monkeypatch)

    admin_token, admin_id = await _member(tenant_id, "admin")

    async def _ok(tenant_id, tool_name, tool_args, **kwargs):
        return {"status": "synced"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    r = await client.post(
        f"/api/v1/tasks/{task['id']}/resume", json={"notes": "reviewed, fine"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resume_outcome"]["outcome"] == "step_succeeded"
    assert body["steps"][0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_reject_step_by_a_real_admin_fails_the_step(client, monkeypatch):
    owner_token, tenant_id, owner_id = await _register(client, "rejectapiok")
    task = await _create_task_with_blocked_step(client, owner_token, monkeypatch)
    admin_token, admin_id = await _member(tenant_id, "admin")

    r = await client.post(
        f"/api/v1/tasks/{task['id']}/reject-step", json={"notes": "not right now"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paused_failed_step"
    assert "not right now" in body["pause_reason"]


@pytest.mark.asyncio
async def test_resume_a_nonexistent_task_is_404(client):
    admin_token, _ = await _member((await _register(client, "resume404"))[1], "admin")
    r = await client.post(
        f"/api/v1/tasks/{uuid.uuid4()}/resume", json={}, headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resume_a_task_not_awaiting_approval_is_409(client, monkeypatch):
    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None):
        return [{"description": "x", "tool_name": "get_system_health", "tool_args": {}, "depends_on_step_index": None}]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    owner_token, tenant_id, _ = await _register(client, "resumenotwaiting")
    r = await client.post(
        "/api/v1/tasks/", json={"goal": "x", "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    created = r.json()
    admin_token, _ = await _member(tenant_id, "admin")

    r2 = await client.post(
        f"/api/v1/tasks/{created['id']}/resume", json={}, headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_approval_pending_reason_names_the_real_step_and_tool(client, monkeypatch):
    owner_token, tenant_id, owner_id = await _register(client, "pendingreason")
    task = await _create_task_with_blocked_step(client, owner_token, monkeypatch)
    assert task["status"] == "paused_needs_approval"
    assert "sync_source" in task["approval_pending_reason"]
    assert "sync a source" in task["approval_pending_reason"]
