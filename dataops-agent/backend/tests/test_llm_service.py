import asyncio
import time
import uuid
import pytest
from google.api_core.exceptions import ResourceExhausted
from langchain_core.messages import AIMessage

import services.llm_service as llm_service_module
from services.llm_service import _TimeoutFallbackChatModel, invoke_llm


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
    # Pinned explicitly rather than relying on whatever settings.FALLBACK_LLM_MODEL
    # currently is - this test is about the wrap-on-build-failure behavior, not
    # about which model happens to be configured (that drifts independently;
    # see GOTCHAS.md's Groq-deprecation entry for why coupling to it directly
    # made this exact assertion silently start failing once before).
    monkeypatch.setattr(llm_service_module.settings, "FALLBACK_LLM_MODEL", "test-fallback-model")

    model = llm_service_module.get_llm_for_agent(temperature=0.0)
    assert isinstance(model, _TimeoutFallbackChatModel)

    result = await model.ainvoke([])
    assert result.content == "from fallback"
    usage = result.additional_kwargs["_llm_usage"]
    assert usage["provider"] == "groq"
    assert usage["model"] == "test-fallback-model"
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


# ---------------------------------------------------------------------
# Quota-exhaustion fix: a 429 carrying Gemini's daily-quota marker is
# fundamentally different from a transient one -- google-api-core's own
# gRPC retry and langchain_google_genai's hardcoded internal tenacity
# retry both blindly retry ANY ResourceExhausted, daily or not, which is
# what turned a single exhausted-quota call into a 65-90s+ wait before
# ever reaching Groq. These tests use unique per-test model names so a
# cache write from one test can never leak into another (or into a real
# production model name) within the TTL.
# ---------------------------------------------------------------------

def _daily_quota_exc() -> ResourceExhausted:
    return ResourceExhausted(
        "429 Resource has been exhausted (e.g. check quota). "
        "quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    )


def _transient_429_exc() -> ResourceExhausted:
    return ResourceExhausted("429 Resource has been exhausted. Please retry in a few seconds.")


@pytest.mark.asyncio
async def test_daily_quota_error_fails_over_immediately_and_caches_the_exhaustion():
    """A 429 carrying the daily-quota marker must fail over to the
    fallback immediately -- no gRPC retry, no tenacity retry, no backoff
    inside this wrapper -- with exactly one primary attempt, well under a
    second. The exhaustion must also be cached: a second call on the same
    wrapper within the TTL must skip the primary entirely."""
    model_name = f"gemini-test-quota-{uuid.uuid4().hex[:8]}"
    primary = _FakeLLM(raises=_daily_quota_exc())
    fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(
        primary, fallback, timeout_seconds=30.0,
        primary_model=model_name, fallback_model="test-fallback-model",
    )

    start = time.monotonic()
    result = await model.ainvoke([])
    elapsed = time.monotonic() - start

    assert result.content == "from fallback"
    assert primary.ainvoke_calls == 1
    assert elapsed < 1.0, f"expected immediate failover, took {elapsed:.2f}s"

    # Cached: a second call within the TTL must skip the primary entirely.
    result2 = await model.ainvoke([])
    assert result2.content == "from fallback"
    assert primary.ainvoke_calls == 1  # the primary was never attempted a second time


@pytest.mark.asyncio
async def test_transient_429_is_not_cached_as_daily_exhaustion():
    """A ResourceExhausted WITHOUT the daily-quota marker (e.g. a per-
    minute rate limit) still falls over to the fallback like any other
    primary failure, but must NOT populate the quota-exhausted cache -- a
    later call should still be willing to try the primary again, not skip
    it for a full hour over what might have been a momentary blip."""
    model_name = f"gemini-test-transient-{uuid.uuid4().hex[:8]}"
    primary = _FakeLLM(raises=_transient_429_exc())
    fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(
        primary, fallback, timeout_seconds=30.0,
        primary_model=model_name, fallback_model="test-fallback-model",
    )
    result = await model.ainvoke([])
    assert result.content == "from fallback"

    # A fresh wrapper for the SAME model must still be willing to try the
    # primary -- nothing was cached as exhausted.
    recovered_primary = _FakeLLM(response=AIMessage(content="from primary, recovered"))
    model2 = _TimeoutFallbackChatModel(
        recovered_primary, fallback, timeout_seconds=30.0,
        primary_model=model_name, fallback_model="test-fallback-model",
    )
    result2 = await model2.ainvoke([])
    assert result2.content == "from primary, recovered"
    assert recovered_primary.ainvoke_calls == 1


@pytest.mark.asyncio
async def test_invoke_llm_surfaces_a_clear_error_when_both_providers_are_down(monkeypatch):
    """A total outage of both providers must raise a clear, real error --
    not hang. Neither failure here is known-terminal, so the outer @retry
    is still allowed to re-attempt (each attempt fails fast since both
    fakes raise immediately with no delay), and the real exception from
    the last attempt is what surfaces, not a generic wrapper error."""
    def _boom_primary(temperature=0.0, model=None):
        return _FakeLLM(raises=RuntimeError("primary down"))

    def _boom_fallback(temperature=0.0):
        return _FakeLLM(raises=RuntimeError("fallback down"))

    monkeypatch.setattr(llm_service_module, "get_primary_llm", _boom_primary)
    monkeypatch.setattr(llm_service_module, "get_fallback_llm", _boom_fallback)

    with pytest.raises(RuntimeError, match="fallback down"):
        await invoke_llm([], tenant_id=None)


@pytest.mark.asyncio
async def test_invoke_llm_outer_retry_gives_up_immediately_on_a_terminal_failure(monkeypatch):
    """If the failure that ultimately escapes both primary and fallback is
    itself a known-terminal one (here: the FALLBACK's own daily-quota
    exhaustion), invoke_llm()'s outer @retry must not spend two more
    attempts on a guaranteed-to-repeat outcome -- exactly one primary
    build/attempt, not three."""
    attempt_count = {"n": 0}

    def _boom_primary(temperature=0.0, model=None):
        attempt_count["n"] += 1
        return _FakeLLM(raises=RuntimeError("primary down"))

    def _boom_fallback(temperature=0.0):
        return _FakeLLM(raises=_daily_quota_exc())

    monkeypatch.setattr(llm_service_module, "get_primary_llm", _boom_primary)
    monkeypatch.setattr(llm_service_module, "get_fallback_llm", _boom_fallback)

    with pytest.raises(ResourceExhausted):
        await invoke_llm([], tenant_id=None)

    assert attempt_count["n"] == 1  # the outer @retry never re-attempted a known-terminal failure


@pytest.mark.asyncio
async def test_invoke_llm_outer_retry_still_retries_a_non_terminal_double_failure(monkeypatch):
    """The flip side of the above: when neither failure is known-terminal,
    the outer @retry must still behave as before this fix -- multiple
    attempts, not a blanket "never retry invoke_llm() again" regression."""
    attempt_count = {"n": 0}

    def _boom_primary(temperature=0.0, model=None):
        attempt_count["n"] += 1
        return _FakeLLM(raises=RuntimeError("primary down"))

    def _boom_fallback(temperature=0.0):
        return _FakeLLM(raises=RuntimeError("fallback down, transient"))

    monkeypatch.setattr(llm_service_module, "get_primary_llm", _boom_primary)
    monkeypatch.setattr(llm_service_module, "get_fallback_llm", _boom_fallback)

    with pytest.raises(RuntimeError, match="fallback down, transient"):
        await invoke_llm([], tenant_id=None)

    assert attempt_count["n"] == 3  # stop_after_attempt(3), unchanged for genuinely non-terminal failures
