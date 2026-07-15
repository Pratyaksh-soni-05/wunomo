import asyncio
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from config import settings
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential
from groq import AuthenticationError as GroqAuthError


log = structlog.get_logger()

# A failing/quota-exhausted Gemini call doesn't fail fast: google-api-core's own
# gRPC retry layer respects the server's suggested `retry_delay` (we've seen it
# ask for 40s+), and langchain_google_genai wraps that with its own hardcoded
# tenacity retry (max_retries=2, backoff up to 60s) on top — neither is
# configurable from the outside, and ChatGoogleGenerativeAI's own `timeout`
# constructor field is dead code (never wired to the actual request in this
# library version). Left alone, a single failed primary call can take 2+
# minutes before RunnableWithFallbacks ever gets a chance to try Groq. We
# enforce our own hard ceiling instead of trusting those nested retries.
PRIMARY_LLM_TIMEOUT_SECONDS = 15


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
        convert_system_message_to_human=True,
    )


def get_primary_llm(temperature=0.0):
    return _build_llm(settings.PRIMARY_LLM_MODEL, temperature)


def get_fallback_llm(temperature=0.0):
    # Bug fix: this used to always build a ChatGroq client regardless of
    # FALLBACK_LLM_MODEL, so a fallback configured for another provider
    # (e.g. Gemini) would silently be sent through the wrong SDK. Route it
    # the same way the primary model is routed.
    return _build_llm(settings.FALLBACK_LLM_MODEL, temperature)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def invoke_llm(messages: list, temperature=0.0) -> str:
    try:
        llm = get_primary_llm(temperature)
        r = await llm.ainvoke(messages)
        return r.content
    except Exception as e:
        log.warning("primary_llm_failed", error=str(e))
        llm = get_fallback_llm(temperature)
        r = await llm.ainvoke(messages)
        return r.content


class _TimeoutFallbackChatModel:
    """Drop-in replacement for `primary.with_fallbacks([fallback])` that adds
    a hard wall-clock ceiling on the primary attempt. `RunnableWithFallbacks`
    only moves on once the primary's call raises — it doesn't enforce a
    timeout itself, so a primary stuck in nested internal retries (see
    PRIMARY_LLM_TIMEOUT_SECONDS above) never actually reaches the fallback in
    reasonable time. Implements just the `bind_tools`/`ainvoke` surface
    `agent/dataops_agent.py` actually calls.
    """

    def __init__(self, primary, fallback, timeout_seconds):
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_seconds

    def bind_tools(self, tools):
        return _TimeoutFallbackChatModel(
            self._primary.bind_tools(tools),
            self._fallback.bind_tools(tools),
            self._timeout,
        )

    async def ainvoke(self, messages, *args, **kwargs):
        try:
            return await asyncio.wait_for(
                self._primary.ainvoke(messages, *args, **kwargs),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("primary_llm_failed_or_timed_out", error=str(e), timeout=self._timeout)
            return await self._fallback.ainvoke(messages, *args, **kwargs)


def get_llm_for_agent(temperature=0.0):
    try:
        primary = get_primary_llm(temperature)
        fallback = get_fallback_llm(temperature)
        return _TimeoutFallbackChatModel(primary, fallback, PRIMARY_LLM_TIMEOUT_SECONDS)
    except Exception:
        return get_fallback_llm(temperature)


class LLMService:
    """String-in/string-out completion wrapper for callers outside the agent
    graph (e.g. IncidentManager) that want a single prompt answered rather
    than a chat-message list. Reuses invoke_llm()'s already-tested
    primary->fallback->retry path rather than introducing a third LLM
    invocation mechanism alongside get_llm_for_agent() and invoke_llm()."""

    async def complete(self, prompt: str, temperature: float = 0.0) -> str:
        from langchain_core.messages import HumanMessage
        return await invoke_llm([HumanMessage(content=prompt)], temperature=temperature)