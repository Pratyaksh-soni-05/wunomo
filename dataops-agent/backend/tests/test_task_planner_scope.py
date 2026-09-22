"""Wunomo Projects Phase 1, part one: enforcement point 4 (plan generation).
Explicitly a COST OPTIMISATION, never the security boundary -- see
CLAUDE.md's rule and validate_step_plan_scope's own docstring. These tests
prove the cost-optimization behaves correctly (rejects what it can detect,
stays a no-op otherwise); test_task_scope_gate.py's own resolution-boundary
test proves the REAL guarantee lives elsewhere.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, AgentSource, DataSource,
    OperationMode, PersonalityMode, SourceType, TaskShape,
)
from modules.orchestration.task_planner import (
    PlanValidationError, _build_prompt, _in_scope_sources_for_prompt, validate_step_plan_scope,
)


async def _register(client, prefix="planscope"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Plan Scope Test",
        "tenant_name": f"Plan Scope Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()["tenant_id"]


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


@pytest.mark.asyncio
async def test_validate_step_plan_scope_is_a_noop_with_no_agent_id(client):
    steps = [{"tool_name": "sync_source", "tool_args": {"source_id": "anything"}}]
    async with AsyncSessionLocal() as db:
        await validate_step_plan_scope(db, None, steps)  # must not raise


@pytest.mark.asyncio
async def test_validate_step_plan_scope_allows_an_in_scope_reference(client):
    tenant_id = await _register(client, "planscopeA")
    source_a = await _make_source(tenant_id, "Source A")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[source_a])
    steps = [{"tool_name": "sync_source", "tool_args": {"source_id": source_a}}]
    async with AsyncSessionLocal() as db:
        await validate_step_plan_scope(db, agent_id, steps)  # must not raise


@pytest.mark.asyncio
async def test_validate_step_plan_scope_rejects_an_out_of_scope_reference(client):
    tenant_id = await _register(client, "planscopeB")
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    agent_id = await _make_agent(tenant_id, name="Nova", scoped_source_ids=[source_a])
    steps = [
        {"tool_name": "list_data_sources", "tool_args": {}},
        {"tool_name": "sync_source", "tool_args": {"source_id": source_b}},
    ]
    async with AsyncSessionLocal() as db:
        with pytest.raises(PlanValidationError, match="Step 1"):
            await validate_step_plan_scope(db, agent_id, steps)


@pytest.mark.asyncio
async def test_validate_step_plan_scope_is_a_noop_for_unresolved_placeholders(client):
    """The cost optimisation's real limit, stated plainly: a step whose
    arg is still a planner placeholder (not a real id) has nothing
    concrete to check -- this must never be treated as a violation just
    because it isn't a known-good id either."""
    tenant_id = await _register(client, "planscopeC")
    source_a = await _make_source(tenant_id, "Source A")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[source_a])
    steps = [{"tool_name": "sync_source", "tool_args": {"source_id": "sales_orders_source_id_placeholder"}}]
    async with AsyncSessionLocal() as db:
        await validate_step_plan_scope(db, agent_id, steps)  # must not raise


@pytest.mark.asyncio
async def test_in_scope_sources_for_prompt_none_agent_id_returns_none(client):
    assert await _in_scope_sources_for_prompt(None) is None


@pytest.mark.asyncio
async def test_in_scope_sources_for_prompt_lists_real_scoped_sources(client):
    tenant_id = await _register(client, "planscopeD")
    source_a = await _make_source(tenant_id, "Warehouse")
    source_b = await _make_source(tenant_id, "CRM")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[source_a, source_b])

    result = await _in_scope_sources_for_prompt(agent_id)
    names = {s["name"] for s in result}
    assert names == {"Warehouse", "CRM"}


@pytest.mark.asyncio
async def test_in_scope_sources_for_prompt_empty_list_for_a_real_unscoped_agent(client):
    tenant_id = await _register(client, "planscopeE")
    agent_id = await _make_agent(tenant_id, scoped_source_ids=[])
    result = await _in_scope_sources_for_prompt(agent_id)
    assert result == []


def test_build_prompt_lists_in_scope_sources_by_name():
    prompt = _build_prompt(
        "sync my data", TaskShape.SYNC_PROFILE_QUALITY,
        in_scope_sources=[{"id": "s1", "name": "Warehouse"}],
    )
    assert "Warehouse" in prompt
    assert "assigned data sources" in prompt


def test_build_prompt_says_no_sources_assigned_for_an_empty_real_scope():
    prompt = _build_prompt("sync my data", TaskShape.SYNC_PROFILE_QUALITY, in_scope_sources=[])
    assert "NO data sources assigned" in prompt


def test_build_prompt_says_nothing_extra_with_no_agent_context():
    prompt = _build_prompt("sync my data", TaskShape.SYNC_PROFILE_QUALITY, in_scope_sources=None)
    assert "assigned data sources" not in prompt
    assert "NO data sources assigned" not in prompt
