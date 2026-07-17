import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from agent import dataops_agent
from agent.tools.cicd_tools import get_cicd_status


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


@tool
async def fake_object_arg_tool(tenant_id: str, payload: dict) -> str:
    """Return the type name actually received for `payload` (test-only).
    Named `payload`, not `config` — `config` collides with LangChain's own
    reserved RunnableConfig parameter name and gets silently dropped before
    the tool function ever sees it, independent of anything this test is
    checking (found live while writing this test; see CLAUDE.md — the real
    orchestration_tools.py create_pipeline() has this exact collision)."""
    return type(payload).__name__ + ":" + str(payload)


@pytest.mark.asyncio
async def test_stringified_dict_arg_is_coerced_back_to_a_real_dict(monkeypatch):
    """Regression test for the langchain-google-genai 3.2.0 finding (see
    CLAUDE.md Gotchas): Gemini 3.5's tool calls, once parsed by
    langchain-google-genai, arrive with dict/list-typed arguments as
    JSON-encoded strings rather than native Python objects — reproduced
    live and traced to the library's own function-call parsing, not our
    tool schemas or Gemini's actual model output. agent_node must coerce
    these back to real dicts/lists (using the tool's own declared schema)
    before the tool function ever runs, the same way it already
    force-overrides tenant_id on every outgoing call.
    """
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {
                "name": "fake_object_arg_tool",
                "args": {"tenant_id": "t1", "payload": '{"path": "test.csv", "nested": {"a": 1}}'},
                "id": "call_1",
            },
        ]),
        AIMessage(content="Done."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_object_arg_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="register this", tenant_id="t1", user_id="u1", session_id="s1",
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    # If coercion didn't run, this would read "str:{\"path\": ...}" instead.
    assert tool_messages[0].content == "dict:{'path': 'test.csv', 'nested': {'a': 1}}"


@pytest.mark.asyncio
async def test_malformed_json_string_arg_is_left_for_the_tool_to_reject(monkeypatch):
    """If the "stringified dict" isn't even valid JSON, coercion must not
    raise — leave the value as-is and let LangChain's own schema validation
    surface a graceful error (it rejects a plain string where the tool
    declares a dict), rather than crashing agent_node itself on a malformed
    upstream response."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {
                "name": "fake_object_arg_tool",
                "args": {"tenant_id": "t1", "payload": "not valid json {{{"},
                "id": "call_1",
            },
        ]),
        AIMessage(content="Done."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_object_arg_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="register this", tenant_id="t1", user_id="u1", session_id="s1",
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    # Coercion leaves the un-parseable string alone; LangChain's own
    # schema validation (payload: dict) then rejects it gracefully —
    # no crash, no silent pass-through of a string where a dict was required.
    assert "Error" in tool_messages[0].content
    assert "payload" in tool_messages[0].content


@pytest.mark.asyncio
async def test_get_cicd_status_tool_uses_real_tenant_id(monkeypatch):
    """Regression test for the get_cicd_status tenant-isolation gap: this tool
    used to take no tenant_id at all and call back into the app's own REST API
    with no auth header, silently returning empty defaults from the 401 it got
    instead of an error. It's now a normal tool with tenant_id as its first
    argument (querying via services.cicd_service.get_status_summary directly,
    no HTTP), so it must be covered by the same force-override mechanism as
    every other tool — confirm agent_node corrects a wrong/hallucinated
    tenant_id before the real tool executes, and that the real tool runs
    successfully end-to-end (against the live test DB) rather than raising.
    """
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "get_cicd_status", "args": {"tenant_id": "hallucinated-placeholder", "query": "status"}, "id": "call_1"},
        ]),
        AIMessage(content="Done."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [get_cicd_status])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="what's my CICD status?",
        tenant_id="real-tenant-abc", user_id="u1", session_id="s1",
    )

    # The tool call's args must have been corrected to the real tenant_id
    # before ToolNode ever executed it.
    ai_with_call = next(m for m in result["messages"] if getattr(m, "tool_calls", None))
    assert ai_with_call.tool_calls[0]["args"]["tenant_id"] == "real-tenant-abc"

    # The real tool actually ran (no exception, no leftover httpx 401) and
    # returned a well-formed summary.
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "CICD Status Summary" in tool_messages[0].content


class InfiniteToolCallLLM:
    """Stand-in for an LLM that never produces a final answer — always
    returns another tool call. Used to deterministically drive the graph
    into MAX_AGENT_ITERATIONS' graceful stop, the way a real runaway
    tool-calling conversation would."""

    def __init__(self):
        self.call_count = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.call_count += 1
        return AIMessage(content="", tool_calls=[
            {"name": "fake_echo_tool", "args": {"x": "again"}, "id": f"call_{self.call_count}"},
        ])


@pytest.mark.asyncio
async def test_runaway_tool_calling_hits_graceful_cap_not_a_crash(monkeypatch):
    """Regression test for the iteration_count/recursion_limit miscalibration
    bug: iteration_count only increments once per agent_node visit, but each
    tool-calling round costs 3 LangGraph supersteps (agent -> approval_gate ->
    tools). With the old hardcoded `> 20` check and LangGraph's default
    recursion_limit (25), a real runaway tool-calling conversation hit
    LangGraph's own limit first and crashed with an unhandled
    GraphRecursionError — the "graceful" cap never actually fired. Confirmed
    live: a real conversation hung for 2+ minutes and crashed with zero
    response persisted to chat_messages.

    An LLM that always returns another tool call (never a final answer) must
    now be cut off by our own MAX_AGENT_ITERATIONS cap, cleanly, with no
    exception — not race LangGraph's harder limit.
    """
    fake_llm = InfiniteToolCallLLM()
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="please keep going forever",
        tenant_id="t1", user_id="u1", session_id="s1",
    )

    assert result["response"] == "Max reasoning steps reached. Please clarify your request."
    # MAX_AGENT_ITERATIONS+1 real calls proceed (entry iteration_count 0..N
    # all pass the `> N` check); the next one triggers the graceful stop
    # without calling the LLM again.
    assert fake_llm.call_count == dataops_agent.MAX_AGENT_ITERATIONS + 1

    # The whole point: this must stay comfortably under LangGraph's actual
    # recursion_limit, not just barely — assert the real numbers, so a future
    # change to either constant without re-deriving the other fails loudly.
    # 1 inject_system + 3 supersteps (agent/approval_gate/tools) per real
    # tool-calling round + 2 for the final grace-stop round (agent/approval_gate,
    # no tools needed since it has no tool_calls).
    needed_supersteps = 1 + 3 * (dataops_agent.MAX_AGENT_ITERATIONS + 1) + 2
    assert needed_supersteps < dataops_agent.AGENT_RECURSION_LIMIT, (
        "MAX_AGENT_ITERATIONS and AGENT_RECURSION_LIMIT are out of sync — "
        "the graceful cap could lose the race to LangGraph's own limit again"
    )
