"""Regression tests for the get_agent() cache re-keying fix (Phase 16).
See CLAUDE.md's get_agent() Gotcha: the module-level _cache dict used to be
keyed only by "{personality}:{operation}", which would silently leak one
tenant's AI model override into another tenant's cached agent once
per-tenant model selection shipped. This is the explicit cross-tenant test
that Gotcha said must exist before Phase 16 could be considered done."""
import uuid
import pytest

import agent.dataops_agent as dataops_agent
from agent.dataops_agent import get_agent
from services.settings_service import get_ai_model_override
from database import AsyncSessionLocal
from models.all_models import Tenant
from sqlalchemy import select
from tests.test_agent_graph import FakeToolCallLLM, fake_echo_tool, _tool_call_then_final_responses


def test_get_agent_requires_tenant_id():
    with pytest.raises(ValueError, match="tenant_id"):
        get_agent("engineer", "assisted")


def test_get_agent_reuses_cache_for_repeated_calls_same_tenant():
    dataops_agent._cache.clear()
    a1 = get_agent("engineer", "assisted", tenant_id="tenant-a")
    a2 = get_agent("engineer", "assisted", tenant_id="tenant-a")
    assert a1 is a2


def test_get_agent_caches_separately_per_tenant_even_with_identical_args():
    dataops_agent._cache.clear()
    a1 = get_agent("engineer", "assisted", tenant_id="tenant-a")
    a2 = get_agent("engineer", "assisted", tenant_id="tenant-b")
    assert a1 is not a2


def test_get_agent_caches_separately_per_model_override_same_tenant():
    """The core of the fix: the SAME tenant asking for two different model
    overrides must get two different cached agent objects, not the first
    one built silently reused for the second (which would mean the second
    request's model choice was ignored)."""
    dataops_agent._cache.clear()
    a1 = get_agent("engineer", "assisted", tenant_id="tenant-a", primary_model="gemini-3.5-flash")
    a2 = get_agent("engineer", "assisted", tenant_id="tenant-a", primary_model="llama-3.3-70b-versatile")
    assert a1 is not a2


def test_get_agent_cross_tenant_isolation_with_different_model_overrides():
    """The exact scenario the Gotcha named: two tenants with DIFFERENT
    model preferences must each get their own cached agent - a cross-
    tenant cache hit would mean tenant B silently inherits tenant A's
    model choice (or vice versa)."""
    dataops_agent._cache.clear()
    tenant_a_agent = get_agent("engineer", "assisted", tenant_id="tenant-a", primary_model="gemini-3.5-flash")
    tenant_b_agent = get_agent("engineer", "assisted", tenant_id="tenant-b", primary_model="llama-3.3-70b-versatile")
    assert tenant_a_agent is not tenant_b_agent

    # Confirm repeat calls for each tenant hit their OWN cache entry, not
    # each other's.
    tenant_a_again = get_agent("engineer", "assisted", tenant_id="tenant-a", primary_model="gemini-3.5-flash")
    tenant_b_again = get_agent("engineer", "assisted", tenant_id="tenant-b", primary_model="llama-3.3-70b-versatile")
    assert tenant_a_again is tenant_a_agent
    assert tenant_b_again is tenant_b_agent


async def _register_tenant(client, prefix="modelovr"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Model Override Test", "tenant_name": f"Model Override Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()["tenant_id"]


@pytest.mark.asyncio
async def test_get_ai_model_override_unset_returns_none(client):
    tenant_id = await _register_tenant(client)
    assert await get_ai_model_override(tenant_id) is None


@pytest.mark.asyncio
async def test_run_agent_threads_the_resolved_override_through_to_the_llm_layer(client, monkeypatch):
    """Proves run_agent() -> get_agent() -> build_agent() -> get_llm_for_agent()
    genuinely carries a tenant's real, DB-stored override end to end -
    without spending a real LLM call. The real live-chat-request proof
    (against the actual running server) is done separately, live, per the
    phase's verification gate - this is the fast, repeatable version of
    the same assertion."""
    dataops_agent._cache.clear()
    tenant_id = await _register_tenant(client)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalar_one()
        tenant.settings = {"ai_model_override": "llama-3.3-70b-versatile"}
        await db.commit()

    captured_calls = []

    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        captured_calls.append(primary_model)
        return FakeToolCallLLM(_tool_call_then_final_responses())

    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_echo_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)

    await dataops_agent.run_agent(
        user_message="please echo hi", tenant_id=tenant_id, user_id="u1", session_id="s1", caller_role="owner",
    )

    assert captured_calls == ["llama-3.3-70b-versatile"]


@pytest.mark.asyncio
async def test_run_agent_two_tenants_different_overrides_do_not_cross_contaminate(client, monkeypatch):
    """The full cross-tenant scenario through the real run_agent() entry
    point, not just get_agent() in isolation: tenant A's override must
    never be the one used for tenant B's request, and vice versa."""
    dataops_agent._cache.clear()
    tenant_a = await _register_tenant(client, "crossa")
    tenant_b = await _register_tenant(client, "crossb")

    async with AsyncSessionLocal() as db:
        ra = await db.execute(select(Tenant).where(Tenant.id == tenant_a))
        ta = ra.scalar_one()
        ta.settings = {"ai_model_override": "gemini-3.5-flash"}
        rb = await db.execute(select(Tenant).where(Tenant.id == tenant_b))
        tb = rb.scalar_one()
        tb.settings = {"ai_model_override": "llama-3.3-70b-versatile"}
        await db.commit()

    captured_calls = []

    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        captured_calls.append(primary_model)
        return FakeToolCallLLM(_tool_call_then_final_responses())

    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_echo_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)

    await dataops_agent.run_agent(user_message="hi", tenant_id=tenant_a, user_id="ua", session_id="sa", caller_role="owner")
    await dataops_agent.run_agent(user_message="hi", tenant_id=tenant_b, user_id="ub", session_id="sb", caller_role="owner")

    assert captured_calls == ["gemini-3.5-flash", "llama-3.3-70b-versatile"]


@pytest.mark.asyncio
async def test_get_ai_model_override_returns_valid_override(client):
    tenant_id = await _register_tenant(client)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalar_one()
        tenant.settings = {"ai_model_override": "llama-3.3-70b-versatile"}
        await db.commit()

    assert await get_ai_model_override(tenant_id) == "llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_get_ai_model_override_rejects_unsupported_model(client):
    """The allowlist enforcement - an unsupported model name must not be
    silently used, must not crash, and must resolve to None (use the
    global default) rather than a value that would degrade chat."""
    tenant_id = await _register_tenant(client)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalar_one()
        tenant.settings = {"ai_model_override": "gpt-4-not-a-real-supported-model"}
        await db.commit()

    assert await get_ai_model_override(tenant_id) is None
