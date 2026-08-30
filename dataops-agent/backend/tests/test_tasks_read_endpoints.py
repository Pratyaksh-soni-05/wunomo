"""GET /api/v1/tasks/ and GET /api/v1/tasks/{id} -- item 6 stage 2 (part 2
of the planning phase). Own tasks are always visible to their creator;
cross-member visibility requires tasks.manage_all (Owner/Admin), mirroring
Team's own precedent.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import User
from services.auth_service import issue_token_for_user


async def _register(client, prefix="taskread"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Read Test",
        "tenant_name": f"Task Read Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _token_for_role(user_id: str, role: str) -> str:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = role
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        return issue_token_for_user(user, "password")


async def _create_mocked_task(client, token, monkeypatch, goal="test goal"):
    import api.v1.tasks as tasks_module

    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None):
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


@pytest.mark.asyncio
async def test_get_own_task_returns_full_detail_with_tool_args(client, monkeypatch):
    token, _, _ = await _register(client, "taskreaddetail")
    created = await _create_mocked_task(client, token, monkeypatch)

    r = await client.get(f"/api/v1/tasks/{created['id']}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["goal"] == "test goal"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["tool_name"] == "get_pipeline_run_history"
    assert body["steps"][0]["tool_args"] == {"pipeline_id": "pl-1"}


@pytest.mark.asyncio
async def test_nonexistent_task_id_is_404(client):
    token, _, _ = await _register(client, "tasknotfound")
    r = await client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_another_users_task_is_403_without_manage_all(client, monkeypatch):
    """Two members of the SAME tenant, neither with tasks.manage_all --
    creator's own view works, the other member is blocked, not 404'd
    (they can see it exists via GET /tasks/ if they had list access, but
    here we're testing detail access specifically)."""
    owner_token, tenant_id, owner_user_id = await _register(client, "taskownerA")
    created = await _create_mocked_task(client, owner_token, monkeypatch)

    # A second real user in the SAME tenant via direct DB insert (cheapest
    # way to get a second real member without the full invite flow).
    async with AsyncSessionLocal() as db:
        from services.auth_service import hash_password
        other = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Other Member",
            role="data_analyst", is_active=True, email_verified=True,
        )
        db.add(other)
        await db.commit()
        other_token = issue_token_for_user(other, "password")

    r = await client.get(f"/api/v1/tasks/{created['id']}", headers={"Authorization": f"Bearer {other_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_owner_with_manage_all_can_view_another_members_task(client, monkeypatch):
    owner_token, tenant_id, owner_user_id = await _register(client, "taskownerB")

    async with AsyncSessionLocal() as db:
        from services.auth_service import hash_password
        member = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"member-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Regular Member",
            role="data_analyst", is_active=True, email_verified=True,
        )
        db.add(member)
        await db.commit()
        member_token = issue_token_for_user(member, "password")

    created = await _create_mocked_task(client, member_token, monkeypatch, goal="member's task")
    # owner_token's user already has role "owner" from registration (see
    # create_new_tenant_and_user) — real tasks.manage_all coverage.
    r = await client.get(f"/api/v1/tasks/{created['id']}", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200
    assert r.json()["goal"] == "member's task"


@pytest.mark.asyncio
async def test_list_shows_only_own_tasks_for_a_non_manager_role(client, monkeypatch):
    owner_token, tenant_id, owner_user_id = await _register(client, "tasklistA")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")

    async with AsyncSessionLocal() as db:
        from services.auth_service import hash_password
        analyst = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"analyst-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Analyst",
            role="data_analyst", is_active=True, email_verified=True,
        )
        db.add(analyst)
        await db.commit()
        analyst_token = issue_token_for_user(analyst, "password")

    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's own task")

    r = await client.get("/api/v1/tasks/", headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 200
    goals = {t["goal"] for t in r.json()}
    assert goals == {"analyst's own task"}


@pytest.mark.asyncio
async def test_list_shows_every_tenant_task_for_a_manage_all_role(client, monkeypatch):
    owner_token, tenant_id, owner_user_id = await _register(client, "tasklistB")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")

    async with AsyncSessionLocal() as db:
        from services.auth_service import hash_password
        analyst = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"analyst2-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Analyst2",
            role="data_analyst", is_active=True, email_verified=True,
        )
        db.add(analyst)
        await db.commit()
        analyst_token = issue_token_for_user(analyst, "password")

    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's task")

    r = await client.get("/api/v1/tasks/", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200
    goals = {t["goal"] for t in r.json()}
    assert goals == {"owner's task", "analyst's task"}


@pytest.mark.asyncio
async def test_list_never_leaks_another_tenants_tasks(client, monkeypatch):
    token_a, tenant_a, _ = await _register(client, "tasktenantA")
    token_b, tenant_b, _ = await _register(client, "tasktenantB")
    await _create_mocked_task(client, token_a, monkeypatch, goal="tenant A's task")
    await _create_mocked_task(client, token_b, monkeypatch, goal="tenant B's task")

    r = await client.get("/api/v1/tasks/", headers={"Authorization": f"Bearer {token_a}"})
    goals = {t["goal"] for t in r.json()}
    assert goals == {"tenant A's task"}
