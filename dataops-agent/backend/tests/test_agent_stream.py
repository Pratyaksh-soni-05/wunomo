import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.tools import tool

from agent import dataops_agent


@tool
async def fake_echo_tool(x: str) -> str:
    """Echo a string back (test-only fake tool)."""
    return x


class FakeToolCallLLM:
    """Same deterministic stand-in test_agent_graph.py already uses for
    run_agent() — bind_tools() is a no-op, ainvoke() replays a scripted
    sequence. Not itself a real Runnable, so it never emits
    on_chat_model_stream events (see test_run_agent_stream_emits_real_
    token_deltas below for that, using a real streaming-capable fake
    instead) — but ToolNode's tool dispatch is unaffected either way,
    since the tools themselves (fake_echo_tool) are real @tool-decorated
    Runnables regardless of what LLM is driving them."""

    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_run_agent_stream_emits_tool_start_and_tool_end(monkeypatch):
    """run_agent_stream() must surface a tool_start/tool_end pair for a
    real tool call executed via ToolNode — same graph, same tools, same
    approval gate as run_agent(), just consumed via astream_events()
    instead of a single ainvoke()."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_echo_tool", "args": {"x": "hi"}, "id": "call_1"},
        ]),
        AIMessage(content="Done."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_echo_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    events = []
    async for ev in dataops_agent.run_agent_stream(
        user_message="please echo hi", tenant_id="t1", user_id="u1", session_id="s1", caller_role="owner",
    ):
        events.append(ev)

    tool_starts = [e for e in events if e["type"] == "tool_start"]
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    finals = [e for e in events if e["type"] == "final_state"]

    assert len(tool_starts) == 1
    assert tool_starts[0]["name"] == "fake_echo_tool"
    assert "hi" in tool_starts[0]["args_summary"]

    assert len(tool_ends) == 1
    assert tool_ends[0]["name"] == "fake_echo_tool"
    assert tool_ends[0]["ok"] is True
    assert "hi" in tool_ends[0]["result_summary"]

    assert len(finals) == 1
    result = dataops_agent._finalize_agent_result(finals[0]["state"], "s1")
    assert result["response"] == "Done."


@pytest.mark.asyncio
async def test_run_agent_stream_reports_tool_end_not_ok_on_lock_conflict(monkeypatch):
    """The live tool_end badge must agree with the persisted trace's
    "denied_source_locked" status (_extract_tool_trace in api/v1/chat.py)
    about whether a call actually succeeded — a source-lock conflict is a
    normal-looking tool result (no exception), not a ToolNode error, so
    `ok` must come from inspecting the payload, not just the absence of
    an exception."""
    @tool
    async def fake_locked_tool(x: str) -> str:
        """Test-only fake tool that returns a lock-conflict shape."""
        import json
        return json.dumps({"error": "locked", "lock_conflict": True})

    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_locked_tool", "args": {"x": "hi"}, "id": "call_1"},
        ]),
        AIMessage(content="Done."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_locked_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_locked_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    tool_ends = []
    async for ev in dataops_agent.run_agent_stream(
        user_message="do it", tenant_id="t1", user_id="u1", session_id="s1", caller_role="owner",
    ):
        if ev["type"] == "tool_end":
            tool_ends.append(ev)

    assert len(tool_ends) == 1
    assert tool_ends[0]["ok"] is False


@pytest.mark.asyncio
async def test_run_agent_stream_final_state_matches_run_agent_result(monkeypatch):
    """The finalized result built from run_agent_stream()'s captured
    final_state must be identical (on every persistence-relevant field)
    to what run_agent() itself returns for the same script — proof the
    buffered and streaming paths can never quietly diverge."""
    def script():
        return [
            AIMessage(content="", tool_calls=[
                {"name": "fake_echo_tool", "args": {"x": "hi"}, "id": "call_1"},
            ]),
            AIMessage(content="Done."),
        ]

    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_echo_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_echo_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)

    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: FakeToolCallLLM(script()))
    dataops_agent._cache.clear()
    buffered = await dataops_agent.run_agent(
        user_message="please echo hi", tenant_id="t1", user_id="u1", session_id="s1", caller_role="owner",
    )

    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: FakeToolCallLLM(script()))
    dataops_agent._cache.clear()
    final_state = None
    async for ev in dataops_agent.run_agent_stream(
        user_message="please echo hi", tenant_id="t1", user_id="u1", session_id="s1", caller_role="owner",
    ):
        if ev["type"] == "final_state":
            final_state = ev["state"]
    streamed = dataops_agent._finalize_agent_result(final_state, "s1")

    assert streamed["response"] == buffered["response"]
    assert streamed["pending_approvals"] == buffered["pending_approvals"]
    assert len(streamed["messages"]) == len(buffered["messages"])
    assert [type(m).__name__ for m in streamed["messages"]] == [type(m).__name__ for m in buffered["messages"]]


@pytest.mark.asyncio
async def test_run_agent_stream_emits_real_token_deltas(monkeypatch):
    """Uses a real streaming-capable BaseChatModel (GenericFakeChatModel,
    a standard LangChain test double with fake content but a real
    _astream implementation) to prove run_agent_stream() relays live
    token deltas, not just tool/final events.

    agent_node calls llm_with_tools.ainvoke() — a single non-streaming
    call — but LangChain's ambient RunnableConfig propagation makes the
    real underlying chat model stream internally anyway whenever the
    outer graph is driven via astream_events(). Confirmed live against
    the real Gemini-backed compiled graph (17 on_chat_model_stream events
    for one two-LLM-call turn) before writing this; reproduced here
    deterministically with no network call.
    """
    class _StreamingFakeChatModel(GenericFakeChatModel):
        """GenericFakeChatModel has a real _astream() (splits content into
        word-by-word chunks) but its bind_tools() raises NotImplementedError
        unconditionally — dataops_agent.build_agent() always calls
        llm.bind_tools(allowed_tools), even with an empty tool list, so it
        needs a no-op override like every other fake LLM in this test
        suite (FakeToolCallLLM etc)."""

        def bind_tools(self, tools, **kwargs):
            return self

    fake_llm = _StreamingFakeChatModel(messages=iter([AIMessage(content="hello there friend")]))
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {})
    dataops_agent._cache.clear()

    tokens = []
    final_state = None
    async for ev in dataops_agent.run_agent_stream(
        user_message="say hi", tenant_id="t1", user_id="u1", session_id="s1", caller_role="owner",
    ):
        if ev["type"] == "token":
            tokens.append(ev["delta"])
        elif ev["type"] == "final_state":
            final_state = ev["state"]

    assert len(tokens) > 1, f"expected multiple incremental token deltas, got {tokens}"
    assert "".join(tokens) == "hello there friend"
    result = dataops_agent._finalize_agent_result(final_state, "s1")
    assert result["response"] == "hello there friend"
