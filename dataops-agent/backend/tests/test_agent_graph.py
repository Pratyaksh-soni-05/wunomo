import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from agent import dataops_agent


@tool
async def fake_echo_tool(x: str) -> str:
    """Echo a string back (test-only fake tool)."""
    return x


@tool
async def fake_identity_tool(tenant_id: str, x: str = "") -> str:
    """Return whatever tenant_id it was actually invoked with (test-only)."""
    return tenant_id


def _identity_tool_call_responses(claimed_tenant_id):
    return [
        AIMessage(content="", tool_calls=[
            {"name": "fake_identity_tool", "args": {"tenant_id": claimed_tenant_id, "x": "hi"}, "id": "call_1"},
        ]),
        AIMessage(content="Done."),
    ]


class FakeToolCallLLM:
    """Deterministic stand-in for the real LLM: bind_tools() is a no-op,
    ainvoke() replays a scripted sequence of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.invoke_history_lengths = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.invoke_history_lengths.append(len(messages))
        return self._responses.pop(0)


def _tool_call_then_final_responses():
    return [
        AIMessage(content="", tool_calls=[
            {"name": "fake_echo_tool", "args": {"x": "hi"}, "id": "call_1"},
        ]),
        AIMessage(content="Done."),
    ]


@pytest.mark.asyncio
async def test_agent_message_history_stays_bounded(monkeypatch):
    """Regression test for the reducer-misuse bug in the LangGraph agent.

    `AgentState.messages` uses an `operator.add` reducer, so LangGraph
    automatically appends whatever a node returns onto the existing
    accumulated value. The custom nodes (`inject_system_prompt`, `agent_node`,
    `approval_gate_node`) used to return `state["messages"] + [new]` instead
    of just `[new]`, so the reducer concatenated old+new onto the
    already-accumulated state on every node hop — a single tool-calling turn
    ballooned from 3 messages to 63 across the internal agent<->tools loop.

    After the fix, one turn with exactly one tool call must produce exactly
    4 messages (human, AI-with-tool-call, tool-result, final AI answer) —
    no duplication.
    """
    fake_llm = FakeToolCallLLM(_tool_call_then_final_responses())
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="please echo hi",
        tenant_id="t1", user_id="u1", session_id="s1",
    )

    messages = result["messages"]
    assert len(messages) == 4, f"expected exactly 4 messages, got {len(messages)}: {messages}"
    assert result["response"] == "Done."

    # The LLM must see a linearly growing, non-duplicated history on each
    # invocation (system prompt + real messages only) rather than the
    # doubling/quadrupling sequence the pre-fix bug produced.
    assert fake_llm.invoke_history_lengths == [2, 4], fake_llm.invoke_history_lengths


@pytest.mark.asyncio
async def test_agent_multi_turn_history_grows_linearly(monkeypatch):
    """Simulate 3 sequential user turns (as the real /chat endpoint does,
    threading only clean human/assistant text back in as `history`) and
    confirm each turn's internal graph run stays bounded on its own —
    growth across turns must be linear in the number of real messages, not
    exponential."""
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)

    from langchain_core.messages import HumanMessage, AIMessage as AIMsg

    history = []
    for turn in range(3):
        fake_llm = FakeToolCallLLM(_tool_call_then_final_responses())
        monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, _l=fake_llm: _l)
        dataops_agent._cache.clear()

        result = await dataops_agent.run_agent(
            user_message=f"turn {turn}",
            tenant_id="t1", user_id="u1", session_id="s1",
            history=history,
        )
        # Each turn's own internal run must stay at exactly
        # len(incoming history) + 1 human + 3 (AI-tool-call, tool-result, final AI).
        assert len(result["messages"]) == len(history) + 4

        history = history + [HumanMessage(content=f"turn {turn}"), AIMsg(content=result["response"])]


@pytest.mark.asyncio
async def test_agent_forces_real_tenant_id_even_if_llm_guesses_wrong(monkeypatch):
    """Regression test for the tenant-isolation gap: tool schemas require
    tenant_id as an LLM-supplied argument, but the LLM previously had no way
    to know the real value and would invent a placeholder (e.g.
    "your_tenant_id"), silently querying the wrong/nonexistent tenant.
    agent_node must force-correct the argument to the real, server-derived
    tenant_id before the tool ever executes — defense-in-depth on top of the
    system-prompt instruction, in case the LLM ignores or mistypes it.
    """
    fake_llm = FakeToolCallLLM(_identity_tool_call_responses("hallucinated-placeholder"))
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_identity_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="do the thing",
        tenant_id="real-tenant-abc", user_id="u1", session_id="s1",
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "real-tenant-abc"


@pytest.mark.asyncio
async def test_client_supplied_context_tenant_id_override_is_ignored(monkeypatch):
    """A client-supplied `context` dict must never be able to override the
    server-derived tenant_id — run_agent() must force it, not merge it,
    whether the mismatch comes from a malicious client or an honest mistake.
    """
    fake_llm = FakeToolCallLLM(_identity_tool_call_responses("real-tenant-abc"))
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_identity_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="do the thing",
        tenant_id="real-tenant-abc", user_id="u1", session_id="s1",
        context={"tenant_id": "malicious-other-tenant", "note": "kept"},
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages[0].content == "real-tenant-abc"
