"""PATCH /api/v1/tasks/{id}/steps -- item 6 stage 2 (part 3). Covers the
two explicit requirements this endpoint was built against: editing shares
validate_step_plan() with generation (fail-closed both directions), and
editing can never implicitly approve a plan.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Task, TaskStatus, User
from services.auth_service import hash_password, issue_token_for_user

import api.v1.tasks as tasks_module


async def _register(client, prefix="taskedit"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Edit Test",
        "tenant_name": f"Task Edit Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _real_plan():
    return [
        {"description": "Check recent runs", "tool_name": "get_pipeline_run_history",
         "tool_args": {"pipeline_id": "pl-1", "limit": 10}, "depends_on_step_index": None},
        {"description": "Check freshness", "tool_name": "check_freshness",
         "tool_args": {}, "depends_on_step_index": None},
    ]


async def _create_task(client, token, monkeypatch, goal="edit test goal"):
    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None, agent_id=None):
        return _real_plan()

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    r = await client.post(
        "/api/v1/tasks/", json={"goal": goal, "task_shape": "diagnose_pipeline_failure"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_edit_persists_new_content_and_marks_plan_edited(client, monkeypatch):
    token, _, _ = await _register(client, "editbasic")
    created = await _create_task(client, token, monkeypatch)

    new_steps = {
        "steps": [
            {"description": "Check recent runs, more of them", "tool_name": "get_pipeline_run_history",
             "tool_args": {"pipeline_id": "pl-1", "limit": 50}, "depends_on_step_index": None},
        ]
    }
    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps", json=new_steps,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_edited"] is True
    assert len(body["steps"]) == 1
    assert body["steps"][0]["tool_args"]["limit"] == 50
    assert body["steps"][0]["source"] == "human_edited"


@pytest.mark.asyncio
async def test_edit_never_sets_approval_fields(client, monkeypatch):
    """The core invariant: an edited plan cannot execute without a fresh,
    explicit approval -- editing must never implicitly approve."""
    token, _, _ = await _register(client, "editnoapprove")
    created = await _create_task(client, token, monkeypatch)

    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps",
        json={"steps": [
            {"description": "Different step entirely", "tool_name": "get_system_health",
             "tool_args": {}, "depends_on_step_index": None},
        ]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan_approved_by"] is None
    assert body["plan_approved_at"] is None
    assert body["status"] == "draft_plan"


@pytest.mark.asyncio
async def test_reedit_with_identical_content_does_not_flip_plan_edited(client, monkeypatch):
    token, _, _ = await _register(client, "editnoop")
    created = await _create_task(client, token, monkeypatch)

    identical_steps = {"steps": [
        {"description": s["description"], "tool_name": s["tool_name"],
         "tool_args": s["tool_args"], "depends_on_step_index": s["depends_on_step_index"]}
        for s in created["steps"]
    ]}
    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps", json=identical_steps,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan_edited"] is False
    assert all(s["source"] == "llm_planned" for s in body["steps"])


@pytest.mark.asyncio
async def test_mixed_edit_preserves_source_on_unchanged_steps_only(client, monkeypatch):
    """The provenance-preserving guarantee: an edit that only changes ONE
    of several steps must leave the untouched ones as llm_planned and
    only mark the genuinely changed one human_edited."""
    token, _, _ = await _register(client, "editmixed")
    created = await _create_task(client, token, monkeypatch)
    assert len(created["steps"]) == 2

    unchanged = created["steps"][0]
    changed_payload = {
        "steps": [
            {"description": unchanged["description"], "tool_name": unchanged["tool_name"],
             "tool_args": unchanged["tool_args"], "depends_on_step_index": unchanged["depends_on_step_index"]},
            {"description": "A genuinely different second step", "tool_name": "get_system_health",
             "tool_args": {}, "depends_on_step_index": None},
        ]
    }
    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps", json=changed_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan_edited"] is True
    steps = sorted(body["steps"], key=lambda s: s["step_index"])
    assert steps[0]["source"] == "llm_planned"
    assert steps[1]["source"] == "human_edited"
    assert steps[1]["tool_name"] == "get_system_health"


@pytest.mark.asyncio
async def test_edit_rejects_a_tool_outside_the_shapes_allowlist(client, monkeypatch):
    """The same validator plan generation is bound by -- a human editing a
    plan cannot insert a tool the planner itself couldn't have proposed."""
    token, _, _ = await _register(client, "editbadtool")
    created = await _create_task(client, token, monkeypatch)

    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps",
        json={"steps": [
            {"description": "Try to sneak in a mutating tool", "tool_name": "sync_source",
             "tool_args": {"source_id": "s-1"}, "depends_on_step_index": None},
        ]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422
    assert "not permitted" in r.json()["detail"]

    # Confirm the rejection didn't mutate anything -- the original plan is intact.
    async with AsyncSessionLocal() as db:
        r2 = await db.execute(select(Task).where(Task.id == created["id"]))
        task = r2.scalar_one()
        assert task.plan_edited is False


@pytest.mark.asyncio
async def test_edit_after_plan_leaves_draft_plan_is_409(client, monkeypatch):
    token, _, _ = await _register(client, "editafterleave")
    created = await _create_task(client, token, monkeypatch)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == created["id"]))
        task = r.scalar_one()
        task.status = TaskStatus.QUEUED
        await db.commit()

    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps",
        json={"steps": [
            {"description": "too late", "tool_name": "get_system_health",
             "tool_args": {}, "depends_on_step_index": None},
        ]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_only_the_creator_may_edit_the_plan(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "editnotmine")
    created = await _create_task(client, token, monkeypatch)

    async with AsyncSessionLocal() as db:
        other = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Other Member",
            role="owner", is_active=True, email_verified=True,
        )
        db.add(other)
        await db.commit()
        other_token = issue_token_for_user(other, "password")

    r = await client.patch(
        f"/api/v1/tasks/{created['id']}/steps",
        json={"steps": [
            {"description": "not my plan to edit", "tool_name": "get_system_health",
             "tool_args": {}, "depends_on_step_index": None},
        ]},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 403
