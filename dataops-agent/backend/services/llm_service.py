import asyncio
import time
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from config import settings
import structlog
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from groq import AuthenticationError as GroqAuthError
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from services.tenant_context import with_tenant_context


log = structlog.get_logger()

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
    request_type: str, provider: str, model: str, used_fallback: bool,
    latency_ms: int, success: bool, usage_metadata: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Usage logging — a transient DB hiccup must never break the actual LLM
    call it's describing, but a permission/RLS denial is not a hiccup and is
    re-raised rather than swallowed (see the except blocks below)."""
    if not tenant_id:
        return
    try:
        from database import AsyncSessionLocal
        from models.all_models import LlmUsageEvent
        usage_metadata = usage_metadata or {}
        async with AsyncSessionLocal() as db:
            db.add(LlmUsageEvent(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                request_type=request_type, provider=provider, model=model,
                used_fallback=used_fallback,
                input_tokens=usage_metadata.get("input_tokens"),
                output_tokens=usage_metadata.get("output_tokens"),
                reasoning_tokens=(usage_metadata.get("output_token_details") or {}).get("reasoning"),
                total_tokens=usage_metadata.get("total_tokens"),
                latency_ms=latency_ms, success=success, error_message=error_message,
            ))
            await db.commit()
    except (OperationalError, InterfaceError, DBAPIError) as exc:
        # Transient only: dropped connection, exhausted pool, DB briefly
        # unreachable. The LLM call itself already happened and its answer is
        # about to be returned — a metering blip shouldn't fail the request.
        log.warning("log_llm_usage.transient_failure",
                    tenant_id=tenant_id, request_type=request_type,
                    provider=provider, model=model, error=str(exc))
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


# retry_if_not_exception_type: a residency refusal is a configuration fact,
# not a transient fault -- retrying it three times with backoff would only
# delay the same answer by up to 20 seconds.
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_not_exception_type(DataResidencyError))
async def invoke_llm(
    messages: list, temperature=0.0, *, tenant_id: str | None = None,
    user_id: str | None = None, session_id: str | None = None,
    request_type: str = "general_completion",
) -> str:
    assert_outbound_llm_allowed()   # Item #11: before any message is sent
    start = time.monotonic()
    used_fallback = False
    model = settings.PRIMARY_LLM_MODEL
    try:
        llm = get_primary_llm(temperature)
        r = await llm.ainvoke(messages)
        latency_ms = int((time.monotonic() - start) * 1000)
        await log_llm_usage(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
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
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                request_type=request_type, provider=_provider_for_model(model), model=model,
                used_fallback=True, latency_ms=latency_ms, success=True,
                usage_metadata=getattr(r, "usage_metadata", None),
            )
            return content_as_text(r.content)
        except Exception as fallback_exc:
            latency_ms = int((time.monotonic() - fallback_start) * 1000)
            await log_llm_usage(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
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

    def __init__(self, primary, fallback, timeout_seconds, primary_model=None, fallback_model=None):
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_seconds
        self._primary_model = primary_model or settings.PRIMARY_LLM_MODEL
        self._fallback_model = fallback_model or settings.FALLBACK_LLM_MODEL

    def bind_tools(self, tools):
        return _TimeoutFallbackChatModel(
            self._primary.bind_tools(tools),
            self._fallback.bind_tools(tools),
            self._timeout,
            self._primary_model, self._fallback_model,
        )

    async def ainvoke(self, messages, *args, **kwargs):
        # No tenant/session context reaches this class (it's built once and
        # cached across tenants via get_agent() — see CLAUDE.md gotcha on
        # _cache). Usage details are stashed on the response's
        # additional_kwargs instead; the caller (agent_node, which does have
        # tenant context) is responsible for popping and logging them.
        assert_outbound_llm_allowed()   # Item #11: the agent path, cached clients
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._primary.ainvoke(messages, *args, **kwargs),
                timeout=self._timeout,
            )
            response.additional_kwargs["_llm_usage"] = {
                "provider": _provider_for_model(self._primary_model),
                "model": self._primary_model,
                "used_fallback": False,
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
    reliability infrastructure, not a per-tenant preference."""
    try:
        primary = get_primary_llm(temperature, model=primary_model)
        fallback = get_fallback_llm(temperature)
        return _TimeoutFallbackChatModel(
            primary, fallback, PRIMARY_LLM_TIMEOUT_SECONDS,
            primary_model=primary_model or settings.PRIMARY_LLM_MODEL,
        )
    except Exception:
        return get_fallback_llm(temperature)


class LLMService:
    """String-in/string-out completion wrapper for callers outside the agent
    graph (e.g. IncidentManager) that want a single prompt answered rather
    than a chat-message list. Reuses invoke_llm()'s already-tested
    primary->fallback->retry path rather than introducing a third LLM
    invocation mechanism alongside get_llm_for_agent() and invoke_llm()."""

    async def complete(
        self, prompt: str, temperature: float = 0.0, *, tenant_id: str | None = None,
        user_id: str | None = None, session_id: str | None = None,
        request_type: str = "general_completion",
    ) -> str:
        from langchain_core.messages import HumanMessage
        return await invoke_llm(
            [HumanMessage(content=prompt)], temperature=temperature,
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
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
