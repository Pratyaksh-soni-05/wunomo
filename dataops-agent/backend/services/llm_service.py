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
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from groq import AuthenticationError as GroqAuthError
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from services.tenant_context import with_tenant_context


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
SUPPORTED_MODEL_OVERRIDES = ["gemini-3.5-flash"]
# `llama-3.3-70b-versatile` was removed 2026-09-16: it is not served by this
# Groq account (the same finding that fixed the FALLBACK on 2026-09-10), and
# a tenant who selected it got a 404 on every primary attempt and a silent
# fallback to openai/gpt-oss-120b -- measured live, recorded in GOTCHAS. Not
# replaced with another Groq name: the only Groq model live-verified for
# tool-calling here IS the fallback, and offering it as a distinct "override"
# would be a false choice. Every entry in this list is now checked against
# the provider's live catalogue at boot by validate_llm_config().

MODEL_LABELS = {
    "gemini-3.5-flash": "Gemini 3.5 Flash",
    "openai/gpt-oss-120b": "GPT-OSS 120B (Groq)",
}


def supported_model_overrides() -> list[dict]:
    """The one source of truth for the Settings -> AI Model picker
    (GET /api/v1/settings/ai-models). The frontend used to carry its own
    hard-coded copy of this list, which is how a model the account does not
    serve stayed on offer for six days after the backend learned it did not
    exist."""
    return [{"value": m, "label": MODEL_LABELS.get(m, m), "provider": _provider_for_model(m)}
            for m in SUPPORTED_MODEL_OVERRIDES]


# Model-name shapes that identify a Groq-hosted model, used ONLY when a caller
# supplies a bare model name with no declared provider (a tenant's
# `ai_model_override`). The configured primary/fallback never reach this path --
# their provider is declared in settings. Extended well past the original
# llama/mixtral/gemma guess, which is what broke: this account's actual chat
# models are `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `groq/compound` and
# `allam-2-7b`, none of which contain any of those three substrings, so every
# one of them was being sent to Google with a Groq model name.
_GROQ_MODEL_HINTS = (
    "llama", "mixtral", "gemma", "qwen", "allam", "whisper",
    "gpt-oss", "compound", "groq/", "openai/", "meta-llama/",
)


class DataResidencyError(RuntimeError):
    """Raised instead of making an outbound LLM call when
    LLM_DATA_RESIDENCY_MODE names a placement this build cannot honour."""


def residency_status() -> dict:
    """What the residency setting currently means, for the startup log,
    tests, and anyone answering a compliance question about a deployment."""
    mode = settings.LLM_DATA_RESIDENCY_MODE
    if mode == "global":
        return {"mode": mode, "outbound_llm_allowed": True,
                "providers": [settings.PRIMARY_LLM_PROVIDER, settings.FALLBACK_LLM_PROVIDER],
                "note": "inference runs at the configured providers' own regions"}
    return {"mode": mode, "outbound_llm_allowed": False, "providers": [],
            "note": f"{mode} endpoint not implemented in this build; every outbound "
                    "LLM call is refused with DataResidencyError",
            "self_hosted_endpoint": settings.LLM_SELF_HOSTED_ENDPOINT or None}


def assert_outbound_llm_allowed() -> None:
    """Item #11's one gate. Called before any provider client is built and
    again before any message list is sent, so a client cached at boot
    (get_agent()'s module-level cache) cannot outlive a mode change.

    The only mode that permits an outbound call today is "global". "eu"
    and "self_hosted" are real settings so an EU buyer has something
    concrete to point at, but the endpoints behind them do not exist yet,
    and the honest behaviour for a residency promise this build cannot keep
    is to refuse the call -- not to send it to the global providers and
    log a warning nobody reads.
    """
    mode = settings.LLM_DATA_RESIDENCY_MODE
    if mode == "global":
        return
    log.error("llm_call_refused_by_residency_mode", mode=mode)
    raise DataResidencyError(
        f"LLM_DATA_RESIDENCY_MODE={mode!r}: no {mode} inference endpoint is implemented "
        "in this build, so outbound LLM calls are refused rather than sent to a "
        "provider outside the configured residency. Set the mode to 'global' to use "
        f"{settings.PRIMARY_LLM_PROVIDER}/{settings.FALLBACK_LLM_PROVIDER}, or wait for "
        "the EU / self-hosted endpoint work (docs/compliance/LLM_DATA_FLOW.md).")


def _provider_for_model(model: str) -> str:
    """Which provider hosts this model.

    Declared configuration wins over inference. Inference is only for a
    per-tenant model override, which supplies a name and no provider.
    """
    if model == settings.PRIMARY_LLM_MODEL:
        return settings.PRIMARY_LLM_PROVIDER
    if model == settings.FALLBACK_LLM_MODEL:
        return settings.FALLBACK_LLM_PROVIDER
    lowered = (model or "").lower()
    return "groq" if any(h in lowered for h in _GROQ_MODEL_HINTS) else "gemini"


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


@with_tenant_context
async def log_llm_usage(
    *, tenant_id: str | None, user_id: str | None = None, session_id: str | None = None,
    task_id: str | None = None, agent_id: str | None = None,
    request_type: str, provider: str, model: str, used_fallback: bool,
    latency_ms: int, success: bool, usage_metadata: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Usage logging — a transient DB hiccup must never break the actual LLM
    call it's describing, but a permission/RLS denial is not a hiccup and is
    re-raised rather than swallowed (see the except blocks below). A
    transient drop also increments a cumulative Redis counter (see
    _record_dropped_usage) so "this happened once" vs "this happened
    constantly" doesn't require grepping logs by hand."""
    if not tenant_id:
        return
    usage_metadata = usage_metadata or {}
    row = {
        "tenant_id": tenant_id, "user_id": user_id, "session_id": session_id,
        "task_id": task_id, "agent_id": agent_id,
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
    except (OperationalError, InterfaceError, DBAPIError) as exc:
        # Transient only: dropped connection, exhausted pool, DB briefly
        # unreachable. The LLM call itself already happened and its answer is
        # about to be returned — a metering blip shouldn't fail the request.
        log.warning("log_llm_usage.transient_failure",
                    tenant_id=tenant_id, request_type=request_type,
                    provider=provider, model=model, error=str(exc))
        await _record_dropped_usage(tenant_id, row["total_tokens"])
    except Exception as exc:
        # Not transient — specifically InsufficientPrivilege from a Row-Level
        # Security denial. Previously this was caught, warned, and dropped, so
        # under RLS the usage meter would silently go blank while every request
        # kept succeeding. Since this table drives quota enforcement and billing
        # figures, silent gaps are worse than a loud failure.
        #
        # NOTE for Master Ranking Item #9 (tamper-evident audit trail): the
        # same caveat as transform_run_log.py — re-raising makes a *failed*
        # write loud, but these rows remain plain, mutable, unsigned records
        # with no chaining, so a successful write is still not tamper-evident.
        log.error("log_llm_usage.write_failed",
                  tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                  request_type=request_type, provider=provider, model=model,
                  error_type=type(exc).__name__, error=str(exc))
        raise

# A failing/quota-exhausted Gemini call doesn't fail fast: google-api-core's own
# gRPC retry layer respects the server's suggested `retry_delay` (we've seen it
# ask for 40s+), and langchain_google_genai wraps that with its own hardcoded
# tenacity retry (max_retries=2, backoff up to 60s) on top — neither is
# configurable from the outside, and ChatGoogleGenerativeAI's own `timeout`
# constructor field is dead code (never wired to the actual request in this
# library version). Left alone, a single failed primary call can take 2+
# minutes before RunnableWithFallbacks ever gets a chance to try Groq. We
# enforce our own hard ceiling instead of trusting those nested retries
# (PRIMARY_LLM_TIMEOUT_SECONDS below, via _TimeoutFallbackChatModel) — and,
# where we can tell the failure apart from a merely slow one, skip waiting
# on it at all (see _is_daily_quota_error and the quota-exhausted cache
# below).
#
# Raised from 15s to 30s when the primary model moved to gemini-3-flash-preview
# (see CLAUDE.md Gotchas): even trivial single-word prompts measured 13-26s
# live, well past the old 15s ceiling, which meant primary lost the race to
# the fallback almost every time. GEMINI_THINKING_BUDGET below caps reasoning
# tokens to reduce that latency — re-measure before lowering this back down.
PRIMARY_LLM_TIMEOUT_SECONDS = 30

# How long we trust a "the primary's daily quota is exhausted" finding before
# re-checking the primary again. Google's free-tier daily caps reset on a
# fixed wall-clock boundary (documented as midnight Pacific), not on a fixed
# offset from the failure we observed -- and the raised exception doesn't
# reliably expose that reset instant in a form worth parsing. A flat,
# conservative window is simpler and safer than guessing at the real reset
# time: worst case we re-attempt the primary once an hour while it's still
# exhausted (one wasted attempt, capped by PRIMARY_LLM_TIMEOUT_SECONDS same
# as any other primary failure) -- cheap compared to paying the full
# retry-storm cost on every single call, which is the status quo this exists
# to fix.
QUOTA_EXHAUSTED_CACHE_TTL_SECONDS = 3600

_QUOTA_EXHAUSTED_KEY_PREFIX = "llm_quota_exhausted"


def _is_daily_quota_error(exc: Exception) -> bool:
    """A 429 whose message carries a DAILY quota-reset signal (Gemini's
    free-tier quota_id strings look like
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier") is fundamentally
    different from a transient rate limit or a network blip: retrying
    against the same primary again today can never succeed, no matter how
    long we wait or how many times we try -- there's no backoff duration
    that fixes "the quota resets tomorrow." A ResourceExhausted WITHOUT
    that marker (e.g. a per-minute rate limit) is still worth the normal
    retry -- only the daily shape is treated as non-retryable-against-
    primary. ServiceUnavailable (503) is never a quota condition at all,
    daily or otherwise -- ordinary transient-error handling covers it."""
    if not isinstance(exc, ResourceExhausted):
        return False
    normalized = str(exc).replace("_", "").replace("-", "").replace(" ", "").lower()
    return "perday" in normalized


def _is_terminal_llm_error(exc: Exception) -> bool:
    """A failure invoke_llm()'s own OUTER @retry should never spend
    another attempt on. Reaching this point already means BOTH primary
    and fallback failed once (invoke_llm()'s try/except already gave the
    fallback a real chance before re-raising) -- retrying a known-terminal
    condition three more times at wait_exponential's own backoff pace just
    repeats the same wasted latency for the same guaranteed outcome, not a
    chance at a different one."""
    return _is_daily_quota_error(exc) or isinstance(exc, GroqAuthError)


def _quota_exhausted_cache_key(provider: str, model: str) -> str:
    return f"{_QUOTA_EXHAUSTED_KEY_PREFIX}:{provider}:{model}"


async def _mark_quota_exhausted(provider: str, model: str) -> None:
    """Best-effort: a cache-write failure must never block the fallback
    response the caller is already about to receive -- worst case, the
    next call simply rediscovers the same exhaustion at full cost, exactly
    today's status quo, not a new failure mode."""
    try:
        await _redis().set(
            _quota_exhausted_cache_key(provider, model), "1", ex=QUOTA_EXHAUSTED_CACHE_TTL_SECONDS,
        )
    except Exception as exc:
        log.warning("quota_exhausted_cache_write_failed", provider=provider, model=model, error=str(exc))


async def _is_quota_exhausted_cached(provider: str, model: str) -> bool:
    """Best-effort: a cache-read failure must fail OPEN (assume not
    exhausted, try the primary as normal) rather than silently starving
    the primary of traffic it may actually be able to serve."""
    try:
        return bool(await _redis().exists(_quota_exhausted_cache_key(provider, model)))
    except Exception as exc:
        log.warning("quota_exhausted_cache_read_failed", provider=provider, model=model, error=str(exc))
        return False

# Gemini 3 models default to an internal "thinking" pass before answering —
# observed burning 94-99 reasoning tokens on "what is 2+2?" and adding
# meaningful wall-clock latency. 0 disables it. Not (yet) proven to fix the
# latency by itself (one measured sample was slower with it than without),
# but it does eliminate the reasoning-token cost, so keep it capped
# regardless. Raise this only if answer quality visibly suffers on real
# tool-calling turns — see CLAUDE.md Gotchas for the measured latency data
# this value shipped with.
GEMINI_THINKING_BUDGET = 0


def _build_llm(model: str, temperature: float, provider: str | None = None):
    """Route to the right provider client.

    `provider`, when given, is the DECLARED provider from settings and is
    authoritative. Only when it is absent (a per-tenant model override, which
    carries a name and nothing else) does this fall back to inferring from the
    model name.

    Hard Rule 2 still holds and is what this preserves: neither
    get_primary_llm() nor get_fallback_llm() returns ChatGoogleGenerativeAI
    unconditionally. What changed is the basis of the branch -- declared
    provider instead of a substring guess -- because the guess was wrong for
    every Groq chat model this account actually has.
    """
    assert_outbound_llm_allowed()   # Item #11: before any client exists
    resolved = (provider or _provider_for_model(model) or "").lower()
    if resolved == "groq":
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
    # An explicit `model` is a per-tenant override with no declared provider,
    # so let _build_llm infer for that case only.
    if model and model != settings.PRIMARY_LLM_MODEL:
        return _build_llm(model, temperature)
    return _build_llm(settings.PRIMARY_LLM_MODEL, temperature,
                      provider=settings.PRIMARY_LLM_PROVIDER)


def get_fallback_llm(temperature=0.0):
    # Bug fix: this used to always build a ChatGroq client regardless of
    # FALLBACK_LLM_MODEL, so a fallback configured for another provider
    # (e.g. Gemini) would silently be sent through the wrong SDK. Route it
    # the same way the primary model is routed.
    return _build_llm(settings.FALLBACK_LLM_MODEL, temperature,
                      provider=settings.FALLBACK_LLM_PROVIDER)


class _TimeoutFallbackChatModel:
    """Drop-in replacement for `primary.with_fallbacks([fallback])` that adds
    a hard wall-clock ceiling on the primary attempt. `RunnableWithFallbacks`
    only moves on once the primary's call raises — it doesn't enforce a
    timeout itself, so a primary stuck in nested internal retries (see
    PRIMARY_LLM_TIMEOUT_SECONDS above) never actually reaches the fallback in
    reasonable time. Implements just the `bind_tools`/`ainvoke` surface
    `agent/dataops_agent.py` actually calls.

    Shared by BOTH get_llm_for_agent() (the agent-chat path) and invoke_llm()
    (every other LLM call in this codebase) as of the quota-exhaustion fix --
    previously invoke_llm() had its own separate, timeout-less primary/
    fallback logic and paid the full retry-storm cost this class exists to
    avoid on every one of its call sites (window_and_summarize(),
    task_planner.generate_plan(), task_executor's step re-planning,
    transform_generator, supervisor.infer_dependencies(), IncidentManager).
    One mechanism, one place to get it right.
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

    async def _call_fallback(self, messages, *args, **kwargs):
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

    async def ainvoke(self, messages, *args, **kwargs):
        # No tenant/session context reaches this class (it's built once and
        # cached across tenants via get_agent() — see CLAUDE.md gotcha on
        # _cache). Usage details are stashed on the response's
        # additional_kwargs instead; the caller (agent_node, which does have
        # tenant context) is responsible for popping and logging them.
        assert_outbound_llm_allowed()   # Item #11: the agent path, cached clients
        provider = _provider_for_model(self._primary_model)

        # A previous call already discovered the primary's daily quota is
        # exhausted -- every call within the TTL would otherwise pay the
        # same cost (up to the full timeout, or the real retry-storm
        # latency if that surfaces faster) just to rediscover the same
        # fact. Skip the primary entirely and go straight to fallback.
        if await _is_quota_exhausted_cached(provider, self._primary_model):
            return await self._call_fallback(messages, *args, **kwargs)

        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._primary.ainvoke(messages, *args, **kwargs),
                timeout=self._timeout,
            )
            response.additional_kwargs["_llm_usage"] = {
                "provider": provider,
                "model": self._primary_model,
                "used_fallback": self._force_used_fallback,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "success": True,
                "usage_metadata": getattr(response, "usage_metadata", None) or {},
            }
            return response
        except Exception as e:
            if _is_daily_quota_error(e):
                # Non-retryable against this primary today, by definition
                # (see _is_daily_quota_error) -- no gRPC retry, no tenacity
                # retry, no backoff: fail over immediately, and remember it
                # so the NEXT call skips the primary too.
                log.warning("primary_llm_quota_exhausted", error=str(e), model=self._primary_model)
                await _mark_quota_exhausted(provider, self._primary_model)
            else:
                log.warning("primary_llm_failed_or_timed_out", error=str(e), timeout=self._timeout)
            return await self._call_fallback(messages, *args, **kwargs)


# Excludes two shapes of guaranteed-to-repeat failure from the outer retry,
# not one: a residency refusal (DataResidencyError, Item #11 -- a
# configuration fact, not a transient fault) and a known-terminal LLM
# failure (_is_terminal_llm_error -- the primary's daily quota, or a bad
# fallback API key). Retrying either three more times at wait_exponential's
# pace just repeats the same wasted latency for the same guaranteed outcome.
@retry(
    stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(
        lambda exc: not isinstance(exc, DataResidencyError) and not _is_terminal_llm_error(exc)
    ),
    reraise=True,
)
async def invoke_llm(
    messages: list, temperature=0.0, *, tenant_id: str | None = None,
    user_id: str | None = None, session_id: str | None = None,
    task_id: str | None = None, agent_id: str | None = None,
    request_type: str = "general_completion",
) -> str:
    """Primary->fallback with the same hard timeout ceiling and quota-
    exhaustion short-circuit get_llm_for_agent() already had, via the
    shared _TimeoutFallbackChatModel (see its own docstring). The outer
    @retry only re-attempts this whole function if BOTH primary and
    fallback failed -- and only when that combined failure ISN'T already
    known-terminal (_is_terminal_llm_error) or a residency refusal
    (DataResidencyError, Item #11): retrying either three more times at
    wait_exponential's pace just repeats the same wasted latency for the
    same guaranteed outcome."""
    assert_outbound_llm_allowed()   # Item #11: before any message is sent
    start = time.monotonic()
    model_wrapper = _TimeoutFallbackChatModel(
        get_primary_llm(temperature), get_fallback_llm(temperature), PRIMARY_LLM_TIMEOUT_SECONDS,
    )
    try:
        response = await model_wrapper.ainvoke(messages)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        await log_llm_usage(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id, agent_id=agent_id,
            request_type=request_type, provider=_provider_for_model(settings.FALLBACK_LLM_MODEL),
            model=settings.FALLBACK_LLM_MODEL, used_fallback=True, latency_ms=latency_ms, success=False,
            error_message=str(exc),
        )
        raise

    usage = response.additional_kwargs.get("_llm_usage", {})
    await log_llm_usage(
        tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id, agent_id=agent_id,
        request_type=request_type,
        provider=usage.get("provider", _provider_for_model(settings.PRIMARY_LLM_MODEL)),
        model=usage.get("model", settings.PRIMARY_LLM_MODEL),
        used_fallback=usage.get("used_fallback", False),
        latency_ms=usage.get("latency_ms", int((time.monotonic() - start) * 1000)),
        success=True, usage_metadata=usage.get("usage_metadata"),
    )
    return content_as_text(response.content)


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
        agent_id: str | None = None,
        request_type: str = "general_completion",
    ) -> str:
        from langchain_core.messages import HumanMessage
        return await invoke_llm(
            [HumanMessage(content=prompt)], temperature=temperature,
            tenant_id=tenant_id, user_id=user_id, session_id=session_id, task_id=task_id, agent_id=agent_id,
            request_type=request_type,
        )

# ── Configuration validation ─────────────────────────────────────────────────

_GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _live_models(provider: str) -> set[str]:
    """Model ids the configured credentials can actually reach.

    Listing models costs no generation quota with either provider, which is why
    this is safe to run at startup and in the test suite.
    """
    import httpx

    if provider == "groq":
        r = httpx.get(_GROQ_MODELS_URL,
                      headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                      timeout=15)
        r.raise_for_status()
        return {m["id"] for m in r.json().get("data", [])}

    r = httpx.get(_GEMINI_MODELS_URL,
                  params={"key": settings.GEMINI_API_KEY, "pageSize": 200},
                  timeout=15)
    r.raise_for_status()
    # Gemini returns "models/gemini-3.5-flash"; callers configure the bare name.
    return {m["name"].split("/", 1)[-1] for m in r.json().get("models", [])}


def validate_llm_config() -> list[str]:
    """Check each configured model against its provider's live catalogue.

    Returns a list of human-readable problems; empty means the configuration is
    sound. Raises nothing — a network blip must not be able to stop the app
    booting, and a broken FALLBACK must not stop it serving traffic on a
    working PRIMARY. Callers decide how loud to be; `main.py` logs at ERROR and
    tests assert the list is empty.

    This exists because the failure it catches is invisible at rest: the
    fallback was configured to `llama-3.3-70b-versatile`, which is not in this
    Groq account at all, so the "fallback" had never once worked and only
    surfaced as a 404 at the exact moment the primary was already failing.
    """
    problems: list[str] = []
    checks = [
        ("PRIMARY", settings.PRIMARY_LLM_PROVIDER, settings.PRIMARY_LLM_MODEL),
        ("FALLBACK", settings.FALLBACK_LLM_PROVIDER, settings.FALLBACK_LLM_MODEL),
    ]
    # Every per-tenant override option too (2026-09-16). These are what the
    # Settings -> AI Model picker offers, and one of them was a model the
    # account did not serve: a tenant who chose it got a 404 on every turn
    # and a silent fallback. Same rule as PRIMARY/FALLBACK -- a name nobody
    # validates against the catalogue fails only at the moment it is needed.
    checks += [(f"OVERRIDE {m!r}", _provider_for_model(m), m) for m in SUPPORTED_MODEL_OVERRIDES]

    catalogues: dict[str, set[str] | None] = {}
    for label, provider, model in checks:
        if provider not in ("groq", "gemini"):
            problems.append(f"{label}: unknown provider {provider!r}")
            continue
        if provider not in catalogues:
            try:
                catalogues[provider] = _live_models(provider)
            except Exception as exc:
                log.warning("llm_config_check_unreachable", provider=provider, error=str(exc))
                catalogues[provider] = None
        available = catalogues[provider]
        if available is None:
            continue
        if model not in available:
            problems.append(
                f"{label}: model {model!r} is not available to the configured "
                f"{provider} credentials"
            )
    return problems
