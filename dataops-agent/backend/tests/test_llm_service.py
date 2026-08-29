import asyncio
import time
import pytest
from langchain_core.messages import AIMessage

import services.llm_service as llm_service_module
from services.llm_service import _TimeoutFallbackChatModel


class _FakeLLM:
    """Deterministic stand-in for a chat model: optionally sleeps before
    responding (simulating a slow/stuck primary), or raises immediately."""

    def __init__(self, response=None, delay=0.0, raises=None):
        self._response = response
        self._delay = delay
        self._raises = raises
        self.bind_tools_calls = []
        self.ainvoke_calls = 0

    def bind_tools(self, tools):
        self.bind_tools_calls.append(tools)
        return self

    async def ainvoke(self, messages, *args, **kwargs):
        self.ainvoke_calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise self._raises
        return self._response


@pytest.mark.asyncio
async def test_slow_primary_falls_back_quickly_instead_of_hanging():
    """Regression test for the ~2.5-minute fallback latency bug: a primary
    stuck in its own internal retry logic (simulated here with a long sleep)
    must be abandoned at the configured timeout, not waited out, and the
    fallback's response must be returned instead."""
    slow_primary = _FakeLLM(delay=5.0)
    fast_fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(slow_primary, fast_fallback, timeout_seconds=0.1)

    start = time.monotonic()
    result = await model.ainvoke([])
    elapsed = time.monotonic() - start

    assert result.content == "from fallback"
    assert elapsed < 1.0, f"expected fallback well under the primary's 5s delay, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_failing_primary_falls_back_immediately():
    """A primary that raises outright (e.g. ResourceExhausted) must still
    fall back, same as before this change — not just on timeout."""
    failing_primary = _FakeLLM(raises=RuntimeError("quota exceeded"))
    fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(failing_primary, fallback, timeout_seconds=5.0)

    result = await model.ainvoke([])
    assert result.content == "from fallback"


@pytest.mark.asyncio
async def test_healthy_primary_used_directly_with_no_added_latency():
    """No-regression check: a normal, fast, successful primary response must
    be returned as-is, with no fallback call and no artificial delay from the
    timeout wrapper itself."""
    healthy_primary = _FakeLLM(response=AIMessage(content="from primary"))
    fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(healthy_primary, fallback, timeout_seconds=15.0)

    start = time.monotonic()
    result = await model.ainvoke([])
    elapsed = time.monotonic() - start

    assert result.content == "from primary"
    assert fallback.ainvoke_calls == 0, "fallback must not be called when primary succeeds"
    assert elapsed < 0.5, f"healthy primary call should return immediately, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_bind_tools_propagates_to_both_primary_and_fallback():
    """bind_tools() must return a wrapper whose ainvoke() still enforces the
    timeout/fallback behavior — this is how agent_node actually uses it
    (get_llm_for_agent(...).bind_tools(ALL_TOOLS))."""
    slow_primary = _FakeLLM(delay=5.0)
    fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(slow_primary, fallback, timeout_seconds=0.1)

    bound = model.bind_tools(["some_tool_schema"])
    result = await bound.ainvoke([])

    assert result.content == "from fallback"
    assert slow_primary.bind_tools_calls == [["some_tool_schema"]]
    assert fallback.bind_tools_calls == [["some_tool_schema"]]


@pytest.mark.asyncio
async def test_get_llm_for_agent_wraps_even_when_primary_build_fails(monkeypatch):
    """Gap 2 fix: if building the primary client itself raises (bad model
    name, SDK-level construction error - not a runtime API failure), the
    caller must still get back a _TimeoutFallbackChatModel, not a bare
    client. agent_node's usage logging depends entirely on the _llm_usage
    key the wrapper stashes onto additional_kwargs; a bare client has no
    such key, so every turn served that way used to log nothing at all."""
    fake_fallback = _FakeLLM(response=AIMessage(content="from fallback"))

    def _boom_primary(temperature=0.0, model=None):
        raise RuntimeError("bad model config")

    monkeypatch.setattr(llm_service_module, "get_primary_llm", _boom_primary)
    monkeypatch.setattr(llm_service_module, "get_fallback_llm", lambda temperature=0.0: fake_fallback)

    model = llm_service_module.get_llm_for_agent(temperature=0.0)
    assert isinstance(model, _TimeoutFallbackChatModel)

    result = await model.ainvoke([])
    assert result.content == "from fallback"
    usage = result.additional_kwargs["_llm_usage"]
    assert usage["provider"] == "groq"
    assert usage["model"] == "llama-3.3-70b-versatile"
    assert usage["used_fallback"] is True


@pytest.mark.asyncio
async def test_get_llm_for_agent_raises_if_fallback_itself_cant_build(monkeypatch):
    """If the fallback client can't even be built, there is genuinely no
    LLM available for this request. Failing loudly here is more honest
    than the old behavior (silently returning a broken, unmetered bare
    client further down the call chain)."""
    def _boom_fallback(temperature=0.0):
        raise RuntimeError("no groq key configured")

    monkeypatch.setattr(llm_service_module, "get_fallback_llm", _boom_fallback)

    with pytest.raises(RuntimeError, match="no groq key configured"):
        llm_service_module.get_llm_for_agent(temperature=0.0)
