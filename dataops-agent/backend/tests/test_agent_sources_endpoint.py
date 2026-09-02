"""Wunomo Projects Phase 1: POST/DELETE/GET /api/v1/agents/{agent_id}/
sources/{source_id} -- the fix for the real UX gap logged in GOTCHAS.md
(a source connected after an agent already exists was invisible to it,
with no self-service way to grant access). See test_permission_matrix.py
for the Owner/Admin role gate itself; these tests cover the endpoints'
own behavior and, in test_connect_grant_and_use_source_end_to_end, the
full real path this was built to fix.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import AgentInstance, AgentSource, DataSource, User
from services.agent_scope import agent_scope_denial_reason


async def _register(client, prefix="agentsrc"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Agent Sources Test",
        "tenant_name": f"Agent Sources Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _real_agent_id(tenant_id: str) -> str:
    """create_new_tenant_and_user() creates exactly one AXIOM row per
    new tenant (Phase 1 commit 2) -- this is it."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.tenant_id == tenant_id))
        return r.scalar_one().id


async def _make_source(tenant_id: str, name="Source") -> str:
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            source_type="postgres", connection_config={},
        )
        db.add(source)
        await db.commit()
        return source.id


@pytest.mark.asyncio
async def test_grant_then_list_then_revoke(client):
    token, tenant_id, _ = await _register(client, "grantlist")
    agent_id = await _real_agent_id(tenant_id)
    source_id = await _make_source(tenant_id, "Warehouse")

    r = await client.post(f"/api/v1/agents/{agent_id}/sources/{source_id}", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["granted"] is True
    assert body["source_name"] == "Warehouse"

    r = await client.get(f"/api/v1/agents/{agent_id}/sources", headers=_auth(token))
    assert r.status_code == 200
    assert {s["id"] for s in r.json()["sources"]} == {source_id}

    r = await client.delete(f"/api/v1/agents/{agent_id}/sources/{source_id}", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["granted"] is False

    r = await client.get(f"/api/v1/agents/{agent_id}/sources", headers=_auth(token))
    assert r.json()["sources"] == []


@pytest.mark.asyncio
async def test_granting_twice_is_a_noop_not_a_duplicate_row(client):
    token, tenant_id, _ = await _register(client, "grantdup")
    agent_id = await _real_agent_id(tenant_id)
    source_id = await _make_source(tenant_id)

    for _ in range(2):
        r = await client.post(f"/api/v1/agents/{agent_id}/sources/{source_id}", headers=_auth(token))
        assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentSource).where(
            AgentSource.agent_id == agent_id, AgentSource.source_id == source_id,
        ))
        assert len(r.scalars().all()) == 1


@pytest.mark.asyncio
async def test_revoking_an_ungranted_source_is_a_noop_not_a_404(client):
    token, tenant_id, _ = await _register(client, "revokenone")
    agent_id = await _real_agent_id(tenant_id)
    source_id = await _make_source(tenant_id)

    r = await client.delete(f"/api/v1/agents/{agent_id}/sources/{source_id}", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["granted"] is False


@pytest.mark.asyncio
async def test_grant_rejects_a_cross_tenant_agent(client):
    token_a, tenant_a, _ = await _register(client, "crossA")
    _, tenant_b, _ = await _register(client, "crossB")
    agent_b = await _real_agent_id(tenant_b)
    source_a = await _make_source(tenant_a)

    r = await client.post(f"/api/v1/agents/{agent_b}/sources/{source_a}", headers=_auth(token_a))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_grant_rejects_a_cross_tenant_source(client):
    token_a, tenant_a, _ = await _register(client, "crossC")
    _, tenant_b, _ = await _register(client, "crossD")
    agent_a = await _real_agent_id(tenant_a)
    source_b = await _make_source(tenant_b)

    r = await client.post(f"/api/v1/agents/{agent_a}/sources/{source_b}", headers=_auth(token_a))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_denial_message_points_at_the_grant_endpoint(client):
    tenant_id_setup = await _register(client, "denialmsg")
    token, tenant_id, _ = tenant_id_setup
    agent_id = await _real_agent_id(tenant_id)
    source_id = await _make_source(tenant_id, "Marketing Analytics")

    async with AsyncSessionLocal() as db:
        reason = await agent_scope_denial_reason(db, agent_id, "sync_source", {"source_id": source_id})
    assert reason is not None
    assert f"/api/v1/agents/{agent_id}/sources/{source_id}" in reason
    assert "Owner or Admin can grant it" in reason


@pytest.mark.asyncio
async def test_connect_grant_and_use_source_end_to_end(client, monkeypatch):
    """The real path this endpoint was built to fix: a customer connects
    a new source, an agent can't touch it, an Owner/Admin grants it via
    the new endpoint, and the agent can use it afterward -- proven
    through the real chat tool-dispatch gate, not just a direct DB
    check."""
    import agent.dataops_agent as dataops_agent
    from langchain_core.messages import AIMessage

    class FakeToolCallLLM:
        def __init__(self, responses):
            self._responses = list(responses)

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return self._responses.pop(0)

    token, tenant_id, user_id = await _register(client, "e2egrant")
    agent_id = await _real_agent_id(tenant_id)

    # 1. Connect a real new source via the real REST endpoint.
    r = await client.post("/api/v1/sources/", headers=_auth(token), json={
        "name": "Marketing Analytics", "source_type": "postgres",
        "connection_config": {"host": "postgres", "database": "demo"},
    })
    assert r.status_code == 200
    source_id = r.json()["id"]

    # 2. Before granting: AXIOM cannot use it (real chat path, real gate).
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "sync_source", "args": {"source_id": source_id}, "id": "call_1"},
        ]),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    r = await client.post("/api/v1/chat/", json={"message": "sync marketing analytics"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["status"] == "denied_out_of_scope"

    # 3. Grant it via the new endpoint.
    r = await client.post(f"/api/v1/agents/{agent_id}/sources/{source_id}", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["granted"] is True

    # 4. After granting: the identical request now goes through.
    fake_llm_2 = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "sync_source", "args": {"source_id": source_id}, "id": "call_2"},
        ]),
        AIMessage(content="Synced."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm_2)
    dataops_agent._cache.clear()

    r = await client.post("/api/v1/chat/", json={"message": "sync marketing analytics"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["status"] == "completed"
