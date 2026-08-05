"""POST /api/v1/tasks/{id}/approve-plan and .../reject-plan -- item 6
stage 2 (part 4, closing out the planning phase). approve-plan is the
ONLY code path that ever sets plan_approved_by/plan_approved_at; this
file proves that end-to-end, including the full edit-then-approve
lifecycle the design was built around (editing must never implicitly
approve, per the explicit requirement).
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Task, TaskStep, User
from services.auth_service import hash_password, issue_token_for_user

import api.v1.tasks as tasks_module


async def _register(client, prefix="taskapprove"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Approve Test",
        "tenant_name": f"Task Approve Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _create_task(client, token, monkeypatch, goal="approve test goal"):
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
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_approve_sets_provenance_and_transitions_to_queued(client, monkeypatch):
    token, _, user_id = await _register(client, "approvebasic")
    created = await _create_task(client, token, monkeypatch)

    r = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["plan_approved_by"] == user_id
    assert body["plan_approved_at"] is not None


@pytest.mark.asyncio
async def test_approving_twice_is_409(client, monkeypatch):
    token, _, _ = await _register(client, "approvetwice")
    created = await _create_task(client, token, monkeypatch)

    r1 = await client.post(f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200
    r2 = await client.post(f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_only_creator_may_approve(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "approvenotmine")
    created = await _create_task(client, token, monkeypatch)

    async with AsyncSessionLocal() as db:
        other = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Other", role="owner",
            is_active=True, email_verified=True,
        )
        db.add(other)
        await db.commit()
        other_token = issue_token_for_user(other, "password")

    r = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_approve_a_plan_with_zero_steps(client, monkeypatch):
    """Defense in depth -- the normal API paths can't produce a zero-step
    draft_plan task (generation/edit both require >=1 step), but this
    guards the invariant directly in case something upstream ever
    changes."""
    token, _, _ = await _register(client, "approvenosteps")
    created = await _create_task(client, token, monkeypatch)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == created["id"]))
        for s in r.scalars().all():
            await db.delete(s)
        await db.commit()

    r = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_reject_is_terminal_and_returns_a_clear_next_step_message(client, monkeypatch):
    token, _, _ = await _register(client, "rejectbasic")
    created = await _create_task(client, token, monkeypatch)

    r = await client.post(
        f"/api/v1/tasks/{created['id']}/reject-plan", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "plan_rejected"
    assert "start a new task" in body["message"].lower()

    # Terminal: neither edit nor approve nor a second reject can act on it again.
    r2 = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_only_creator_may_reject(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "rejectnotmine")
    created = await _create_task(client, token, monkeypatch)

    async with AsyncSessionLocal() as db:
        other = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"other2-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Other2", role="owner",
            is_active=True, email_verified=True,
        )
        db.add(other)
        await db.commit()
        other_token = issue_token_for_user(other, "password")

    r = await client.post(
        f"/api/v1/tasks/{created['id']}/reject-plan", headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_full_lifecycle_create_edit_approve_edit_again_is_409(client, monkeypatch):
    """The end-to-end proof the whole design was built around: editing a
    plan never implicitly approves it, and once genuinely approved, the
    plan is locked -- a fresh, explicit approval is the only way in."""
    token, _, user_id = await _register(client, "lifecycle")
    created = await _create_task(client, token, monkeypatch)

    edit = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps",
        json={"steps": [
            {"description": "an edited step", "tool_name": "check_freshness",
             "tool_args": {}, "depends_on_step_index": None},
        ]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert edit.status_code == 200
    assert edit.json()["plan_edited"] is True
    assert edit.json()["plan_approved_by"] is None  # edit alone never approves

    approve = await client.post(
        f"/api/v1/tasks/{created['id']}/approve-plan", headers={"Authorization": f"Bearer {token}"},
    )
    assert approve.status_code == 200
    assert approve.json()["plan_approved_by"] == user_id
    assert approve.json()["status"] == "queued"
    # The approved plan reflects the edited content, not the original.
    assert approve.json()["steps"][0]["tool_name"] == "check_freshness"
    assert approve.json()["steps"][0]["source"] == "human_edited"

    # And now that it's genuinely approved, it's locked -- no more edits.
    edit_again = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps",
        json={"steps": [
            {"description": "too late now", "tool_name": "get_system_health",
             "tool_args": {}, "depends_on_step_index": None},
        ]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert edit_again.status_code == 409

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == created["id"]))
        task = r.scalar_one()
        assert task.status.value == "queued"
        assert task.plan_approved_by == user_id
