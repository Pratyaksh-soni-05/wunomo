"""Wunomo Projects Phase 4: explicit agent selection for tasks. Before
this, POST /api/v1/tasks/ always resolved the tenant's oldest ACTIVE
agent, regardless of which agent a caller actually meant -- the
difference between "you can talk to different agents" (already real, via
chat/channels) and "different agents do different work" (tasks, where
the real work happens). Covers: an explicit agent_id is honored and
validated (tenant-scoped, must be ACTIVE); omitting it keeps the exact
pre-existing oldest-active fallback; and the new GET /api/v1/agents/
selectable endpoint, which exists specifically because the real GET /
is agents.manage-gated and a task creator isn't necessarily an Owner/Admin.
"""
import uuid

import pytest

from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, OperationMode, PersonalityMode, User,
)
from services.auth_service import hash_password, issue_token_for_user


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _register(client, prefix="taskagent"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Agent Selection Test",
        "tenant_name": f"Task Agent Selection Corp {uuid.uuid4().hex[:6]}",
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


async def _hire_agent(tenant_id, name, active=True):
    async with AsyncSessionLocal() as db:
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, employee_type=AgentEmployeeType.DATAOPS,
            personality=PersonalityMode.ENGINEER, operation_mode=OperationMode.ASSISTED,
            model="gemini-3.5-flash",
            status=AgentInstanceStatus.ACTIVE if active else AgentInstanceStatus.OFFBOARDED,
        )
        db.add(agent)
        await db.commit()
        return agent.id


async def _create_source(tenant_id, name):
    from models.all_models import DataSource, SourceType
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            source_type=SourceType.POSTGRES, connection_config={"host": "postgres"},
        )
        db.add(source)
        await db.commit()
        return source.id


async def _grant(agent_id, source_id):
    from models.all_models import AgentSource
    async with AsyncSessionLocal() as db:
        db.add(AgentSource(id=str(uuid.uuid4()), agent_id=agent_id, source_id=source_id))
        await db.commit()


async def _create_mocked_task(client, token, monkeypatch, goal="test goal", agent_id=None):
    import api.v1.tasks as tasks_module

    async def _fake_plan(tenant_id, user_id, goal, task_shape, task_id=None, agent_id=None):
        return [{
            "description": "check history", "tool_name": "get_pipeline_run_history",
            "tool_args": {"pipeline_id": "pl-1"}, "depends_on_step_index": None,
        }]

    monkeypatch.setattr(tasks_module, "generate_plan", _fake_plan)
    body = {"goal": goal, "task_shape": "diagnose_pipeline_failure"}
    if agent_id is not None:
        body["agent_id"] = agent_id
    return await client.post("/api/v1/tasks/", json=body, headers=_auth(token))


# ---------------------------------------------------------------------------
# Explicit agent_id on task creation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explicit_agent_id_is_honored(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "explicit")
    nova_id = await _hire_agent(tenant_id, "Nova")
    await _hire_agent(tenant_id, "Atlas")  # a second, older-by-default agent -- proves it's NOT picked

    r = await _create_mocked_task(client, token, monkeypatch, agent_id=nova_id)
    assert r.status_code == 200, r.text
    assert r.json()["id"]

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from models.all_models import Task
        result = await db.execute(select(Task).where(Task.id == r.json()["id"]))
        task = result.scalar_one()
        assert task.agent_id == nova_id


@pytest.mark.asyncio
async def test_omitted_agent_id_keeps_oldest_active_fallback(client, monkeypatch):
    """Explicit backward-compatibility guarantee: every caller that
    doesn't think about agent selection must keep behaving identically."""
    token, tenant_id, _ = await _register(client, "fallback")
    axiom_id = None
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from models.all_models import AgentInstance as AI
        result = await db.execute(select(AI).where(AI.tenant_id == tenant_id))
        axiom_id = result.scalar_one().id  # the auto-provisioned AXIOM row
    await _hire_agent(tenant_id, "Nova")  # hired after AXIOM -- must NOT be picked

    r = await _create_mocked_task(client, token, monkeypatch)  # no agent_id at all
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from models.all_models import Task
        result = await db.execute(select(Task).where(Task.id == r.json()["id"]))
        task = result.scalar_one()
        assert task.agent_id == axiom_id


@pytest.mark.asyncio
async def test_explicit_agent_id_rejects_offboarded_agent(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "offboardedpick")
    dead_id = await _hire_agent(tenant_id, "Retired", active=False)

    r = await _create_mocked_task(client, token, monkeypatch, agent_id=dead_id)
    assert r.status_code == 409
    assert "offboarded" in r.json()["detail"]


@pytest.mark.asyncio
async def test_explicit_agent_id_404s_for_nonexistent_agent(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "nonexistentpick")

    r = await _create_mocked_task(client, token, monkeypatch, agent_id="does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_explicit_agent_id_never_leaks_across_tenants(client, monkeypatch):
    token_a, tenant_a, _ = await _register(client, "crosstenantA")
    token_b, tenant_b, _ = await _register(client, "crosstenantB")
    other_tenants_agent = await _hire_agent(tenant_b, "NotYours")

    r = await _create_mocked_task(client, token_a, monkeypatch, agent_id=other_tenants_agent)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/agents/selectable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_selectable_endpoint_accessible_to_any_role_not_just_manage_all(client):
    """The real bug this endpoint fixes: GET / (agents.manage-gated) 403s
    for a data_analyst, which meant the channel-creation picker was
    already coming up empty for that role before this existed."""
    token, tenant_id, _ = await _register(client, "selectableperm")
    await _hire_agent(tenant_id, "Nova")
    analyst_token, _ = await _member(tenant_id, "data_analyst", "selectableanalyst")

    r_manage = await client.get("/api/v1/agents/", headers=_auth(analyst_token))
    assert r_manage.status_code == 403  # confirms the real gap this endpoint fixes

    r_selectable = await client.get("/api/v1/agents/selectable", headers=_auth(analyst_token))
    assert r_selectable.status_code == 200
    names = {a["name"] for a in r_selectable.json()["agents"]}
    assert "Nova" in names


@pytest.mark.asyncio
async def test_selectable_excludes_offboarded_agents(client):
    token, tenant_id, _ = await _register(client, "selectableoffboard")
    await _hire_agent(tenant_id, "Retired", active=False)
    await _hire_agent(tenant_id, "Active One")

    r = await client.get("/api/v1/agents/selectable", headers=_auth(token))
    names = {a["name"] for a in r.json()["agents"]}
    assert "Active One" in names
    assert "Retired" not in names


@pytest.mark.asyncio
async def test_selectable_includes_real_source_scope_not_just_a_count(client):
    token, tenant_id, _ = await _register(client, "selectablescope")
    nova_id = await _hire_agent(tenant_id, "Nova")
    source_id = await _create_source(tenant_id, "Marketing Data")
    await _grant(nova_id, source_id)
    await _hire_agent(tenant_id, "Atlas")  # unscoped -- must show empty sources, not omitted

    r = await client.get("/api/v1/agents/selectable", headers=_auth(token))
    by_name = {a["name"]: a for a in r.json()["agents"]}
    assert by_name["Nova"]["sources"] == [{"id": source_id, "name": "Marketing Data"}]
    assert by_name["Atlas"]["sources"] == []


@pytest.mark.asyncio
async def test_selectable_never_exposes_monthly_token_budget(client):
    """Deliberately narrower than GET / -- budget stays behind
    agents.manage even here."""
    token, tenant_id, _ = await _register(client, "selectablebudget")
    await _hire_agent(tenant_id, "Nova")

    r = await client.get("/api/v1/agents/selectable", headers=_auth(token))
    agent = r.json()["agents"][0]
    assert "monthly_token_budget" not in agent


@pytest.mark.asyncio
async def test_selectable_never_leaks_another_tenants_agents(client):
    token_a, tenant_a, _ = await _register(client, "selectabletenantA")
    token_b, tenant_b, _ = await _register(client, "selectabletenantB")
    await _hire_agent(tenant_b, "NotYours")

    r = await client.get("/api/v1/agents/selectable", headers=_auth(token_a))
    names = {a["name"] for a in r.json()["agents"]}
    assert "NotYours" not in names
