"""Wunomo Projects Phase 1, part one: intersection permission enforcement,
chat-layer half (agent_node's new scope gate). Mirrors
test_agent_role_gate.py's own shape and philosophy -- most tests here hit
services/agent_scope.py and agent_scope_denied_tool_calls() directly with
real DB rows but no LLM, per the same "avoid burning quota on routine gate
checks" reasoning. The two required failure shapes (see CLAUDE.md's
intersection-permission rule):

  (a) High-role caller, narrow-scope agent: denial attributable to SCOPE,
      not role -- the property the rule exists for.
  (b) Low-role caller, broad-scope agent: still denied by ROLE -- the
      original Viewer-bypasses-the-gate bug wearing a new door.

test_scope_and_role_gates_compose_through_real_chat below re-runs both
through the actual /api/v1/chat/ endpoint, the same "both real consumers"
proof test_viewer_blocked_from_pipeline_trigger_both_consumers used for
the role-only gate.
"""
import uuid

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

import agent.dataops_agent as dataops_agent
from agent.dataops_agent import agent_scope_denied_tool_calls, role_denied_tool_calls
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, AgentSource,
    DataSource, OperationMode, PersonalityMode, SourceType, User,
)
from services.agent_scope import agent_scope_denial_reason, agent_touches_source


def unique_email(prefix="scopegate"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _register(client, prefix="scopegate"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": unique_email(prefix), "password": "test1234",
        "full_name": "Scope Gate Tester", "tenant_name": f"Scope Gate Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _make_source(tenant_id: str, name="Source") -> str:
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            source_type=SourceType.POSTGRES, connection_config={},
        )
        db.add(source)
        await db.commit()
        return source.id


async def _make_agent(tenant_id: str, name="Nova", scoped_source_ids=None) -> str:
    async with AsyncSessionLocal() as db:
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            employee_type=AgentEmployeeType.DATAOPS, personality=PersonalityMode.ENGINEER,
            operation_mode=OperationMode.ASSISTED, model="gemini-3.5-flash",
            status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        await db.flush()
        for source_id in (scoped_source_ids or []):
            db.add(AgentSource(id=str(uuid.uuid4()), agent_id=agent.id, source_id=source_id))
        await db.commit()
        return agent.id


async def _set_role(user_id: str, role: str) -> None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = role
        await db.commit()


# ---------------------------------------------------------------------------
# services/agent_scope.py direct tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_touches_source_true_and_false(client):
    _, tenant_id, _ = await _register(client)
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[source_a])

    async with AsyncSessionLocal() as db:
        assert await agent_touches_source(db, agent_id, source_a) is True
        assert await agent_touches_source(db, agent_id, source_b) is False


@pytest.mark.asyncio
async def test_agent_with_zero_scope_rows_is_denied_everything(client):
    """Fail-closed, confirmed decision (2026-09-03): zero agent_sources
    rows means zero access, not unrestricted access."""
    _, tenant_id, _ = await _register(client)
    source_a = await _make_source(tenant_id, "Source A")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[])  # no scope at all

    async with AsyncSessionLocal() as db:
        reason = await agent_scope_denial_reason(db, agent_id, "sync_source", {"source_id": source_a})
    assert reason is not None
    assert "isn't scoped" in reason["message"]


@pytest.mark.asyncio
async def test_denial_dict_carries_structured_fields_not_just_a_string(client):
    """Wunomo Projects Phase 2 frontend, slice 9: callers that build a real
    UI action (a "grant access" link pre-scoped to this exact agent/
    source, a deduped notification keyed on the (agent_id, source_id)
    pair) need these fields directly -- not a prose string to parse ids
    back out of."""
    _, tenant_id, _ = await _register(client)
    source_a = await _make_source(tenant_id, "Warehouse")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[])

    async with AsyncSessionLocal() as db:
        denial = await agent_scope_denial_reason(db, agent_id, "sync_source", {"source_id": source_a})
    assert set(denial.keys()) == {"message", "agent_id", "agent_name", "source_id", "source_name", "tool_name"}
    assert denial["agent_id"] == agent_id
    assert denial["source_id"] == source_a
    assert denial["source_name"] == "Warehouse"
    assert denial["tool_name"] == "sync_source"
    assert "POST /api/v1/agents/" in denial["message"]


@pytest.mark.asyncio
async def test_agent_id_none_is_a_transitional_noop(client):
    """No agent context at all (agent_id=None) must never deny -- role
    alone keeps governing in that case, unchanged from before this gate
    existed."""
    async with AsyncSessionLocal() as db:
        reason = await agent_scope_denial_reason(db, None, "sync_source", {"source_id": "anything"})
    assert reason is None


@pytest.mark.asyncio
async def test_not_source_scoped_tool_is_never_denied(client):
    _, tenant_id, _ = await _register(client)
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[])
    async with AsyncSessionLocal() as db:
        reason = await agent_scope_denial_reason(db, agent_id, "list_data_sources", {})
    assert reason is None


@pytest.mark.asyncio
async def test_pipeline_and_incident_resolution_reach_the_owning_source(client):
    """A tool that only takes pipeline_id/incident_id must still be
    scope-checked against the SOURCE that pipeline/incident belongs to
    -- not skipped just because the arg isn't literally source_id."""
    from models.all_models import Incident, Pipeline

    _, tenant_id, _ = await _register(client)
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[source_a])

    async with AsyncSessionLocal() as db:
        pipeline_on_a = Pipeline(id=str(uuid.uuid4()), tenant_id=tenant_id, name="P-A", source_id=source_a)
        pipeline_on_b = Pipeline(id=str(uuid.uuid4()), tenant_id=tenant_id, name="P-B", source_id=source_b)
        db.add_all([pipeline_on_a, pipeline_on_b])
        await db.flush()
        incident_on_b = Incident(id=str(uuid.uuid4()), tenant_id=tenant_id, pipeline_id=pipeline_on_b.id, title="Stale")
        db.add(incident_on_b)
        await db.commit()
        pipeline_on_a_id, pipeline_on_b_id, incident_on_b_id = pipeline_on_a.id, pipeline_on_b.id, incident_on_b.id

    async with AsyncSessionLocal() as db:
        assert await agent_scope_denial_reason(db, agent_id, "run_pipeline", {"pipeline_id": pipeline_on_a_id}) is None
        denial = await agent_scope_denial_reason(db, agent_id, "run_pipeline", {"pipeline_id": pipeline_on_b_id})
        assert denial is not None and "Source B" in denial["message"]
        assert denial["source_name"] == "Source B" and denial["source_id"] == source_b

        denial = await agent_scope_denial_reason(db, agent_id, "resolve_incident", {"incident_id": incident_on_b_id})
        assert denial is not None and "Source B" in denial["message"]


# ---------------------------------------------------------------------------
# agent_scope_denied_tool_calls() -- mirrors role_denied_tool_calls()'s own
# direct-call tests in test_agent_role_gate.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scope_denied_tool_calls_mutates_in_place_and_returns_denied(client):
    _, tenant_id, _ = await _register(client)
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[source_a])

    calls = [
        {"name": "sync_source", "args": {"source_id": source_a}, "id": "c1"},  # in scope
        {"name": "sync_source", "args": {"source_id": source_b}, "id": "c2"},  # out of scope
    ]
    denied = await agent_scope_denied_tool_calls(agent_id, calls)
    assert [c["id"] for c in denied] == ["c2"]
    assert [c["id"] for c in calls] == ["c1"], "denied call must be removed from the list in place"
    assert "isn't scoped" in denied[0]["reason"]


@pytest.mark.asyncio
async def test_scope_denied_tool_calls_with_none_agent_id_denies_nothing(client):
    calls = [{"name": "sync_source", "args": {"source_id": "whatever"}, "id": "c1"}]
    denied = await agent_scope_denied_tool_calls(None, calls)
    assert denied == []
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# (a) High-role caller, narrow-scope agent -> denied by SCOPE, not role.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_owner_with_narrow_scope_agent_denied_by_scope_not_role(client):
    _, tenant_id, user_id = await _register(client)
    await _set_role(user_id, "owner")
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    agent_id = await _make_agent(tenant_id, name="Nova", scoped_source_ids=[source_a])

    calls = [{"name": "sync_source", "args": {"source_id": source_b}, "id": "c1"}]

    # Role gate alone: Owner can do anything -- must NOT be the thing that denies this.
    role_denied = role_denied_tool_calls("owner", list(calls))
    assert role_denied == [], "an Owner must never be denied by the role gate itself"

    # Scope gate: must deny, and the reason must name the agent/source, not role.
    scope_denied = await agent_scope_denied_tool_calls(agent_id, list(calls))
    assert len(scope_denied) == 1
    assert "Nova" in scope_denied[0]["reason"]
    assert "Source B" in scope_denied[0]["reason"]
    assert "role" not in scope_denied[0]["reason"].lower()


# ---------------------------------------------------------------------------
# (b) Low-role caller, broad-scope agent -> still denied by ROLE.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b_viewer_with_broad_scope_agent_still_denied_by_role(client):
    _, tenant_id, user_id = await _register(client)
    await _set_role(user_id, "viewer")
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    # Broad scope: this agent can reach EVERY source in the tenant.
    agent_id = await _make_agent(tenant_id, name="BroadBot", scoped_source_ids=[source_a, source_b])

    calls = [{"name": "sync_source", "args": {"source_id": source_a}, "id": "c1"}]

    # Scope gate alone: fully in scope, must NOT deny.
    scope_denied = await agent_scope_denied_tool_calls(agent_id, list(calls))
    assert scope_denied == [], "a fully in-scope call must never be denied by the scope gate itself"

    # Role gate: Viewer lacks sources.profile -- must deny regardless of scope.
    role_denied = role_denied_tool_calls("viewer", list(calls))
    assert len(role_denied) == 1
    assert "role" in role_denied[0]["reason"].lower()


# ---------------------------------------------------------------------------
# Both gates composed through the real chat endpoint (both real consumers,
# same spirit as test_viewer_blocked_from_pipeline_trigger_both_consumers).
# ---------------------------------------------------------------------------

class FakeToolCallLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self._responses.pop(0)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_a_scope_denial_surfaces_through_real_chat(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "scopechatA")
    await _set_role(user_id, "owner")
    source_a = await _make_source(tenant_id, "Warehouse")
    source_b = await _make_source(tenant_id, "CRM Export")

    # This tenant's real AXIOM row (created by create_new_tenant_and_user)
    # is what chat.py actually resolves and passes as agent_id -- rename
    # it to Nova and narrow ITS scope, so the real chat path exercises the
    # exact agent chat.py will pick (oldest ACTIVE agent for the tenant).
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.tenant_id == tenant_id).order_by(AgentInstance.created_at.asc()))
        real_agent = r.scalars().first()
        real_agent.name = "Nova"
        db.add(AgentSource(id=str(uuid.uuid4()), agent_id=real_agent.id, source_id=source_a))
        await db.commit()

    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "sync_source", "args": {"source_id": source_b}, "id": "call_1"},
        ]),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    r = await client.post("/api/v1/chat/", json={"message": "sync the CRM Export source"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["status"] == "denied_out_of_scope"
    assert "Nova" in call["reason"]
    assert "CRM Export" in call["reason"]


@pytest.mark.asyncio
async def test_b_role_denial_still_fires_through_real_chat_for_a_broad_scope_agent(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "scopechatB")
    await _set_role(user_id, "viewer")
    source_a = await _make_source(tenant_id, "Warehouse")

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance).where(AgentInstance.tenant_id == tenant_id).order_by(AgentInstance.created_at.asc()))
        real_agent = r.scalars().first()
        db.add(AgentSource(id=str(uuid.uuid4()), agent_id=real_agent.id, source_id=source_a))
        await db.commit()

    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "sync_source", "args": {"source_id": source_a}, "id": "call_1"},
        ]),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    r = await client.post("/api/v1/chat/", json={"message": "sync the warehouse"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["status"] == "denied_insufficient_role"
