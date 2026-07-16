import uuid
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from database import AsyncSessionLocal
from models.all_models import LlmUsageEvent
from services.llm_service import _TimeoutFallbackChatModel
import services.llm_service as llm_service_module


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
async def test_invoke_llm_writes_a_real_usage_event(client, monkeypatch):
    """End-to-end regression test for the LlmUsageEvent table + invoke_llm()
    instrumentation: a successful call with a real tenant_id must persist a
    real row, queryable afterward — not just an in-memory side effect."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"usagetest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Usage Test",
        "tenant_name": "Usage Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]

    fake_primary = _FakeLLM(response=AIMessage(
        content="ok", usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    ))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)

    result = await llm_service_module.invoke_llm(
        [HumanMessage(content="hello")], tenant_id=tenant_id, request_type="transform_generation",
    )
    assert result == "ok"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        r = await db.execute(select(LlmUsageEvent).where(LlmUsageEvent.tenant_id == tenant_id))
        events = r.scalars().all()

    assert len(events) == 1
    event = events[0]
    assert event.request_type == "transform_generation"
    assert event.used_fallback is False
    assert event.success is True
    assert event.total_tokens == 5


@pytest.mark.asyncio
async def test_invoke_llm_captures_reasoning_tokens_separately(client, monkeypatch):
    """Gemini 3's "thinking" tokens (usage_metadata.output_token_details.reasoning,
    confirmed live: 94-99 tokens spent on "what is 2+2?") are already folded
    into total_tokens by the provider, but must also land in their own
    reasoning_tokens column — kept distinct since thinking tokens will likely
    be priced differently from plain output tokens for credits later."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"reasoningtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Reasoning Test",
        "tenant_name": "Reasoning Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]

    fake_primary = _FakeLLM(response=AIMessage(
        content="four",
        usage_metadata={
            "input_tokens": 27, "output_tokens": 2, "total_tokens": 128,
            "output_token_details": {"reasoning": 99},
        },
    ))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)

    await llm_service_module.invoke_llm(
        [HumanMessage(content="what is 2+2?")], tenant_id=tenant_id, request_type="agent_chat",
    )

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        r = await db.execute(select(LlmUsageEvent).where(LlmUsageEvent.tenant_id == tenant_id))
        event = r.scalars().one()

    assert event.output_tokens == 2
    assert event.reasoning_tokens == 99
    assert event.total_tokens == 128


@pytest.mark.asyncio
async def test_invoke_llm_skips_logging_without_tenant_id(monkeypatch):
    """No-regression check: callers that don't pass tenant_id (existing tests,
    or any future caller that forgets to) must not crash — logging is just
    skipped, matching log_llm_usage()'s early-return-on-no-tenant_id contract."""
    fake_primary = _FakeLLM(response=AIMessage(content="ok"))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)

    result = await llm_service_module.invoke_llm([HumanMessage(content="hello")])
    assert result == "ok"
