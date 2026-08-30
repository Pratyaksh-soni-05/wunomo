import asyncio
import time
from typing import Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from redis import asyncio as aioredis
from config import settings
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential
from groq import AuthenticationError as GroqAuthError


log = structlog.get_logger()

# Same lazy, loop-aware client pattern as services/auth_service.py's OTP
# rate limiter (_redis()) - a module-level client bound at import time
# would break across pytest-asyncio's per-test event loops. Not reusing
# auth_service._redis() directly since no shared redis-accessor module
# exists yet in this codebase; each file that needs Redis builds its own.
_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


async def _record_dropped_usage(tenant_id: str, total_tokens: Optional[int]) -> None:
    """Best-effort detectability signal for a usage row that failed to
    persist - cumulative counters (not TTL-windowed like the OTP rate
    limiter's keys), since this is a 'has this ever happened, by how
    much' gauge to check on demand, not a time-boxed rate gate. Must
    never itself raise: a Redis hiccup on top of the DB hiccup it's
    reporting must not break log_llm_usage()'s own never-fail contract."""
    try:
        await _redis().incr(f"llm_usage_meter:dropped_events:{tenant_id}")
        if total_tokens:
            await _redis().incrby(f"llm_usage_meter:dropped_tokens:{tenant_id}", total_tokens)
    except Exception as exc:
        log.warning("dropped_usage_counter_failed", tenant_id=tenant_id, error=str(exc))

# The only models this project has actually live-verified end-to-end for
# real tool-calling (see CLAUDE.md's LangChain v1.x upgrade row and the
# Gemini quota-deprecation Gotcha). A tenant's AI model override (Phase
# 16, Tenant.settings.ai_model_override) is validated against exactly this
# list, not left as a free string - the Gemini-saga lesson applied: an
# unvalidated/unsupported model name doesn't error clearly, it silently
# degrades (falls through to the fallback on every request, or just fails
# in a way that looks like an unrelated bug). Kept in this one place -
# extend it only once a new model is actually proven working here, not
# just because a provider released it.
SUPPORTED_MODEL_OVERRIDES = ["gemini-3.5-flash", "llama-3.3-70b-versatile"]


def _provider_for_model(model: str) -> str:
    """Same routing rule _build_llm() uses, exposed for usage logging."""
    if "llama" in model or "mixtral" in model or "gemma" in model:
        return "groq"
    return "gemini"


def content_as_text(content) -> str:
    """langchain-core 1.x (post-upgrade) can return AIMessage.content as a
    list of structured content blocks (e.g. Gemini 3.5's
    `[{"type": "text", "text": "...", "extras": {"signature": "..."}}]`,
    the new home for what used to be a bare `thought_signature` field)
    instead of the plain string every prior version always returned. Every
    caller of invoke_llm() (and the agent graph's own equivalent handling in
    dataops_agent.py) treats the return value as a plain string — normalize
    once here rather than at every call site. Shared here (not just in
    dataops_agent.py) because invoke_llm() is a separate call path (used by
    TransformGenerator, IncidentManager, etc.) that hits the identical
    Gemini 3.5 response shape and was crashing on it independently."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


async def log_llm_usage(
    *, tenant_id: str | None, user_id: str | None = None, session_id: str | None = None,
    task_id: str | None = None,
    request_type: str, provider: str, model: str, used_fallback: bool,
    latency_ms: int, success: bool, usage_metadata: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Best-effort usage logging — a DB hiccup here must never break the
    actual LLM call it's describing, so failures are logged and swallowed.
    A dropped row used to vanish with just a warning line carrying the
    exception text - no token count, no way to tell "this happened once"
    from "this happened constantly" without grepping logs by hand. Now the
    full would-be row goes into an error-level log line (a dropped usage
    row is a real gap in cost accounting, not a routine warning), plus a
    cumulative Redis counter (see _record_dropped_usage) that can be
    checked on demand rather than only discovered by re-reading logs."""
    if not tenant_id:
        return
    usage_metadata = usage_metadata or {}
    row = {
        "tenant_id": tenant_id, "user_id": user_id, "session_id": session_id,
        "task_id": task_id,
        "request_type": request_type, "provider": provider, "model": model,
        "used_fallback": used_fallback,
        "input_tokens": usage_metadata.get("input_tokens"),
        "output_tokens": usage_metadata.get("output_tokens"),
        "reasoning_tokens": (usage_metadata.get("output_token_details") or {}).get("reasoning"),
        "total_tokens": usage_metadata.get("total_tokens"),
        "latency_ms": latency_ms, "success": success, "error_message": error_message,
    }
    try:
        from database import AsyncSessionLocal
        from models.all_models import LlmUsageEvent
        async with AsyncSessionLocal() as db:
            db.add(LlmUsageEvent(**row))
            await db.commit()
    except Exception as exc:
        log.error("log_llm_usage_dropped", write_error=str(exc), **row)
        await _record_dropped_usage(tenant_id, row["total_tokens"])

# A failing/quota-exhausted Gemini call doesn't fail fast: google-api-core's own
# gRPC retry layer respects the server's suggested `retry_delay` (we've seen it
# ask for 40s+), and langchain_google_genai wraps that with its own hardcoded
# tenacity retry (max_retries=2, backoff up to 60s) on top — neither is
# configurable from the outside, and ChatGoogleGenerativeAI's own `timeout`
# constructor field is dead code (never wired to the actual request in this
# library version). Left alone, a single failed primary call can take 2+
# minutes before RunnableWithFallbacks ever gets a chance to try Groq. We
# enforce our own hard ceiling instead of trusting those nested retries.
#
# Raised from 15s to 30s when the primary model moved to gemini-3-flash-preview
# (see CLAUDE.md Gotchas): even trivial single-word prompts measured 13-26s
# live, well past the old 15s ceiling, which meant primary lost the race to
# the fallback almost every time. GEMINI_THINKING_BUDGET below caps reasoning
# tokens to reduce that latency — re-measure before lowering this back down.
PRIMARY_LLM_TIMEOUT_SECONDS = 30

# Gemini 3 models default to an internal "thinking" pass before answering —
# observed burning 94-99 reasoning tokens on "what is 2+2?" and adding
# meaningful wall-clock latency. 0 disables it. Not (yet) proven to fix the
# latency by itself (one measured sample was slower with it than without),
# but it does eliminate the reasoning-token cost, so keep it capped
# regardless. Raise this only if answer quality visibly suffers on real
# tool-calling turns — see CLAUDE.md Gotchas for the measured latency data
# this value shipped with.
GEMINI_THINKING_BUDGET = 0


def _build_llm(model: str, temperature: float):
    """Route to the right provider client based on the model name."""
    if "llama" in model or "mixtral" in model or "gemma" in model:
        return ChatGroq(
            model=model,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=temperature,
        )
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature,
        thinking_budget=GEMINI_THINKING_BUDGET,
    )


def get_primary_llm(temperature=0.0, model: str | None = None):
    return _build_llm(model or settings.PRIMARY_LLM_MODEL, temperature)


def get_fallback_llm(temperature=0.0):
    # Bug fix: this used to always build a ChatGroq client regardless of
    # FALLBACK_LLM_MODEL, so a fallback configured for another provider
    # (e.g. Gemini) would silently be sent through the wrong SDK. Route it
    # the same way the primary model is routed.
    return _build_llm(settings.FALLBACK_LLM_MODEL, temperature)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def invoke_llm(
    messages: list, temperature=0.0, *, tenant_id: str | None = None,
    user_id: str | None = None, session_id: str | None = None,
    task_id: str | None = None,
    request_type: str = "general_completion",
) -> str:
    start = time.monotonic()
    used_fallback = False
    model = settings.PRIMARY_LLM_MODEL
    try:
        llm = get_primary_llm(temperature)
        r = await llm.ainvoke(messages)
        latency_ms = int((time.monotonic() - start) * 1000)
        await log_llm_usage(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id,
            request_type=request_type, provider=_provider_for_model(model), model=model,
            used_fallback=False, latency_ms=latency_ms, success=True,
            usage_metadata=getattr(r, "usage_metadata", None),
        )
        return content_as_text(r.content)
    except Exception as e:
        log.warning("primary_llm_failed", error=str(e))
        used_fallback = True
        model = settings.FALLBACK_LLM_MODEL
        fallback_start = time.monotonic()
        try:
            llm = get_fallback_llm(temperature)
            r = await llm.ainvoke(messages)
            latency_ms = int((time.monotonic() - fallback_start) * 1000)
            await log_llm_usage(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id,
                request_type=request_type, provider=_provider_for_model(model), model=model,
                used_fallback=True, latency_ms=latency_ms, success=True,
                usage_metadata=getattr(r, "usage_metadata", None),
            )
            return content_as_text(r.content)
        except Exception as fallback_exc:
            latency_ms = int((time.monotonic() - fallback_start) * 1000)
            await log_llm_usage(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id,
                request_type=request_type, provider=_provider_for_model(model), model=model,
                used_fallback=True, latency_ms=latency_ms, success=False,
                error_message=str(fallback_exc),
            )
            raise


class _TimeoutFallbackChatModel:
    """Drop-in replacement for `primary.with_fallbacks([fallback])` that adds
    a hard wall-clock ceiling on the primary attempt. `RunnableWithFallbacks`
    only moves on once the primary's call raises — it doesn't enforce a
    timeout itself, so a primary stuck in nested internal retries (see
    PRIMARY_LLM_TIMEOUT_SECONDS above) never actually reaches the fallback in
    reasonable time. Implements just the `bind_tools`/`ainvoke` surface
    `agent/dataops_agent.py` actually calls.
    """

    def __init__(
        self, primary, fallback, timeout_seconds, primary_model=None, fallback_model=None,
        force_used_fallback=False,
    ):
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_seconds
        self._primary_model = primary_model or settings.PRIMARY_LLM_MODEL
        self._fallback_model = fallback_model or settings.FALLBACK_LLM_MODEL
        # Set when the caller already knows the "primary" slot holds the
        # fallback client itself (get_llm_for_agent's build-failure branch)
        # - the primary-succeeded code path below would otherwise report
        # used_fallback=False just because nothing raised on this call,
        # even though the model actually serving the request is the
        # fallback, not the real primary.
        self._force_used_fallback = force_used_fallback

    def bind_tools(self, tools):
        return _TimeoutFallbackChatModel(
            self._primary.bind_tools(tools),
            self._fallback.bind_tools(tools),
            self._timeout,
            self._primary_model, self._fallback_model,
            force_used_fallback=self._force_used_fallback,
        )

    async def ainvoke(self, messages, *args, **kwargs):
        # No tenant/session context reaches this class (it's built once and
        # cached across tenants via get_agent() — see CLAUDE.md gotcha on
        # _cache). Usage details are stashed on the response's
        # additional_kwargs instead; the caller (agent_node, which does have
        # tenant context) is responsible for popping and logging them.
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._primary.ainvoke(messages, *args, **kwargs),
                timeout=self._timeout,
            )
            response.additional_kwargs["_llm_usage"] = {
                "provider": _provider_for_model(self._primary_model),
                "model": self._primary_model,
                "used_fallback": self._force_used_fallback,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "success": True,
                "usage_metadata": getattr(response, "usage_metadata", None) or {},
            }
            return response
        except Exception as e:
            log.warning("primary_llm_failed_or_timed_out", error=str(e), timeout=self._timeout)
            fallback_start = time.monotonic()
            response = await self._fallback.ainvoke(messages, *args, **kwargs)
            response.additional_kwargs["_llm_usage"] = {
                "provider": _provider_for_model(self._fallback_model),
                "model": self._fallback_model,
                "used_fallback": True,
                "latency_ms": int((time.monotonic() - fallback_start) * 1000),
                "success": True,
                "usage_metadata": getattr(response, "usage_metadata", None) or {},
            }
            return response


def get_llm_for_agent(temperature=0.0, primary_model: str | None = None):
    """primary_model overrides settings.PRIMARY_LLM_MODEL for this call
    only (Phase 16's per-tenant AI model override) - the fallback model is
    always the global settings.FALLBACK_LLM_MODEL, since fallback is
    reliability infrastructure, not a per-tenant preference.

    Always returns a _TimeoutFallbackChatModel, never a bare client -
    agent_node's usage logging depends on the _llm_usage key that only
    the wrapper stashes onto a response's additional_kwargs. This used to
    fall back to a bare get_fallback_llm() client on ANY exception here
    (including the primary failing to even build), which meant every chat
    turn served that way was completely unmetered - no _llm_usage key, so
    agent_node's `if usage:` check silently skipped log_llm_usage() the
    whole time. get_fallback_llm() itself is deliberately NOT wrapped in
    the try - if there's genuinely no LLM available at all, failing loudly
    here is more honest than silently returning a broken, unmetered
    object further down the call chain."""
    fallback = get_fallback_llm(temperature)
    force_used_fallback = False
    try:
        primary = get_primary_llm(temperature, model=primary_model)
        primary_model_name = primary_model or settings.PRIMARY_LLM_MODEL
    except Exception as exc:
        log.warning(
            "primary_llm_build_failed", error=str(exc),
            primary_model=primary_model or settings.PRIMARY_LLM_MODEL,
        )
        primary = fallback
        primary_model_name = settings.FALLBACK_LLM_MODEL
        force_used_fallback = True
    return _TimeoutFallbackChatModel(
        primary, fallback, PRIMARY_LLM_TIMEOUT_SECONDS,
        primary_model=primary_model_name,
        force_used_fallback=force_used_fallback,
    )


class LLMService:
    """String-in/string-out completion wrapper for callers outside the agent
    graph (e.g. IncidentManager) that want a single prompt answered rather
    than a chat-message list. Reuses invoke_llm()'s already-tested
    primary->fallback->retry path rather than introducing a third LLM
    invocation mechanism alongside get_llm_for_agent() and invoke_llm()."""

    async def complete(
        self, prompt: str, temperature: float = 0.0, *, tenant_id: str | None = None,
        user_id: str | None = None, session_id: str | None = None, task_id: str | None = None,
        request_type: str = "general_completion",
    ) -> str:
        from langchain_core.messages import HumanMessage
        return await invoke_llm(
            [HumanMessage(content=prompt)], temperature=temperature,
            tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id,
            request_type=request_type,
        )