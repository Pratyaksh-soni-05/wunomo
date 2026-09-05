"""Item 6 stage 7: GET /api/v1/tasks/all (hard-gated tasks.manage_all --
the real endpoint that capability was exempted pending, see stage 1).

Also GET /api/v1/tasks/active (Wunomo Projects Phase 4 frontend, slice
12 -- the tenant-wide task rail): replaces the old GET /api/v1/tasks/counts,
which returned only a bare number for the topbar badge. This endpoint
returns the real rows the rail renders, with the topbar badge now just
len() of this same response -- so this file's old "counts" tests became
"active" tests covering the richer shape (agent name, current step,
needs_attention/attention_tier/action_text), not a separate contract.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

import api.v1.tasks as tasks_module
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, OperationMode, PersonalityMode,
    Task, TaskStatus, TaskStep, TaskStepStatus, User,
)
from modules.orchestration.task_executor import APPROVAL_PAUSE_TIMEOUT_HOURS
from services.auth_service import hash_password, issue_token_for_user


async def _register(client, prefix="taskallactive"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Tasks All/Active Test",
        "tenant_name": f"Tasks All Active Corp {uuid.uuid4().hex[:6]}",
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


async def _set_status(task_id, status, **extra):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.status = status
        for k, v in extra.items():
            setattr(task, k, v)
        await db.commit()


async def _attach_agent(tenant_id, task_id, name="Nova"):
    async with AsyncSessionLocal() as db:
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, employee_type=AgentEmployeeType.DATAOPS,
            personality=PersonalityMode.ENGINEER, operation_mode=OperationMode.ASSISTED,
            model="gemini-3.5-flash", status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.agent_id = agent.id
        await db.commit()
        return agent.id


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
async def test_active_excludes_terminal_statuses(client, monkeypatch):
    token, _, _ = await _register(client, "activeterm")
    active_draft = await _create_mocked_task(client, token, monkeypatch, goal="still draft")
    done = await _create_mocked_task(client, token, monkeypatch, goal="done")
    failed = await _create_mocked_task(client, token, monkeypatch, goal="failed")
    await _set_status(done["id"], TaskStatus.COMPLETED)
    await _set_status(failed["id"], TaskStatus.FAILED)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    goals = {t["goal"] for t in r.json()}
    assert goals == {"still draft"}


@pytest.mark.asyncio
async def test_active_includes_paused_and_queued_states(client, monkeypatch):
    """A task needing approval or paused on a failed step still needs the
    user's attention -- it must appear, not be silently excluded just
    because nothing is currently executing."""
    token, _, _ = await _register(client, "activepaused")
    needs_approval = await _create_mocked_task(client, token, monkeypatch, goal="needs approval")
    paused_failed = await _create_mocked_task(client, token, monkeypatch, goal="paused failed")
    queued = await _create_mocked_task(client, token, monkeypatch, goal="queued")
    await _set_status(needs_approval["id"], TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=datetime.utcnow())
    await _set_status(paused_failed["id"], TaskStatus.PAUSED_FAILED_STEP)
    await _set_status(queued["id"], TaskStatus.QUEUED)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    assert len(r.json()) == 3


@pytest.mark.asyncio
async def test_active_is_scoped_to_own_tasks_without_manage_all(client, monkeypatch):
    owner_token, tenant_id, _ = await _register(client, "activescope")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")
    analyst_token, _ = await _member(tenant_id, "data_analyst", "activescopeanalyst")
    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's own task")

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {analyst_token}"})
    goals = {t["goal"] for t in r.json()}
    assert goals == {"analyst's own task"}


@pytest.mark.asyncio
async def test_active_covers_every_tenant_task_with_manage_all(client, monkeypatch):
    owner_token, tenant_id, _ = await _register(client, "activeall")
    await _create_mocked_task(client, owner_token, monkeypatch, goal="owner's task")
    analyst_token, _ = await _member(tenant_id, "data_analyst", "activeallanalyst")
    await _create_mocked_task(client, analyst_token, monkeypatch, goal="analyst's task")

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {owner_token}"})
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_active_never_leaks_another_tenants_tasks(client, monkeypatch):
    token_a, _, _ = await _register(client, "activetenantA")
    token_b, _, _ = await _register(client, "activetenantB")
    await _create_mocked_task(client, token_a, monkeypatch, goal="tenant A's task")
    await _create_mocked_task(client, token_b, monkeypatch, goal="tenant B's task")
    await _create_mocked_task(client, token_b, monkeypatch, goal="tenant B's second task")

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token_a}"})
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_route_order_all_and_active_are_not_swallowed_by_the_task_id_route(client):
    """/all and /active are literal path segments registered before the
    parameterized /{task_id} route -- if registration order regresses,
    'all'/'active' would be parsed as a task_id instead and 404, not
    reach the real handlers."""
    token, _, _ = await _register(client, "routeorder")
    r_all = await client.get("/api/v1/tasks/all", headers={"Authorization": f"Bearer {token}"})
    r_active = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    assert r_all.status_code in (200, 403)  # never 404 -- would mean it hit /{task_id} instead
    assert r_active.status_code == 200


@pytest.mark.asyncio
async def test_active_derives_needs_attention_from_runnable_minus_active_not_a_hardcoded_list(client, monkeypatch):
    """The whole point of deriving instead of hardcoding: every status
    that isn't in RUNNABLE_TASK_STATUSES needs attention, including ones
    with no dedicated reason-text helper (PAUSED_PLAN_INVALID)."""
    token, _, _ = await _register(client, "activederive")
    draft = await _create_mocked_task(client, token, monkeypatch, goal="draft")
    approval = await _create_mocked_task(client, token, monkeypatch, goal="approval")
    failed = await _create_mocked_task(client, token, monkeypatch, goal="failed")
    invalid = await _create_mocked_task(client, token, monkeypatch, goal="invalid")
    running = await _create_mocked_task(client, token, monkeypatch, goal="running")
    quota = await _create_mocked_task(client, token, monkeypatch, goal="quota")
    await _set_status(approval["id"], TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=datetime.utcnow())
    await _set_status(failed["id"], TaskStatus.PAUSED_FAILED_STEP)
    await _set_status(invalid["id"], TaskStatus.PAUSED_PLAN_INVALID)
    await _set_status(running["id"], TaskStatus.RUNNING)
    await _set_status(quota["id"], TaskStatus.PAUSED_QUOTA_EXCEEDED)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    by_goal = {t["goal"]: t for t in r.json()}
    assert by_goal["draft"]["needs_attention"] is True
    assert by_goal["approval"]["needs_attention"] is True
    assert by_goal["failed"]["needs_attention"] is True
    assert by_goal["invalid"]["needs_attention"] is True
    assert by_goal["running"]["needs_attention"] is False
    assert by_goal["quota"]["needs_attention"] is False


@pytest.mark.asyncio
async def test_active_sorts_needs_attention_tiers_and_auto_advancing_last(client, monkeypatch):
    token, _, _ = await _register(client, "activesort")
    draft = await _create_mocked_task(client, token, monkeypatch, goal="draft")
    approval = await _create_mocked_task(client, token, monkeypatch, goal="approval")
    failed = await _create_mocked_task(client, token, monkeypatch, goal="failed")
    running = await _create_mocked_task(client, token, monkeypatch, goal="running")
    await _set_status(approval["id"], TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=datetime.utcnow())
    await _set_status(failed["id"], TaskStatus.PAUSED_FAILED_STEP)
    await _set_status(running["id"], TaskStatus.RUNNING)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    goals_in_order = [t["goal"] for t in r.json()]
    assert goals_in_order == ["approval", "failed", "draft", "running"]


@pytest.mark.asyncio
async def test_active_sorts_expiring_approvals_soonest_first(client, monkeypatch):
    token, _, _ = await _register(client, "activesoonest")
    older = await _create_mocked_task(client, token, monkeypatch, goal="older approval")
    newer = await _create_mocked_task(client, token, monkeypatch, goal="newer approval")
    now = datetime.utcnow()
    await _set_status(older["id"], TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=now - timedelta(hours=40))
    await _set_status(newer["id"], TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=now - timedelta(hours=2))

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    goals_in_order = [t["goal"] for t in r.json()]
    assert goals_in_order == ["older approval", "newer approval"]


@pytest.mark.asyncio
async def test_active_action_text_names_the_fix_not_just_the_status(client, monkeypatch):
    token, _, _ = await _register(client, "activeaction")
    approval = await _create_mocked_task(client, token, monkeypatch, goal="approval")
    failed = await _create_mocked_task(client, token, monkeypatch, goal="failed")
    invalid = await _create_mocked_task(client, token, monkeypatch, goal="invalid")
    draft = await _create_mocked_task(client, token, monkeypatch, goal="draft")
    running = await _create_mocked_task(client, token, monkeypatch, goal="running")
    await _set_status(approval["id"], TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=datetime.utcnow() - timedelta(hours=10))
    await _set_status(failed["id"], TaskStatus.PAUSED_FAILED_STEP)
    await _set_status(invalid["id"], TaskStatus.PAUSED_PLAN_INVALID)
    await _set_status(running["id"], TaskStatus.RUNNING)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    by_goal = {t["goal"]: t for t in r.json()}
    assert by_goal["approval"]["action_text"] == "Review to approve or reject — expires in 38h."
    assert by_goal["failed"]["action_text"] == "Can't be resumed — start a new task."
    assert by_goal["invalid"]["action_text"] == "Can't be resumed — start a new task."
    assert by_goal["draft"]["action_text"] == "Review the plan to approve or reject."
    assert by_goal["running"]["action_text"] is None


@pytest.mark.asyncio
async def test_active_includes_agent_name_via_join(client, monkeypatch):
    # create_task() defaults agent_id to the tenant's auto-provisioned
    # AXIOM agent when none is named -- a genuinely unassigned task (the
    # column is nullable) has to be seeded directly to exercise the
    # outerjoin's None-agent_id branch, not produced by the real endpoint.
    token, tenant_id, _ = await _register(client, "activeagent")
    task = await _create_mocked_task(client, token, monkeypatch, goal="assigned")
    unassigned = await _create_mocked_task(client, token, monkeypatch, goal="unassigned")
    await _attach_agent(tenant_id, task["id"], name="Nova")
    await _set_status(unassigned["id"], TaskStatus.DRAFT_PLAN, agent_id=None)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    by_goal = {t["goal"]: t for t in r.json()}
    assert by_goal["assigned"]["agent_name"] == "Nova"
    assert by_goal["unassigned"]["agent_name"] is None


@pytest.mark.asyncio
async def test_active_surfaces_current_step(client, monkeypatch):
    token, _, _ = await _register(client, "activestep")
    task = await _create_mocked_task(client, token, monkeypatch, goal="stepped")

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    item = next(t for t in r.json() if t["goal"] == "stepped")
    assert item["current_step"] == {"step_index": 0, "description": "check history", "status": "pending"}


@pytest.mark.asyncio
async def test_task_detail_surfaces_plan_invalid_reason(client, monkeypatch):
    """PAUSED_PLAN_INVALID had no reason text anywhere before this slice
    (discovered while deriving the rail's needs_attention set) -- GET
    /{task_id} must now say what happened and that it's unrecoverable,
    same as the sibling PAUSED_FAILED_STEP field."""
    token, _, _ = await _register(client, "planinvalid")
    task = await _create_mocked_task(client, token, monkeypatch, goal="invalidated")
    await _set_status(task["id"], TaskStatus.PAUSED_PLAN_INVALID)

    r = await client.get(f"/api/v1/tasks/{task['id']}", headers={"Authorization": f"Bearer {token}"})
    body = r.json()
    assert "can no longer reach the goal" in body["plan_invalid_reason"]
    assert "can't be resumed" in body["plan_invalid_reason"]


@pytest.mark.asyncio
async def test_task_detail_plan_invalid_reason_is_null_for_other_statuses(client, monkeypatch):
    token, _, _ = await _register(client, "planinvalidnull")
    task = await _create_mocked_task(client, token, monkeypatch, goal="fine")

    r = await client.get(f"/api/v1/tasks/{task['id']}", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["plan_invalid_reason"] is None


@pytest.mark.asyncio
async def test_active_current_step_falls_back_to_last_step_when_all_done(client, monkeypatch):
    token, _, _ = await _register(client, "activedone")
    task = await _create_mocked_task(client, token, monkeypatch, goal="all done")
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task["id"]))
        step = r.scalar_one()
        step.status = TaskStepStatus.SUCCEEDED
        await db.commit()
    await _set_status(task["id"], TaskStatus.QUEUED)

    r = await client.get("/api/v1/tasks/active", headers={"Authorization": f"Bearer {token}"})
    item = next(t for t in r.json() if t["goal"] == "all done")
    assert item["current_step"]["status"] == "succeeded"
