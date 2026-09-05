"""Wunomo Projects Phase 2 frontend, slice 4: offboarding an agent.

OFFBOARDED must be an enforced state, not just a display label (explicit
requirement) -- these tests prove three things together: (1) offboarding
is blocked while the agent owns a non-terminal task, naming that task,
(2) offboarding actually removes reachability (channel membership,
@mention resolution, and the per-step _caller_still_authorized re-check
in task_executor.py), not just the status column, and (3) history and
agent_sources survive untouched.

This file deletes every Task/Channel/ChannelAgent row it creates (see
test_auto_advance.py's own docstring for why real teardown matters here,
not just hygiene -- item 74's backlog is the same shape at a much larger
scale).
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, AgentInstanceStatus, Channel, ChannelAgent, Task, TaskShape, TaskStatus,
)
from modules.orchestration.task_executor import _caller_still_authorized
from services.channel_routing import channel_agent_members, resolve_mentioned_agent


@pytest_asyncio.fixture
async def created_ids():
    ids = {"tasks": [], "channels": [], "channel_agents": []}
    yield ids
    async with AsyncSessionLocal() as db:
        if ids["channel_agents"]:
            await db.execute(ChannelAgent.__table__.delete().where(ChannelAgent.id.in_(ids["channel_agents"])))
        if ids["tasks"]:
            await db.execute(Task.__table__.delete().where(Task.id.in_(ids["tasks"])))
        if ids["channels"]:
            await db.execute(Channel.__table__.delete().where(Channel.id.in_(ids["channels"])))
        await db.commit()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _register(client, prefix="offboard"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Offboard Test",
        "tenant_name": f"Offboard Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _real_agent_id(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.tenant_id == tenant_id))
        return r.scalar_one().id


async def _seed_task(tenant_id, user_id, agent_id, status, created_ids):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=status, step_budget_max=20,
        )
        db.add(task)
        await db.commit()
        created_ids["tasks"].append(task.id)
        return task.id


async def _seed_channel_membership(tenant_id, agent_id, created_ids):
    async with AsyncSessionLocal() as db:
        channel = Channel(id=str(uuid.uuid4()), tenant_id=tenant_id, name="test-channel")
        db.add(channel)
        await db.flush()
        membership = ChannelAgent(id=str(uuid.uuid4()), channel_id=channel.id, agent_id=agent_id)
        db.add(membership)
        await db.commit()
        created_ids["channels"].append(channel.id)
        created_ids["channel_agents"].append(membership.id)
        return channel.id


# ---------------------------------------------------------------------------
# Task-blocking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offboard_succeeds_with_no_tasks(client):
    token, tenant_id, _ = await _register(client, "offboardA")
    agent_id = await _real_agent_id(tenant_id)

    resp = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "offboarded"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance.status).where(AgentInstance.id == agent_id))
        assert r.scalar_one() == AgentInstanceStatus.OFFBOARDED


@pytest.mark.asyncio
async def test_offboard_blocked_by_running_task_and_names_it(client, created_ids):
    token, tenant_id, user_id = await _register(client, "offboardB")
    agent_id = await _real_agent_id(tenant_id)
    task_id = await _seed_task(tenant_id, user_id, agent_id, TaskStatus.RUNNING, created_ids)

    resp = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["task_id"] == task_id
    assert task_id in detail["message"]
    assert "running" in detail["message"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance.status).where(AgentInstance.id == agent_id))
        assert r.scalar_one() == AgentInstanceStatus.ACTIVE


@pytest.mark.asyncio
async def test_offboard_blocked_by_task_paused_for_approval(client, created_ids):
    """A pending approval is caught by the same terminal-status check --
    no separate ApprovalRequest query needed, since PAUSED_NEEDS_APPROVAL
    is already non-terminal."""
    token, tenant_id, user_id = await _register(client, "offboardC")
    agent_id = await _real_agent_id(tenant_id)
    await _seed_task(tenant_id, user_id, agent_id, TaskStatus.PAUSED_NEEDS_APPROVAL, created_ids)

    resp = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_offboard_succeeds_once_task_is_terminal(client, created_ids):
    token, tenant_id, user_id = await _register(client, "offboardD")
    agent_id = await _real_agent_id(tenant_id)
    await _seed_task(tenant_id, user_id, agent_id, TaskStatus.COMPLETED, created_ids)

    resp = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "offboarded"


@pytest.mark.asyncio
async def test_offboard_is_idempotent(client):
    token, tenant_id, _ = await _register(client, "offboardE")
    agent_id = await _real_agent_id(tenant_id)

    first = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    second = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "offboarded"


# ---------------------------------------------------------------------------
# Reachability actually removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offboard_removes_channel_membership(client, created_ids):
    token, tenant_id, _ = await _register(client, "offboardF")
    agent_id = await _real_agent_id(tenant_id)
    channel_id = await _seed_channel_membership(tenant_id, agent_id, created_ids)

    resp = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ChannelAgent).where(ChannelAgent.channel_id == channel_id))
        assert r.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_offboarded_agent_not_resolvable_by_mention(client, created_ids):
    token, tenant_id, _ = await _register(client, "offboardG")
    agent_id = await _real_agent_id(tenant_id)
    channel_id = await _seed_channel_membership(tenant_id, agent_id, created_ids)

    async with AsyncSessionLocal() as db:
        agent_name = (await db.execute(
            select(AgentInstance.name).where(AgentInstance.id == agent_id)
        )).scalar_one()

    async with AsyncSessionLocal() as db:
        before = await resolve_mentioned_agent(db, channel_id, agent_name)
        assert before is not None

    await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))

    # Offboard deletes the channel_agents row (proven above), which alone
    # would already make resolution fail -- re-add membership here to
    # isolate the status filter itself, not just membership removal.
    async with AsyncSessionLocal() as db:
        membership_id = str(uuid.uuid4())
        db.add(ChannelAgent(id=membership_id, channel_id=channel_id, agent_id=agent_id))
        await db.commit()
    created_ids["channel_agents"].append(membership_id)

    async with AsyncSessionLocal() as db:
        after = await resolve_mentioned_agent(db, channel_id, agent_name)
        assert after is None
        members = await channel_agent_members(db, channel_id)
        assert agent_id not in [m.id for m in members]


# ---------------------------------------------------------------------------
# Per-step re-check (_caller_still_authorized)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_caller_still_authorized_rejects_offboarded_agent(client, created_ids):
    token, tenant_id, user_id = await _register(client, "offboardH")
    agent_id = await _real_agent_id(tenant_id)
    task_id = await _seed_task(tenant_id, user_id, agent_id, TaskStatus.RUNNING, created_ids)

    async with AsyncSessionLocal() as db:
        agent = (await db.execute(select(AgentInstance).where(AgentInstance.id == agent_id))).scalar_one()
        agent.status = AgentInstanceStatus.OFFBOARDED
        await db.commit()

    async with AsyncSessionLocal() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        authorized, reason, scope_denial = await _caller_still_authorized(db, task, "sync_source", {})
        assert authorized is False
        assert "offboarded" in reason
        assert scope_denial is None  # this denial was agent-offboarded, not a scope gap


# ---------------------------------------------------------------------------
# History and scope survive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offboard_preserves_source_scope(client):
    token, tenant_id, _ = await _register(client, "offboardI")
    agent_id = await _real_agent_id(tenant_id)

    src = await client.post("/api/v1/sources/", headers=_auth(token), json={
        "name": "Offboard Test Source", "source_type": "postgres",
        "connection_config": {"host": "postgres", "port": 5432, "database": "x", "user": "x", "password": "x"},
    })
    source_id = src.json()["id"]
    grant = await client.post(f"/api/v1/agents/{agent_id}/sources/{source_id}", headers=_auth(token))
    assert grant.status_code == 200

    await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))

    sources_after = await client.get(f"/api/v1/agents/{agent_id}/sources", headers=_auth(token))
    assert any(s["id"] == source_id for s in sources_after.json()["sources"])


# ---------------------------------------------------------------------------
# GET /{agent_id}/quota
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_agent_quota_endpoint(client):
    token, tenant_id, _ = await _register(client, "offboardJ")
    agent_id = await _real_agent_id(tenant_id)

    resp = await client.get(f"/api/v1/agents/{agent_id}/quota", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == agent_id
    assert body["limit"] is None
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# Name reuse stays blocked (documented decision, GOTCHAS.md)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offboarded_agents_name_stays_blocked_from_reuse(client):
    token, tenant_id, _ = await _register(client, "offboardK")

    hire = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "Nova", "employee_type": "dataops"})
    agent_id = hire.json()["id"]
    await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))

    retry = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "Nova", "employee_type": "dataops"})
    assert retry.status_code == 409
