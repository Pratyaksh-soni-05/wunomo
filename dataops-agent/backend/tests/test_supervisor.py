"""Stage 2, part 1 (multi-agent supervisor) -- headless acceptance and
failure-semantics tests for modules/orchestration/supervisor.py. Nothing
here goes through any HTTP route; run_supervisor()/retry_task() are called
directly, matching the "no UI, no route wiring yet" scope of this pass.

Written BEFORE the implementation existed, per the blueprint's own
requirement that the acceptance test gate the work -- see
test_acceptance_* below.

AgentEmployeeType has exactly one real value (DATAOPS) today, by
deliberate, documented design (models/all_models.py: "extend this the day
a second employee type actually ships, not before"). The acceptance
test's literal "two agents of different employee_type" therefore cannot
be constructed without violating that existing design decision -- these
tests use two distinct AgentInstance rows (same employee_type, different
names/models) instead, the closest faithful approximation available.

DEPENDENCY PLANNER TESTING STRATEGY: most tests below monkeypatch
supervisor.infer_dependencies() directly, returning a pre-built,
already-validated plan -- they're testing plan_node's OWN branching
(apply/ask/refuse) given a certain planner outcome, not the LLM
prompt/JSON-parsing mechanics. test_infer_dependencies_retries_once_on_
malformed_json_then_succeeds and test_infer_dependencies_raises_after_
exhausting_retries exercise that layer directly, end to end, by mocking
invoke_llm() with raw text instead.

FAST PATH: plan_node now runs a deterministic possessive-reference check
before ever considering the LLM (_references_agent_output) -- any test
whose message already contains "X's ..." resolves entirely via that fast
path and never reaches infer_dependencies at all, regardless of what
_patch_dependency_planner below is set up to return; that mock is simply
never invoked in those cases (the acceptance test asserts this
explicitly). Only a message with a genuine paraphrase -- a bare mention
of another agent's name with no possessive -- reaches the LLM.
"""
import json
import uuid

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

import agent.dataops_agent as dataops_agent
import modules.orchestration.supervisor as supervisor
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, Channel, ChannelAgent, Handoff,
    OperationMode, PersonalityMode, Task, TaskShape, TaskStatus, TaskStep, TaskStepStatus,
)
from models.approval_model import ApprovalRequest
from modules.orchestration.supervisor import (
    MAX_DAG_TASKS, DependencyPlanningError, infer_dependencies, parse_all_mentions, retry_task, run_supervisor,
)
from services.tenant_context import async_tenant_context, tenant_session


async def _register(client, prefix="supervisor"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Supervisor Tester",
        "tenant_name": f"Supervisor Corp {uuid.uuid4().hex[:6]}",
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
        channel = Channel(tenant_id=tenant_id, name=f"general-{uuid.uuid4().hex[:6]}")
        db.add(channel)
        await db.flush()
        for agent_id in agent_ids:
            db.add(ChannelAgent(channel_id=channel.id, agent_id=agent_id))
        await db.commit()
        return channel.id


class FakeToolCallLLM:
    """Same shape every other test in this suite already uses -- bind_tools()
    is a no-op, ainvoke() replays (or raises) a scripted response."""

    def __init__(self, responses=None, raises: Exception | None = None):
        self._responses = list(responses or [])
        self._raises = raises

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if self._raises is not None:
            raise self._raises
        return self._responses.pop(0)


def _patch_llms(monkeypatch, by_model: dict[str, "FakeToolCallLLM"]):
    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        if primary_model not in by_model:
            raise AssertionError(f"no fake LLM configured for model {primary_model!r}")
        return by_model[primary_model]
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()


def _dep(agent: str, depends_on: list[str] | None = None, confidence: str | None = None, reason: str | None = None) -> dict:
    """One entry in the shape infer_dependencies()/_validate_dependency_plan()
    already returns -- used to build a fake planner response without going
    through the LLM/JSON layer."""
    return {"agent": agent, "depends_on": depends_on or [], "confidence": confidence, "reason": reason}


def _patch_dependency_planner(monkeypatch, plan: list[dict], calls: list | None = None):
    """Mocks supervisor.infer_dependencies() directly, bypassing the LLM
    call entirely -- deterministic and fast, the same reason every other
    test in this suite fakes get_llm_for_agent() rather than hitting a
    real model. `plan` may cover more agents than plan_node ever actually
    asks about (its own fast path resolves some intents without ever
    calling this) -- only entries matching `pending_intents` are
    returned, mirroring infer_dependencies' real contract. Pass `calls`
    (a list) to record each invocation's pending agent names, for tests
    that assert whether -- and for whom -- the LLM was actually called."""
    async def fake_infer_dependencies(*, tenant_id, user_id, message, intents, pending_intents=None):
        names = {p["agent_name"] for p in (pending_intents or intents)}
        if calls is not None:
            calls.append(sorted(names))
        return [p for p in plan if p["agent"] in names]
    monkeypatch.setattr(supervisor, "infer_dependencies", fake_infer_dependencies)


async def _get_task(tenant_id: str, task_id: str) -> Task:
    async with tenant_session(tenant_id) as db:
        return await db.get(Task, task_id)


async def _get_step(tenant_id: str, task_id: str) -> TaskStep:
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        return r.scalars().first()


# ---------------------------------------------------------------------
# parse_all_mentions -- pure function, no DB, unaffected by the LLM planner
# ---------------------------------------------------------------------

def test_parse_all_mentions_splits_the_acceptance_test_message():
    result = parse_all_mentions("@a summarise this file, then @b count the rows in a's summary.")
    assert result == [
        ("a", "summarise this file, then"),
        ("b", "count the rows in a's summary."),
    ]


def test_parse_all_mentions_ignores_a_mention_with_nothing_after_it():
    result = parse_all_mentions("@a")
    assert result == [("a", "")]


# ---------------------------------------------------------------------
# The acceptance test (Task 4) -- written to gate this work, per the spec.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acceptance_two_agent_chain_success(client, monkeypatch):
    """Given a channel with two agents, one message addressing both with
    an explicit dependency ("Nova's summary") in the second instruction:
    two Task rows, B queued behind A rather than started, exactly one
    Handoff row linking them, B's input containing A's output, and both
    reaching COMPLETED in the right order.

    The dependency here is a possessive back-reference ("Nova's
    summary"), so plan_node's deterministic fast path resolves it (and
    Nova's own lack of any dependency) without ever consulting the LLM --
    this is the fast-path optimization's own acceptance case: the planner
    mock is wired up but must never actually be invoked."""
    token, tenant_id, user_id = await _register(client, "acceptok")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    _patch_llms(monkeypatch, {
        "model-nova": FakeToolCallLLM([AIMessage(content="Summary: 3 widgets, 5 gadgets, 2 gizmos.")]),
        "model-ravi": FakeToolCallLLM([AIMessage(content="There are 3 numbers in that summary.")]),
    })
    calls: list = []
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi", depends_on=["Nova"], confidence="high", reason="Ravi needs Nova's summary to count rows"),
    ], calls=calls)

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova summarise this file, then @Ravi count the rows in Nova's summary.",
    )

    assert calls == []  # the possessive fast path resolves this entirely -- zero LLM calls
    assert result["error"] is None
    assert result["needs_clarification"] is None
    assert len(result["tasks"]) == 2
    task_a_id = result["tasks"][0]["task_id"]
    task_b_id = result["tasks"][1]["task_id"]

    # The dependency was inferred, not stated as a structured edge by the
    # user -- it must be surfaced, never silently applied.
    assert len(result["inferred_edge_notices"]) == 1
    assert "Ravi" in result["inferred_edge_notices"][0] and "Nova" in result["inferred_edge_notices"][0]

    task_a = await _get_task(tenant_id, task_a_id)
    task_b = await _get_task(tenant_id, task_b_id)
    assert task_a.task_shape == TaskShape.SUPERVISOR_INTENT
    assert task_b.depends_on_task_id == task_a.id
    assert task_a.status == TaskStatus.COMPLETED
    assert task_b.status == TaskStatus.COMPLETED

    # Exactly one Handoff row, linking A -> B.
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Handoff).where(
            Handoff.from_task_id == task_a.id, Handoff.to_task_id == task_b.id,
        ))
        handoffs = r.scalars().all()
    assert len(handoffs) == 1
    assert handoffs[0].from_agent_id == agent_a
    assert handoffs[0].to_agent_id == agent_b
    assert handoffs[0].withheld == []

    # B's real input (the message run_agent() was called with) must
    # contain A's actual output text, not just a Handoff row existing.
    step_b = await _get_step(tenant_id, task_b_id)
    assert "3 widgets, 5 gadgets, 2 gizmos" in task_b.goal


@pytest.mark.asyncio
async def test_acceptance_upstream_failure_blocks_dependent_then_retry_releases_it(client, monkeypatch):
    """Same two-agent chain, A forced to fail: B lands in BLOCKED_ON_
    DEPENDENCY naming the upstream task, never FAILED itself. Retrying A
    then releases B, which completes with A's (retried) real output.
    retry_task() never re-invokes the planner -- it operates on already-
    dispatched Task rows -- so this test only needs to mock the planner
    once, for the initial run_supervisor() call."""
    token, tenant_id, user_id = await _register(client, "acceptfail")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-fail")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-fail")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    _patch_llms(monkeypatch, {
        "model-nova-fail": FakeToolCallLLM(raises=RuntimeError("Nova's model timed out")),
        "model-ravi-fail": FakeToolCallLLM([AIMessage(content="unreachable -- B must never run while blocked")]),
    })
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi", depends_on=["Nova"], confidence="high", reason="needs Nova's summary"),
    ])

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova summarise this file, then @Ravi count the rows in Nova's summary.",
    )

    task_a_id = result["tasks"][0]["task_id"]
    task_b_id = result["tasks"][1]["task_id"]
    task_a = await _get_task(tenant_id, task_a_id)
    task_b = await _get_task(tenant_id, task_b_id)

    assert task_a.status == TaskStatus.FAILED
    assert task_b.status == TaskStatus.BLOCKED_ON_DEPENDENCY
    assert task_a_id in task_b.termination_reason  # names the upstream task, per the spec

    # No Handoff was ever written for a task that never completed.
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Handoff).where(Handoff.to_task_id == task_b_id))
        assert r.scalars().first() is None

    # Retrying A (this time it succeeds) releases B.
    _patch_llms(monkeypatch, {
        "model-nova-fail": FakeToolCallLLM([AIMessage(content="Retried summary: 7 rows total.")]),
        "model-ravi-fail": FakeToolCallLLM([AIMessage(content="7 rows counted, confirmed.")]),
    })

    async with async_tenant_context(tenant_id):
        retry_result = await retry_task(
            task_a_id, tenant_id=tenant_id, channel_id=channel_id, project_id=None,
            user_id=user_id, caller_role="owner",
        )

    assert task_b_id in retry_result["released_from_block"]
    task_a = await _get_task(tenant_id, task_a_id)
    task_b = await _get_task(tenant_id, task_b_id)
    assert task_a.status == TaskStatus.COMPLETED
    assert task_b.status == TaskStatus.COMPLETED
    assert "Retried summary: 7 rows total" in task_b.goal

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Handoff).where(
            Handoff.from_task_id == task_a_id, Handoff.to_task_id == task_b_id,
        ))
        assert r.scalars().first() is not None


# ---------------------------------------------------------------------
# Failure semantics (Task 3), each as its own focused test.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_needing_approval_holds_dependent_without_blocking_it(client, monkeypatch):
    """"A needs approval -> A holds, B holds behind it" -- B must NOT be
    BLOCKED_ON_DEPENDENCY (that's reserved for a genuine failure); it
    simply stays SUPERVISOR_QUEUED, not yet ready, until A resolves."""
    token, tenant_id, user_id = await _register(client, "acceptapproval")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-appr")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-appr")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        if primary_model == "model-nova-appr":
            return FakeToolCallLLM([AIMessage(content="", tool_calls=[
                {"name": "run_pipeline", "args": {"pipeline_id": "p1"}, "id": "call_1"},
            ])])
        return FakeToolCallLLM([AIMessage(content="unreachable while A holds")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    # Real ALL_TOOLS/TOOL_CAPABILITIES left untouched -- run_pipeline is a
    # genuinely registered tool, and "owner" has every capability, so this
    # exercises the real role gate, not a synthetic bypass of it.
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: True)
    dataops_agent._cache.clear()
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi", depends_on=["Nova"], confidence="high", reason="wants to hear about Nova's run"),
    ])

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova run the pipeline, then @Ravi tell me about Nova's run.",
    )

    task_a_id = result["tasks"][0]["task_id"]
    task_b_id = result["tasks"][1]["task_id"]
    task_a = await _get_task(tenant_id, task_a_id)
    task_b = await _get_task(tenant_id, task_b_id)

    assert task_a.status == TaskStatus.PAUSED_NEEDS_APPROVAL
    assert task_b.status == TaskStatus.SUPERVISOR_QUEUED  # holding, not blocked
    assert task_b.termination_reason is None

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.session_id == channel_id))
        approvals = r.scalars().all()
    assert len(approvals) == 1
    assert approvals[0].action_name == "run_pipeline"

    # The step this approval is blocking must be discoverable from the
    # approval alone (findings-98's own missing link) -- this is what lets
    # PolicyEngine.approve()/reject() find their way back to this task at
    # all, and what the Needs You screen's tier-0/tier-1 dedup now relies
    # on (needsYou.ts: linkedApprovalIds keys off current_step.
    # approval_request_id).
    async with async_tenant_context(tenant_id):
        found_task_id = await supervisor.find_supervisor_task_for_approval(approvals[0].id)
    assert found_task_id == task_a_id


async def _setup_paused_approval_chain(client, monkeypatch, prefix: str):
    """Shared setup for the two resolve_task_approval() tests below: a
    two-agent chain (Ravi depends on Nova) where Nova's own turn trips a
    real approval gate and pauses -- same shape
    test_task_needing_approval_holds_dependent_without_blocking_it already
    builds and proves, factored out so approve/reject can each pick up
    from the identical starting point."""
    token, tenant_id, user_id = await _register(client, prefix)
    agent_a = await _make_agent(tenant_id, "Nova", f"model-nova-{prefix}")
    agent_b = await _make_agent(tenant_id, "Ravi", f"model-ravi-{prefix}")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    def fake_get_llm_for_agent(temperature=0.0, primary_model=None):
        if primary_model == f"model-nova-{prefix}":
            return FakeToolCallLLM([AIMessage(content="", tool_calls=[
                {"name": "run_pipeline", "args": {"pipeline_id": "p1"}, "id": "call_1"},
            ])])
        return FakeToolCallLLM([AIMessage(content="Ravi ran after Nova resolved.")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", fake_get_llm_for_agent)
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: True)
    dataops_agent._cache.clear()
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi", depends_on=["Nova"], confidence="high", reason="wants to hear about Nova's run"),
    ])

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova run the pipeline, then @Ravi tell me about Nova's run.",
    )
    task_a_id = result["tasks"][0]["task_id"]
    task_b_id = result["tasks"][1]["task_id"]
    step_a = await _get_step(tenant_id, task_a_id)
    assert (await _get_task(tenant_id, task_a_id)).status == TaskStatus.PAUSED_NEEDS_APPROVAL
    assert step_a.approval_request_id is not None

    return {
        "tenant_id": tenant_id, "user_id": user_id, "channel_id": channel_id,
        "task_a_id": task_a_id, "task_b_id": task_b_id, "approval_id": step_a.approval_request_id,
    }


@pytest.mark.asyncio
async def test_approving_a_paused_supervisor_task_releases_its_dependent(client, monkeypatch):
    """The correctness bug, live-discovered: a task queued behind an
    approval-paused task never resumed once a human approved it. Approving
    now completes the paused task for real (its step carries the actual
    execution_result) and reuses retry_task()'s own wave-draining core
    (_drain_ready_waves) to release Ravi -- not a second scheduling
    mechanism."""
    ctx = await _setup_paused_approval_chain(client, monkeypatch, "approverelease")

    # Simulates what PolicyEngine.approve() has already done by the time it
    # calls resolve_task_approval() -- persisted the real execution_result
    # on the ApprovalRequest row. Tested at this level (not through a real
    # DAGManager.trigger_run() call against a pipeline that doesn't exist)
    # so this test verifies resolve_task_approval()'s own state-transition
    # logic precisely, the same way this file already tests supervisor.py's
    # other internals directly rather than only through HTTP.
    async with tenant_session(ctx["tenant_id"]) as db:
        approval = await db.get(ApprovalRequest, ctx["approval_id"])
        approval.execution_result = {"status": "triggered", "run_id": "run_123"}
        await db.commit()

    async with async_tenant_context(ctx["tenant_id"]):
        resolve_result = await supervisor.resolve_task_approval(ctx["task_a_id"], ctx["approval_id"], approved=True)
    assert resolve_result["outcome"] == "approved_and_completed"

    task_a = await _get_task(ctx["tenant_id"], ctx["task_a_id"])
    task_b = await _get_task(ctx["tenant_id"], ctx["task_b_id"])
    assert task_a.status == TaskStatus.COMPLETED
    assert task_b.status == TaskStatus.COMPLETED  # released AND run, not just released
    assert "Ravi ran after Nova resolved" in (await _get_step(ctx["tenant_id"], ctx["task_b_id"])).outcome_summary

    step_a = await _get_step(ctx["tenant_id"], ctx["task_a_id"])
    assert step_a.status == TaskStepStatus.SUCCEEDED
    assert "run_pipeline" in step_a.outcome_summary
    assert step_a.raw_result == {"status": "triggered", "run_id": "run_123"}

    # A real ChatMessage persisted for the approved task's own answer --
    # this never happened before (chat.py's old persistence loop only ever
    # read back result["tasks"] from the ORIGINAL run_supervisor() call,
    # which had already returned long before a human clicked approve).
    async with tenant_session(ctx["tenant_id"]) as db:
        from models.all_models import ChatMessage
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == ctx["channel_id"], ChatMessage.agent_id == task_a.agent_id,
            ChatMessage.role == "assistant",
        ))
        messages = r.scalars().all()
    assert any("run_pipeline" in m.content for m in messages)

    # And a real Handoff, exactly like the normal completion path writes.
    async with tenant_session(ctx["tenant_id"]) as db:
        r = await db.execute(select(Handoff).where(
            Handoff.from_task_id == ctx["task_a_id"], Handoff.to_task_id == ctx["task_b_id"],
        ))
        assert r.scalars().first() is not None


@pytest.mark.asyncio
async def test_rejecting_a_paused_supervisor_task_blocks_its_dependent(client, monkeypatch):
    """A rejection is a decision, not a pause -- Ravi must move to
    BLOCKED_ON_DEPENDENCY naming Nova and saying it was REJECTED
    specifically (not the generic "which failed" wording _block_dependents
    otherwise defaults to), never sit SUPERVISOR_QUEUED forever."""
    ctx = await _setup_paused_approval_chain(client, monkeypatch, "approvereject")

    async with async_tenant_context(ctx["tenant_id"]):
        resolve_result = await supervisor.resolve_task_approval(ctx["task_a_id"], ctx["approval_id"], approved=False)
    assert resolve_result["outcome"] == "rejected"
    assert ctx["task_b_id"] in resolve_result["blocked_dependents"]

    task_a = await _get_task(ctx["tenant_id"], ctx["task_a_id"])
    task_b = await _get_task(ctx["tenant_id"], ctx["task_b_id"])
    assert task_a.status == TaskStatus.FAILED
    assert task_a.termination_reason == "Approval rejected."
    assert task_b.status == TaskStatus.BLOCKED_ON_DEPENDENCY
    assert ctx["task_a_id"] in task_b.termination_reason
    assert "rejected" in task_b.termination_reason
    assert "failed" not in task_b.termination_reason  # must not reuse the generic-failure wording

    # No Handoff, no ChatMessage for the rejected task's non-answer.
    async with tenant_session(ctx["tenant_id"]) as db:
        r = await db.execute(select(Handoff).where(Handoff.from_task_id == ctx["task_a_id"]))
        assert r.scalars().first() is None


@pytest.mark.asyncio
async def test_circular_dependency_refuses_to_dispatch_with_zero_tasks_created(client, monkeypatch):
    """The planner itself proposes a 2-cycle (Nova needs Ravi, Ravi needs
    Nova) -- must refuse before creating any Task row at all, never
    deadlock two tasks that can each never become ready."""
    token, tenant_id, user_id = await _register(client, "acceptcycle")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-cycle")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-cycle")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova", depends_on=["Ravi"], confidence="high", reason="needs Ravi's file"),
        _dep("Ravi", depends_on=["Nova"], confidence="high", reason="needs Nova's file"),
    ])

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner",
        message="@Nova use Ravi's file to do X. @Ravi use Nova's file to do Y.",
    )

    assert result["error"] is not None
    assert "ircular" in result["error"]
    assert result["error_kind"] == "cycle"
    assert result["needs_clarification"] is None
    assert result["tasks"] == []

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Task).where(Task.tenant_id == tenant_id))
        assert r.scalars().first() is None


@pytest.mark.asyncio
async def test_fan_in_message_refuses_with_zero_tasks_created(client, monkeypatch):
    """The planner proposes a node needing BOTH other agents' output --
    this schema stores a single predecessor per task. Must refuse, not
    silently drop one edge or linearize an order nobody asked for."""
    token, tenant_id, user_id = await _register(client, "acceptfanin")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-fanin")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-fanin")
    agent_c = await _make_agent(tenant_id, "Priya", "model-priya-fanin")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b, agent_c])
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi"),
        _dep("Priya", depends_on=["Nova", "Ravi"], confidence="high",
             reason="needs both Nova's and Ravi's numbers to combine them"),
    ])

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner",
        message=(
            "@Nova gather sales numbers. @Ravi gather cost numbers. "
            "@Priya combine Nova's and Ravi's numbers into one report."
        ),
    )

    assert result["error"] is not None
    assert "Priya" in result["error"]
    assert result["error_kind"] == "fan_in"
    assert result["needs_clarification"] is None
    assert result["tasks"] == []

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Task).where(Task.tenant_id == tenant_id))
        assert r.scalars().first() is None


@pytest.mark.asyncio
async def test_agent_mentioned_but_not_on_channel_is_reported_without_failing_the_message(client, monkeypatch):
    """One resolvable mention, one that names a real tenant agent who
    simply isn't a member of this channel -- the resolvable intent must
    still dispatch and run; the whole message must not fail. Only one
    intent resolves, so plan_node never calls the planner at all (nothing
    to order) -- no LLM mock needed here."""
    token, tenant_id, user_id = await _register(client, "acceptmissing")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-missing")
    agent_c = await _make_agent(tenant_id, "Carlos", "model-carlos-missing")  # real, but never added to the channel
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a])  # Carlos deliberately excluded

    _patch_llms(monkeypatch, {"model-nova-missing": FakeToolCallLLM([AIMessage(content="Done, Nova here.")])})

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova say hello. @Carlos say hello too.",
    )

    assert result["error"] is None
    assert len(result["tasks"]) == 1  # only Nova's intent dispatched
    assert len(result["unresolved_mentions"]) == 1
    assert result["unresolved_mentions"][0]["name"] == "Carlos"
    assert "isn't a member" in result["unresolved_mentions"][0]["reason"]

    task_a = await _get_task(tenant_id, result["tasks"][0]["task_id"])
    assert task_a.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_dag_task_ceiling_refuses_an_oversized_fanout(client, monkeypatch):
    """A DAG-level ceiling, separate from Task.step_budget_max (which
    bounds steps WITHIN one task) -- one ambiguous message must not be
    able to fan out into an unbounded number of real Task rows. Checked
    BEFORE the planner is ever called -- no LLM mock needed here, and no
    LLM spend either."""
    token, tenant_id, user_id = await _register(client, "acceptceiling")
    agent_ids = [await _make_agent(tenant_id, f"Agent{i}", f"model-{i}") for i in range(MAX_DAG_TASKS + 2)]
    channel_id = await _make_channel_with_agents(tenant_id, agent_ids)

    message = " ".join(f"@Agent{i} do thing {i}." for i in range(MAX_DAG_TASKS + 2))
    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message=message,
    )

    assert result["error"] is not None
    assert str(MAX_DAG_TASKS) in result["error"]
    assert result["error_kind"] == "ceiling"
    assert result["tasks"] == []

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Task).where(Task.tenant_id == tenant_id))
        assert r.scalars().first() is None


@pytest.mark.asyncio
async def test_message_with_no_dependency_runs_both_tasks_in_parallel(client, monkeypatch):
    """Two intents with no relationship at all -- the planner correctly
    returns empty depends_on for both. Must NOT overcorrect into
    serialising everything: both dispatch as independent, immediately-
    ready tasks and run in the same wave (one asyncio.gather call), not
    one after the other."""
    token, tenant_id, user_id = await _register(client, "acceptindependent")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-indep")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-indep")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    _patch_llms(monkeypatch, {
        "model-nova-indep": FakeToolCallLLM([AIMessage(content="Nova's own unrelated answer.")]),
        "model-ravi-indep": FakeToolCallLLM([AIMessage(content="Ravi's own unrelated answer.")]),
    })
    _patch_dependency_planner(monkeypatch, [_dep("Nova"), _dep("Ravi")])

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova check the pipeline status. @Ravi check the incident queue.",
    )

    assert result["error"] is None
    assert result["needs_clarification"] is None
    assert result["inferred_edge_notices"] == []
    task_a = await _get_task(tenant_id, result["tasks"][0]["task_id"])
    task_b = await _get_task(tenant_id, result["tasks"][1]["task_id"])
    assert task_a.depends_on_task_id is None
    assert task_b.depends_on_task_id is None
    assert task_a.status == TaskStatus.COMPLETED
    assert task_b.status == TaskStatus.COMPLETED
    # Both ran in the very first (and only) wave -- neither waited on the
    # other. completed_this_wave on the final state reflects whatever the
    # LAST run_node pass completed; since nothing depended on anything,
    # there is exactly one pass and it contains both.
    assert set(result["completed_this_wave"]) == {task_a.id, task_b.id}


@pytest.mark.asyncio
async def test_llm_planner_catches_the_regression_case_the_old_regex_missed(client, monkeypatch):
    """THE regression test for this whole change. "count the rows using
    what Nova found" describes the identical dependency the acceptance
    test's "in Nova's summary" phrasing does, but has no possessive
    back-reference -- the old regex heuristic (_references_agent_output,
    now deleted) missed this case entirely (see this file's git history
    for the test that used to prove that gap: test_known_limitation_a_
    differently_phrased_dependency_is_not_inferred, which asserted NO
    edge was found). The LLM planner, given this exact input live against
    a real model, correctly returns Ravi depends_on=["Nova"], confidence
    "high", reason "Ravi needs Nova's summary to count rows" -- verified
    against the real Gemini/Groq backend before writing this fixture, not
    assumed. This test asserts plan_node acts correctly GIVEN that real,
    verified planner output."""
    token, tenant_id, user_id = await _register(client, "acceptregression")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-regression")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-regression")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    _patch_llms(monkeypatch, {
        "model-nova-regression": FakeToolCallLLM([AIMessage(content="Found 3 widgets.")]),
        "model-ravi-regression": FakeToolCallLLM([AIMessage(content="3 widgets counted, confirmed.")]),
    })
    calls: list = []
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi", depends_on=["Nova"], confidence="high", reason="Ravi needs Nova's summary to count rows"),
    ], calls=calls)

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner",
        message="@Nova summarise this file. @Ravi count the rows using what Nova found.",
    )

    # No possessive here ("what Nova found", not "Nova's") -- the fast
    # path can't resolve it, but Ravi's text still names Nova, so it's
    # sent to the LLM. Nova's own text names nobody, so it's never asked
    # about.
    assert calls == [["Ravi"]]
    assert result["error"] is None
    assert result["needs_clarification"] is None
    assert len(result["inferred_edge_notices"]) == 1  # now DOES surface, unlike the old regex
    task_a = await _get_task(tenant_id, result["tasks"][0]["task_id"])
    task_b = await _get_task(tenant_id, result["tasks"][1]["task_id"])
    assert task_b.depends_on_task_id == task_a.id
    assert task_a.status == TaskStatus.COMPLETED
    assert task_b.status == TaskStatus.COMPLETED
    # B's real input now DOES contain A's real output -- the exact gap the
    # regex left open.
    assert "Found 3 widgets" in task_b.goal


@pytest.mark.asyncio
async def test_ambiguous_message_triggers_ask_instead_of_a_guess(client, monkeypatch):
    """A genuinely ambiguous relationship -- the planner itself is only
    MEDIUM confidence. Must NOT dispatch on a guess: zero Task rows,
    needs_clarification populated naming both agents and offering a
    concrete choice, exactly the "ask once, cheap" behavior the spec
    requires over "a confident wrong answer."

    Ravi's text names Nova by bare mention (no possessive), which is
    exactly what makes it a fast-path CANDIDATE for the LLM (a silent
    intent would never reach the planner at all -- see _mentions_agent_
    name) without the fast path being able to resolve it outright."""
    token, tenant_id, user_id = await _register(client, "acceptambiguous")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-ambiguous")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-ambiguous")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])
    calls: list = []
    _patch_dependency_planner(monkeypatch, [
        _dep("Nova"),
        _dep("Ravi", depends_on=["Nova"], confidence="medium",
             reason="Ravi's 'second opinion' might be about Nova's finding, or might be independent"),
    ], calls=calls)

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner",
        message="@Nova look into the pipeline. @Ravi take a look at what Nova found too and give a second opinion.",
    )

    assert calls == [["Ravi"]]  # named Nova, but not possessively -- a real LLM candidate
    assert result["error"] is None
    assert result["tasks"] == []
    assert result["needs_clarification"] is not None
    assert len(result["needs_clarification"]) == 1
    ask = result["needs_clarification"][0]
    assert set(ask["agents"]) == {"Nova", "Ravi"}
    assert "Ravi" in ask["question"] and "Nova" in ask["question"]
    assert any("Wait for Nova" in o for o in ask["options"])
    assert any("independently" in o.lower() for o in ask["options"])

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Task).where(Task.tenant_id == tenant_id))
        assert r.scalars().first() is None


@pytest.mark.asyncio
async def test_planner_failure_degrades_to_asking_never_to_guessing(client, monkeypatch):
    """Requirement 5: a planner failure (LLM never produces a valid
    response, even through invoke_llm's own timeout-fallback wrapper and
    retries) must degrade to asking the user for the order -- never a
    silent "no dependency" guess, and never a hard error either (this
    isn't a structural refusal like a cycle or fan-in; it's "I don't
    know, please tell me").

    Since the fast-path optimization, this must ALSO prove partial
    dispatch: "regex-only behaviour plus a clarification prompt for the
    rest," never discarding an edge (or a confirmed non-edge) already
    known to be correct. Nova's intent doesn't mention Ravi anywhere, so
    the fast path already knows it's independent -- it dispatches and
    completes normally even though the planner call fails outright.
    Ravi's intent names Nova (no possessive), so it's the only one that
    needed the LLM, and the only one withheld when that call fails."""
    token, tenant_id, user_id = await _register(client, "acceptplannerfail")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-plannerfail")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-plannerfail")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b])

    _patch_llms(monkeypatch, {
        "model-nova-plannerfail": FakeToolCallLLM([AIMessage(content="Nova did something.")]),
        "model-ravi-plannerfail": FakeToolCallLLM([AIMessage(content="unreachable while withheld")]),
    })

    async def always_fails(*, tenant_id, user_id, message, intents, pending_intents=None):
        raise DependencyPlanningError("Failed to infer dependencies after 2 attempts: LLM call failed: boom")
    monkeypatch.setattr(supervisor, "infer_dependencies", always_fails)

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner", message="@Nova do something. @Ravi build on what Nova did.",
    )

    assert result["error"] is None  # not a hard refusal
    assert result["needs_clarification"] is not None
    assert result["needs_clarification"][0]["agents"] == ["Ravi"]  # only the intent the LLM was actually needed for

    # Nova's intent was resolved by the fast path (independent) and
    # dispatches/completes normally -- never discarded just because the
    # planner failed for a DIFFERENT intent.
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["agent_name"] == "Nova"
    nova_task = await _get_task(tenant_id, result["tasks"][0]["task_id"])
    assert nova_task.status == TaskStatus.COMPLETED

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Task).where(Task.tenant_id == tenant_id))
        all_tasks = r.scalars().all()
    assert len(all_tasks) == 1  # Ravi's task was withheld, never created


@pytest.mark.asyncio
async def test_mixed_message_calls_the_planner_once_for_the_paraphrase_only(client, monkeypatch):
    """One edge stated as an explicit possessive (Ravi depends on Nova --
    resolved by the fast path, free) and one edge that's only a
    paraphrase (Priya depends on Ravi, worded as "what Ravi came up
    with" -- needs the LLM) in the same message: the planner must be
    called exactly once, scoped to Priya alone."""
    token, tenant_id, user_id = await _register(client, "acceptmixed")
    agent_a = await _make_agent(tenant_id, "Nova", "model-nova-mixed")
    agent_b = await _make_agent(tenant_id, "Ravi", "model-ravi-mixed")
    agent_c = await _make_agent(tenant_id, "Priya", "model-priya-mixed")
    channel_id = await _make_channel_with_agents(tenant_id, [agent_a, agent_b, agent_c])

    _patch_llms(monkeypatch, {
        "model-nova-mixed": FakeToolCallLLM([AIMessage(content="Summary: 3 widgets.")]),
        "model-ravi-mixed": FakeToolCallLLM([AIMessage(content="3 widgets counted.")]),
        "model-priya-mixed": FakeToolCallLLM([AIMessage(content="Cross-checked: confirmed.")]),
    })
    calls: list = []
    _patch_dependency_planner(monkeypatch, [
        _dep("Priya", depends_on=["Ravi"], confidence="high", reason="wants Ravi's cross-check input"),
    ], calls=calls)

    result = await run_supervisor(
        tenant_id=tenant_id, channel_id=channel_id, project_id=None, user_id=user_id,
        caller_role="owner",
        message=(
            "@Nova summarise the file. @Ravi count the rows in Nova's summary. "
            "@Priya cross-check what Ravi came up with."
        ),
    )

    assert calls == [["Priya"]]  # Nova referenced nobody; Ravi was resolved possessively -- only Priya needed the LLM
    assert result["error"] is None
    assert result["needs_clarification"] is None
    assert len(result["tasks"]) == 3

    nova_task = await _get_task(tenant_id, result["tasks"][0]["task_id"])
    ravi_task = await _get_task(tenant_id, result["tasks"][1]["task_id"])
    priya_task = await _get_task(tenant_id, result["tasks"][2]["task_id"])
    assert ravi_task.depends_on_task_id == nova_task.id  # fast path
    assert priya_task.depends_on_task_id == ravi_task.id  # LLM
    assert all(t.status == TaskStatus.COMPLETED for t in (nova_task, ravi_task, priya_task))


# ---------------------------------------------------------------------
# infer_dependencies() itself -- the prompt/JSON/retry pipeline, mirroring
# task_planner.py's generate_plan() pattern exactly (mocking invoke_llm
# with raw text, not the higher-level function).
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_infer_dependencies_retries_once_on_malformed_json_then_succeeds(monkeypatch):
    calls = []

    async def fake_invoke_llm(messages, *, tenant_id, user_id, request_type):
        calls.append(messages)
        if len(calls) == 1:
            return "not valid json {{{"
        return json.dumps([
            {"agent": "Nova", "depends_on": [], "confidence": None, "reason": None},
            {"agent": "Ravi", "depends_on": ["Nova"], "confidence": "high", "reason": "needs Nova's output"},
        ])
    monkeypatch.setattr(supervisor, "invoke_llm", fake_invoke_llm)

    intents = [
        {"agent_name": "Nova", "employee_type": "dataops", "standing_instructions": None, "text": "do X"},
        {"agent_name": "Ravi", "employee_type": "dataops", "standing_instructions": None, "text": "do Y with Nova's X"},
    ]
    plan = await infer_dependencies(tenant_id="t1", user_id="u1", message="...", intents=intents)

    assert len(calls) == 2  # one corrective retry, matching task_planner.py's own _MAX_GENERATION_ATTEMPTS shape
    assert plan[1]["agent"] == "Ravi"
    assert plan[1]["depends_on"] == ["Nova"]
    assert plan[1]["confidence"] == "high"


@pytest.mark.asyncio
async def test_infer_dependencies_raises_after_exhausting_retries(monkeypatch):
    async def always_malformed(messages, *, tenant_id, user_id, request_type):
        return "still not json"
    monkeypatch.setattr(supervisor, "invoke_llm", always_malformed)

    intents = [
        {"agent_name": "Nova", "employee_type": "dataops", "standing_instructions": None, "text": "do X"},
        {"agent_name": "Ravi", "employee_type": "dataops", "standing_instructions": None, "text": "do Y"},
    ]
    with pytest.raises(DependencyPlanningError):
        await infer_dependencies(tenant_id="t1", user_id="u1", message="...", intents=intents)


@pytest.mark.asyncio
async def test_infer_dependencies_rejects_a_self_dependency(monkeypatch):
    async def self_reference(messages, *, tenant_id, user_id, request_type):
        return json.dumps([
            {"agent": "Nova", "depends_on": ["Nova"], "confidence": "high", "reason": "??"},
            {"agent": "Ravi", "depends_on": [], "confidence": None, "reason": None},
        ])
    monkeypatch.setattr(supervisor, "invoke_llm", self_reference)

    intents = [
        {"agent_name": "Nova", "employee_type": "dataops", "standing_instructions": None, "text": "do X"},
        {"agent_name": "Ravi", "employee_type": "dataops", "standing_instructions": None, "text": "do Y"},
    ]
    with pytest.raises(DependencyPlanningError):
        await infer_dependencies(tenant_id="t1", user_id="u1", message="...", intents=intents)
