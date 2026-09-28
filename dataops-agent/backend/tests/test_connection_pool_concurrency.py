"""Repro/regression coverage for the connection-pool exhaustion fix
(database.py, GOTCHAS.md "Connection-pool exhaustion", 2026-09-27) --
targeted at the two live code paths that fan out real concurrent
AsyncSessionLocal() usage without any request/response cycle bounding them:

  - modules/orchestration/supervisor.py's _run_ready_wave: one
    asyncio.gather over every ready task in a wave, each _run_one_task()
    opening several of its own sessions.
  - api/v1/chat.py's chat_stream(): a bare asyncio.create_task(...) per
    request, deliberately NOT a child of the request's cancellation scope
    (_run_agent_and_persist_stream's own docstring) -- a burst of
    concurrent requests fires a burst of independent detached tasks with
    nothing bounding how many run at once.

The pool_size/max_overflow fix in database.py doesn't apply under
APP_ENV=test (NullPool -- see database.py's own comment), so this cannot
assert against a pool ceiling directly. What it CAN and does assert: a
burst of concurrent activity through both paths leaves no connection
behind in `idle in transaction` -- the exact symptom a session that
opened a transaction and never committed/rolled-back/closed produces, and
the shape found empirically (94 such connections) during Pratyaksh's
setup session. NullPool makes this a strong check, not a weak one: every
checkout is a real, unpooled physical connection, so a leak is not masked
by pool reuse -- it just sits there.

Counts are asserted as a before/after DELTA, not an absolute (there is no
guarantee some other fixture/session-scoped connection isn't already
idle-in-transaction for an unrelated reason) -- the same before/after
diffing discipline conftest.py's own tenant-cleanup fixture already uses.
"""
import asyncio
import uuid

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, text

import agent.dataops_agent as dataops_agent
from config import settings
from models.all_models import AgentEmployeeType, AgentInstanceStatus, Channel, ChannelAgent, AgentInstance, OperationMode, PersonalityMode, Task, TaskStatus
from modules.orchestration.supervisor import MAX_DAG_TASKS, run_supervisor
from services.tenant_context import tenant_session


class FakeToolCallLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self._responses.pop(0)


def _count_idle_in_transaction() -> int:
    """Real connections, as Postgres itself sees them -- via
    ADMIN_DATABASE_URL, the same role/mechanism conftest.py's cleanup
    fixture uses, never the application's own dataops_app pool (asking the
    pool about itself couldn't see a connection that leaked past it)."""
    admin = create_engine(settings.ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            return c.execute(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE usename = 'dataops_app' AND state = 'idle in transaction'"
            )).scalar_one()
    finally:
        admin.dispose()


async def _register(client, prefix="poolburst"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Pool Burst Tester",
        "tenant_name": f"Pool Burst Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _make_agent(tenant_id: str, name: str, model: str) -> str:
    async with tenant_session(tenant_id) as db:
        agent = AgentInstance(
            tenant_id=tenant_id, name=name, employee_type=AgentEmployeeType.DATAOPS,
            personality=PersonalityMode.ENGINEER, operation_mode=OperationMode.ASSISTED,
            model=model, status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        await db.commit()
        return agent.id


async def _make_channel_with_agents(tenant_id: str, agent_ids: list[str]) -> str:
    async with tenant_session(tenant_id) as db:
        channel = Channel(tenant_id=tenant_id, name=f"pool-burst-{uuid.uuid4().hex[:6]}")
        db.add(channel)
        await db.flush()
        for agent_id in agent_ids:
            db.add(ChannelAgent(channel_id=channel.id, agent_id=agent_id))
        await db.commit()
        return channel.id


@pytest.mark.asyncio
async def test_supervisor_gather_wave_at_dag_ceiling_leaves_no_leaked_connection(client, monkeypatch):
    """MAX_DAG_TASKS fully independent agents, one message, one
    asyncio.gather wave (_run_ready_wave) -- the real concurrency ceiling
    this code path can produce in a single request. None reference any
    other agent by name, so plan_node's fast path resolves all of them
    with zero LLM calls (no dependency-planner mock needed) and every
    task lands in the same first-and-only wave, exactly like
    test_message_with_no_dependency_runs_both_tasks_in_parallen in
    test_supervisor.py, just scaled to the real ceiling instead of 2."""
    token, tenant_id, user_id = await _register(client, "poolburstsup")
    agent_ids = []
    by_model = {}
    for i in range(MAX_DAG_TASKS):
        model = f"model-poolburst-{i}"
        agent_ids.append(await _make_agent(tenant_id, f"Agent{i}", model))
        by_model[model] = FakeToolCallLLM([AIMessage(content=f"Answer {i}.")])
    channel_id = await _make_channel_with_agents(tenant_id, agent_ids)

    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        return by_model[primary_model]
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    message = " ".join(f"@Agent{i} do independent thing {i}." for i in range(MAX_DAG_TASKS))

    idle_before = _count_idle_in_transaction()

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message=message,
    )

    assert result["error"] is None
    assert len(result["tasks"]) == MAX_DAG_TASKS
    # All MAX_DAG_TASKS completed in the SAME wave -- proof this actually
    # went through one asyncio.gather call, not MAX_DAG_TASKS sequential
    # ones.
    assert set(result["completed_this_wave"]) == {t["task_id"] for t in result["tasks"]}

    async with tenant_session(tenant_id) as db:
        for t in result["tasks"]:
            task = await db.get(Task, t["task_id"])
            assert task.status == TaskStatus.COMPLETED

    idle_after = _count_idle_in_transaction()
    assert idle_after <= idle_before, (
        f"supervisor's asyncio.gather wave left {idle_after - idle_before} new "
        f"idle-in-transaction connection(s) behind after {MAX_DAG_TASKS} concurrent tasks"
    )


@pytest.mark.asyncio
async def test_concurrent_chat_stream_bursts_leave_no_leaked_connection(client, monkeypatch):
    """N separate tenants each POST /api/v1/chat/stream at the same time --
    N independent, detached asyncio.create_task(_run_agent_and_persist_stream)
    calls in flight concurrently, none of them a child of any request's
    cancellation scope (see that function's own docstring). Each stream is
    drained fully (to its `done`/_STREAM_DONE frame) so the detached task
    is confirmed to have run to completion, not just been scheduled."""
    N = 6

    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        return FakeToolCallLLM([AIMessage(content="Burst answer.")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    tenants = [await _register(client, f"poolburstchat{i}") for i in range(N)]

    async def _run_one_stream(token):
        chunks = []
        async with client.stream(
            "POST", "/api/v1/chat/stream", json={"message": "burst message"},
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            assert response.status_code == 200
            async for chunk in response.aiter_text():
                chunks.append(chunk)
        return "".join(chunks)

    idle_before = _count_idle_in_transaction()

    bodies = await asyncio.gather(*[_run_one_stream(token) for token, _tid, _uid in tenants])

    for body in bodies:
        assert "event: done" in body

    idle_after = _count_idle_in_transaction()
    assert idle_after <= idle_before, (
        f"{N} concurrent chat_stream detached tasks left {idle_after - idle_before} new "
        f"idle-in-transaction connection(s) behind"
    )
