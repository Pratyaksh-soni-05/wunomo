import uuid
import pytest
from unittest.mock import AsyncMock
from langchain_core.messages import AIMessage, HumanMessage

from database import AsyncSessionLocal
from models.all_models import LlmUsageEvent
from services.llm_service import _TimeoutFallbackChatModel
import services.llm_service as llm_service_module
from services.tenant_context import tenant_session


class _FakeLLM:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, *args, **kwargs):
        if self._raises:
            raise self._raises
        return self._response


@pytest.mark.asyncio
async def test_timeout_fallback_model_stashes_usage_on_primary_success():
    """Phase 1 instrumentation: a successful primary call must stash provider/
    model/latency/token usage on the response's additional_kwargs, since
    _TimeoutFallbackChatModel itself has no tenant context to log with directly
    (it's cached/shared across tenants — see CLAUDE.md's _cache gotcha)."""
    primary = _FakeLLM(response=AIMessage(
        content="hi", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    ))
    fallback = _FakeLLM(response=AIMessage(content="unused"))
    model = _TimeoutFallbackChatModel(
        primary, fallback, timeout_seconds=5.0,
        primary_model="gemini-3-flash-preview", fallback_model="llama-3.3-70b-versatile",
    )

    result = await model.ainvoke([])
    usage = result.additional_kwargs["_llm_usage"]

    assert usage["provider"] == "gemini"
    assert usage["model"] == "gemini-3-flash-preview"
    assert usage["used_fallback"] is False
    assert usage["success"] is True
    assert usage["usage_metadata"]["total_tokens"] == 15
    assert usage["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_timeout_fallback_model_stashes_usage_on_fallback():
    """Same as above, but for the fallback path — provider/model must reflect
    the fallback, and used_fallback must be True."""
    primary = _FakeLLM(raises=RuntimeError("quota exceeded"))
    fallback = _FakeLLM(response=AIMessage(content="from fallback"))
    model = _TimeoutFallbackChatModel(
        primary, fallback, timeout_seconds=5.0,
        primary_model="gemini-3-flash-preview", fallback_model="llama-3.3-70b-versatile",
    )

    result = await model.ainvoke([])
    usage = result.additional_kwargs["_llm_usage"]

    assert usage["provider"] == "groq"
    assert usage["model"] == "llama-3.3-70b-versatile"
    assert usage["used_fallback"] is True
    assert usage["success"] is True


@pytest.mark.asyncio
async def test_log_llm_usage_persists_a_real_row(client):
    """End-to-end regression test for the LlmUsageEvent table: log_llm_usage()
    must persist a real, queryable row - not just an in-memory side effect -
    and must correctly extract reasoning tokens (Gemini 3's "thinking" tokens,
    confirmed live: 94-99 tokens spent on "what is 2+2?") into their own
    column separate from output_tokens, since they're already folded into
    total_tokens by the provider and will likely be priced differently later.

    This is the ONLY test in this file that writes a real row into the shared
    llm_usage_events table (calling log_llm_usage directly, once, is how you
    test that it persists correctly - there's no way around that). Every
    other test below asserts on log_llm_usage's *call args* instead of a real
    DB row, specifically so the suite doesn't inflate the same table this
    project also reads to gauge real LLM quota consumption - see GOTCHAS.md,
    2026-08, for the incident where four un-instrumented full-suite runs of
    the old version of this file (which called the real invoke_llm() with
    get_primary_llm mocked, still hitting the real DB write) silently ate
    into the day's real Gemini quota budget."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"usagetest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Usage Test",
        "tenant_name": "Usage Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]

    await llm_service_module.log_llm_usage(
        tenant_id=tenant_id, request_type="agent_chat",
        provider="gemini", model="gemini-3.5-flash", used_fallback=False,
        latency_ms=42, success=True,
        usage_metadata={
            "input_tokens": 27, "output_tokens": 2, "total_tokens": 128,
            "output_token_details": {"reasoning": 99},
        },
    )

    async with tenant_session(tenant_id) as db:
        from sqlalchemy import select
        r = await db.execute(select(LlmUsageEvent).where(LlmUsageEvent.tenant_id == tenant_id))
        events = r.scalars().all()

    assert len(events) == 1
    event = events[0]
    assert event.request_type == "agent_chat"
    assert event.used_fallback is False
    assert event.success is True
    assert event.input_tokens == 27
    assert event.output_tokens == 2
    assert event.reasoning_tokens == 99
    assert event.total_tokens == 128


@pytest.mark.asyncio
async def test_invoke_llm_passes_usage_metadata_to_logger(monkeypatch):
    """invoke_llm() must derive the right provider/model/used_fallback/success
    from a successful primary call and forward the raw usage_metadata (Gemini's
    exact shape, including nested output_token_details) to log_llm_usage
    untouched - log_llm_usage's own persistence and column-extraction logic is
    covered directly by test_log_llm_usage_persists_a_real_row above, so this
    asserts on the mock's call args rather than hitting the real DB, keeping
    this test's contamination footprint at zero real rows."""
    fake_primary = _FakeLLM(response=AIMessage(
        content="four",
        usage_metadata={
            "input_tokens": 27, "output_tokens": 2, "total_tokens": 128,
            "output_token_details": {"reasoning": 99},
        },
    ))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)
    logged = AsyncMock()
    monkeypatch.setattr(llm_service_module, "log_llm_usage", logged)

    result = await llm_service_module.invoke_llm(
        [HumanMessage(content="what is 2+2?")], tenant_id="fake-tenant", request_type="agent_chat",
    )
    assert result == "four"

    logged.assert_awaited_once()
    kwargs = logged.await_args.kwargs
    assert kwargs["tenant_id"] == "fake-tenant"
    assert kwargs["request_type"] == "agent_chat"
    assert kwargs["provider"] == "gemini"
    assert kwargs["used_fallback"] is False
    assert kwargs["success"] is True
    assert kwargs["usage_metadata"]["total_tokens"] == 128
    assert kwargs["usage_metadata"]["output_token_details"]["reasoning"] == 99


@pytest.mark.asyncio
async def test_invoke_llm_flattens_list_shaped_gemini_content(monkeypatch):
    """Regression test for a bug found live while sanity-checking Phase 13's
    schema-grounding fix: invoke_llm() returned r.content raw (annotated -> str
    but not actually guaranteed to be one). Gemini 3.5 responses can come back
    as a list of structured content blocks (see dataops_agent.py's original
    _content_as_text, now shared here as content_as_text) instead of a plain
    string — dataops_agent.py's own run_agent() path already normalized this,
    but invoke_llm() (used by TransformGenerator, IncidentManager, etc.) did
    not, and crashed downstream (e.g. TransformGenerator._extract_code()'s
    re.search on a list) on a real Gemini call. Every caller of invoke_llm()
    must get back a real string, matching its own return-type annotation.

    No tenant_id is passed, so log_llm_usage's own early-return-on-no-tenant_id
    (proven by test_invoke_llm_skips_logging_without_tenant_id below) means
    this exercises the real end-to-end invoke_llm() flow without writing to
    the real DB or needing a real tenant registration."""
    fake_primary = _FakeLLM(response=AIMessage(
        content=[{"type": "text", "text": "SELECT 1;", "extras": {"signature": "abc"}}],
    ))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)

    result = await llm_service_module.invoke_llm(
        [HumanMessage(content="generate")], request_type="transform_generation",
    )
    assert result == "SELECT 1;"
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_invoke_llm_skips_logging_without_tenant_id(monkeypatch):
    """No-regression check: callers that don't pass tenant_id (existing tests,
    or any future caller that forgets to) must not crash — logging is just
    skipped, matching log_llm_usage()'s early-return-on-no-tenant_id contract."""
    fake_primary = _FakeLLM(response=AIMessage(content="ok"))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)

    result = await llm_service_module.invoke_llm([HumanMessage(content="hello")])
    assert result == "ok"


@pytest.mark.asyncio
async def test_log_llm_usage_transient_db_failure_is_swallowed_and_counted(monkeypatch):
    """Gap 1 fix (his branch) + Integration Phase 2/3a's re-composition, now
    tested together, correctly split. A TRANSIENT failure (dropped
    connection, exhausted pool, DB briefly unreachable -- the
    OperationalError/InterfaceError/DBAPIError tuple log_llm_usage's except
    clause names explicitly) must still never raise: the LLM call already
    happened and its answer is about to be returned, so a metering blip
    must not fail the request. It must also no longer just vanish into a
    bare warning -- both detectability traces this test checks (an
    error... no, a WARNING-level log for the transient case specifically,
    see the assertion below, plus the cumulative Redis counters) must
    fire. Forces the failure by making LlmUsageEvent's own constructor
    raise sqlalchemy.exc.OperationalError -- enough to blow up db.add()
    without faking an entire broken DB session -- and asserts it lands in
    the TRANSIENT branch specifically, not the permission-denial one this
    same fix must also prove distinct (see the sibling test below)."""
    import models.all_models as models_module
    from sqlalchemy.exc import OperationalError

    class _BoomLlmUsageEvent:
        def __init__(self, *a, **k):
            raise OperationalError("INSERT INTO llm_usage_events ...", {}, Exception("connection lost"))

    monkeypatch.setattr(models_module, "LlmUsageEvent", _BoomLlmUsageEvent)

    warned = []
    monkeypatch.setattr(
        llm_service_module.log, "warning",
        lambda event, **kw: warned.append((event, kw)),
    )
    errored = []
    monkeypatch.setattr(
        llm_service_module.log, "error",
        lambda event, **kw: errored.append((event, kw)),
    )

    tenant_id = f"gap1-transient-test-{uuid.uuid4().hex[:8]}"
    redis = llm_service_module._redis()
    dropped_key = f"llm_usage_meter:dropped_events:{tenant_id}"
    tokens_key = f"llm_usage_meter:dropped_tokens:{tenant_id}"
    await redis.delete(dropped_key, tokens_key)

    # The core contract: must not raise.
    await llm_service_module.log_llm_usage(
        tenant_id=tenant_id, request_type="agent_chat",
        provider="gemini", model="gemini-3.5-flash", used_fallback=False,
        latency_ms=10, success=True,
        usage_metadata={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
    )

    # Landed in the transient branch (log.warning), not the permission-
    # denial one (log.error) -- and the Redis counter fired, which the
    # permission-denial branch deliberately does not do (see sibling test).
    assert len(warned) == 1
    event, kw = warned[0]
    assert event == "log_llm_usage.transient_failure"
    assert kw["tenant_id"] == tenant_id
    assert kw["request_type"] == "agent_chat"
    assert errored == []

    assert await redis.get(dropped_key) == "1"
    assert await redis.get(tokens_key) == "12"
    await redis.delete(dropped_key, tokens_key)


@pytest.mark.asyncio
async def test_log_llm_usage_still_swallows_transient_failure_if_redis_counter_also_fails(monkeypatch):
    """Belt-and-suspenders: if Redis is ALSO down when a TRANSIENT DB write
    failure happens, log_llm_usage() must still never raise - it's
    best-effort logging on top of best-effort logging, all the way down.
    (Not applicable to the permission-denial branch, which never touches
    Redis at all - see the dedicated permission-denial test.)"""
    import models.all_models as models_module
    from sqlalchemy.exc import OperationalError

    class _BoomLlmUsageEvent:
        def __init__(self, *a, **k):
            raise OperationalError("INSERT INTO llm_usage_events ...", {}, Exception("connection lost"))

    monkeypatch.setattr(models_module, "LlmUsageEvent", _BoomLlmUsageEvent)

    class _BoomRedis:
        async def incr(self, *a, **k):
            raise RuntimeError("redis also down")

        async def incrby(self, *a, **k):
            raise RuntimeError("redis also down")

    monkeypatch.setattr(llm_service_module, "_redis", lambda: _BoomRedis())

    await llm_service_module.log_llm_usage(
        tenant_id="gap1-redis-down-test", request_type="agent_chat",
        provider="gemini", model="gemini-3.5-flash", used_fallback=False,
        latency_ms=10, success=True,
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    )


@pytest.mark.asyncio
async def test_log_llm_usage_permission_denial_reraises_and_is_not_counted_as_a_drop(monkeypatch):
    """Integration Phase 4 item 3: the other half of the composition this
    merge is responsible for keeping intact. A permission/RLS denial
    (InsufficientPrivilege, surfaced here as any exception OTHER than the
    transient tuple above) is NOT a hiccup -- it means the usage meter
    would otherwise silently go blank while every real request kept
    succeeding, and since this table drives quota enforcement and billing
    figures, that gap must be loud, not swallowed. This must (a) raise,
    so the failure is impossible to miss, and (b) NOT increment the
    dropped-event Redis counter -- that counter exists to answer "how many
    routine transient blips happened," and a security-relevant permission
    failure counted alongside them would under-represent exactly the
    class of event most worth noticing."""
    import models.all_models as models_module

    class _BoomLlmUsageEvent:
        def __init__(self, *a, **k):
            raise PermissionError("simulated InsufficientPrivilege from an RLS denial")

    monkeypatch.setattr(models_module, "LlmUsageEvent", _BoomLlmUsageEvent)

    errored = []
    monkeypatch.setattr(
        llm_service_module.log, "error",
        lambda event, **kw: errored.append((event, kw)),
    )
    warned = []
    monkeypatch.setattr(
        llm_service_module.log, "warning",
        lambda event, **kw: warned.append((event, kw)),
    )

    tenant_id = f"gap1-permission-denial-test-{uuid.uuid4().hex[:8]}"
    redis = llm_service_module._redis()
    dropped_key = f"llm_usage_meter:dropped_events:{tenant_id}"
    tokens_key = f"llm_usage_meter:dropped_tokens:{tenant_id}"
    await redis.delete(dropped_key, tokens_key)

    with pytest.raises(PermissionError):
        await llm_service_module.log_llm_usage(
            tenant_id=tenant_id, request_type="agent_chat",
            provider="gemini", model="gemini-3.5-flash", used_fallback=False,
            latency_ms=10, success=True,
            usage_metadata={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        )

    assert len(errored) == 1
    event, kw = errored[0]
    assert event == "log_llm_usage.write_failed"
    assert kw["tenant_id"] == tenant_id
    assert kw["error_type"] == "PermissionError"
    assert warned == []

    # The dropped-event counter must NOT have fired for this -- a
    # permission denial is not "routine drop noise."
    assert await redis.get(dropped_key) is None
    assert await redis.get(tokens_key) is None
