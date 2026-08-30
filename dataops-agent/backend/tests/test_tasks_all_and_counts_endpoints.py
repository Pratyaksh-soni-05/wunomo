"""Item 6 stage 7: GET /api/v1/tasks/all (hard-gated tasks.manage_all --
the real endpoint that capability was exempted pending, see stage 1) and
GET /api/v1/tasks/counts (the topbar's real active-task count -- must be
a real live count against the real DB or it doesn't ship per explicit
requirement, not a decorative placeholder).
"""
import uuid

import pytest
from sqlalchemy import select

import api.v1.tasks as tasks_module
from database import AsyncSessionLocal
from models.all_models import Task, TaskStatus, User
from services.auth_service import hash_password, issue_token_for_user


async def _register(client, prefix="taskallcounts"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Tasks All/Counts Test",
        "tenant_name": f"Tasks All Counts Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _member(tenant_id, role, prefix="member"):
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name=prefix, role=role,
            is_active=True, email_verified=True,
        )
        db.add(user)
        await db.commit()
        return issue_token_for_user(user, "password"), user.id


async def _create_mocked_task(client, token, monkeypatch, goal="test goal"):
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


async def _set_status(task_id, status):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.status = status
        await db.commit()


@pytest.mark.asyncio
async def test_all_returns_every_tenant_task_for_owner(client, monkeypatch):
    owner_token, tenant_id, _ = await _register(client, "allowner")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")
    analyst_token, _ = await _member(tenant_id, "data_analyst", "allanalyst")
    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's task")

    r = await client.get("/api/v1/tasks/all", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200
    goals = {t["goal"] for t in r.json()}
    assert goals == {"owner's task", "analyst's task"}


@pytest.mark.asyncio
async def test_all_is_403_without_tasks_manage_all(client, monkeypatch):
    owner_token, tenant_id, _ = await _register(client, "allnoperm")
    await _create_mocked_task(client, owner_token, monkeypatch)
    analyst_token, _ = await _member(tenant_id, "data_analyst", "allnopermanalyst")

    r = await client.get("/api/v1/tasks/all", headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_all_never_leaks_another_tenants_tasks(client, monkeypatch):
    token_a, _, _ = await _register(client, "alltenantA")
    token_b, _, _ = await _register(client, "alltenantB")
    await _create_mocked_task(client, token_a, monkeypatch, goal="tenant A's task")
    await _create_mocked_task(client, token_b, monkeypatch, goal="tenant B's task")

    r = await client.get("/api/v1/tasks/all", headers={"Authorization": f"Bearer {token_a}"})
    goals = {t["goal"] for t in r.json()}
    assert goals == {"tenant A's task"}


@pytest.mark.asyncio
async def test_counts_excludes_terminal_statuses(client, monkeypatch):
    token, _, _ = await _register(client, "countsterm")
    active_draft = await _create_mocked_task(client, token, monkeypatch, goal="still draft")
    done = await _create_mocked_task(client, token, monkeypatch, goal="done")
    failed = await _create_mocked_task(client, token, monkeypatch, goal="failed")
    await _set_status(done["id"], TaskStatus.COMPLETED)
    await _set_status(failed["id"], TaskStatus.FAILED)

    r = await client.get("/api/v1/tasks/counts", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["active"] == 1  # only the still-draft one


@pytest.mark.asyncio
async def test_counts_includes_paused_and_queued_states_as_active(client, monkeypatch):
    """A task needing approval or paused on a failed step still needs the
    user's attention -- it must count as 'active', not be silently
    excluded just because nothing is currently executing."""
    token, _, _ = await _register(client, "countspaused")
    needs_approval = await _create_mocked_task(client, token, monkeypatch, goal="needs approval")
    paused_failed = await _create_mocked_task(client, token, monkeypatch, goal="paused failed")
    queued = await _create_mocked_task(client, token, monkeypatch, goal="queued")
    await _set_status(needs_approval["id"], TaskStatus.PAUSED_NEEDS_APPROVAL)
    await _set_status(paused_failed["id"], TaskStatus.PAUSED_FAILED_STEP)
    await _set_status(queued["id"], TaskStatus.QUEUED)

    r = await client.get("/api/v1/tasks/counts", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["active"] == 3


@pytest.mark.asyncio
async def test_counts_is_scoped_to_own_tasks_without_manage_all(client, monkeypatch):
    owner_token, tenant_id, _ = await _register(client, "countsscope")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")
    analyst_token, _ = await _member(tenant_id, "data_analyst", "countsscopeanalyst")
    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's own task")

    r = await client.get("/api/v1/tasks/counts", headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.json()["active"] == 1  # only the analyst's own


@pytest.mark.asyncio
async def test_counts_covers_every_tenant_task_with_manage_all(client, monkeypatch):
    owner_token, tenant_id, _ = await _register(client, "countsall")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")
    analyst_token, _ = await _member(tenant_id, "data_analyst", "countsallanalyst")
    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's task")

    r = await client.get("/api/v1/tasks/counts", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.json()["active"] == 2


@pytest.mark.asyncio
async def test_counts_never_leaks_another_tenants_tasks(client, monkeypatch):
    token_a, _, _ = await _register(client, "countstenantA")
    token_b, _, _ = await _register(client, "countstenantB")
    await _create_mocked_task(client, token_a, monkeypatch, goal="tenant A's task")
    await _create_mocked_task(client, token_b, monkeypatch, goal="tenant B's task")
    await _create_mocked_task(client, token_b, monkeypatch, goal="tenant B's second task")

    r = await client.get("/api/v1/tasks/counts", headers={"Authorization": f"Bearer {token_a}"})
    assert r.json()["active"] == 1


@pytest.mark.asyncio
async def test_route_order_all_and_counts_are_not_swallowed_by_the_task_id_route(client):
    """/all and /counts are literal path segments registered before the
    parameterized /{task_id} route -- if registration order regresses,
    'all'/'counts' would be parsed as a task_id instead and 404, not
    reach the real handlers."""
    token, _, _ = await _register(client, "routeorder")
    r_all = await client.get("/api/v1/tasks/all", headers={"Authorization": f"Bearer {token}"})
    r_counts = await client.get("/api/v1/tasks/counts", headers={"Authorization": f"Bearer {token}"})
    assert r_all.status_code in (200, 403)  # never 404 -- would mean it hit /{task_id} instead
    assert r_counts.status_code == 200
