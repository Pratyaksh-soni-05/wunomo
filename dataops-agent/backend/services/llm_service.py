from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from config import settings
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential
from groq import AuthenticationError as GroqAuthError


log = structlog.get_logger()


def get_primary_llm(temperature=0.0):
    model = settings.PRIMARY_LLM_MODEL
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


def get_fallback_llm(temperature=0.0):
    return ChatGroq(
        model=settings.FALLBACK_LLM_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=temperature,
    )


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


def get_llm_for_agent(temperature=0.0):
    try:
        primary = get_primary_llm(temperature)
        fallback = get_fallback_llm(temperature)
        return primary.with_fallbacks(
            [fallback],
            exceptions_to_handle=(
                ResourceExhausted,
                ServiceUnavailable,
                Exception,
            ),
        )
    except Exception:
        return get_fallback_llm(temperature)