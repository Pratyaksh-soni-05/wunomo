"""Model liveness check (2026-09-03).

The Groq deprecation of llama-3.3-70b-versatile (see GOTCHAS.md) was
silent for an unknown period across 265 real tenant rows -- nothing in
this app ever checked whether a configured model still existed until a
real chat/task request failed against it mid-incident. This closes that
gap: ping every model this app could actually select for a real request
-- PRIMARY_LLM_MODEL, FALLBACK_LLM_MODEL, and every value in
SUPPORTED_MODEL_OVERRIDES (the only tenant-level overrides
get_ai_model_override() will ever actually return; a raw string sitting
unused in some tenant's stored settings but no longer in this list is
already inert, and pinging it would just reconfirm known-dead junk) --
once at boot, and again on demand via GET /health/models.

Deliberately a model-metadata GET, not a real generation call: zero
token spend, same distinction this codebase's own Gotchas already draw
between "the model doesn't exist" and "a real completion succeeded."
Cached in Redis (CACHE_TTL_SECONDS) so a fleet-wide restart (backend +
celery_worker + celery_beat all coming up around the same deploy) shares
one real check instead of three, and so polling /health/models doesn't
hit the providers on every request.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from redis import asyncio as aioredis

from config import settings
from services.llm_service import SUPPORTED_MODEL_OVERRIDES, _provider_for_model

log = structlog.get_logger()

CACHE_TTL_SECONDS = 600  # 10 minutes
CACHE_KEY = "model_liveness:v1"
_REQUEST_TIMEOUT_SECONDS = 10.0

# Lazy singleton, not a module-level client built at import time -- binds
# to whatever event loop happens to exist then, which breaks across
# pytest-asyncio's test/loop boundaries. Same pattern as
# services/auth_service.py's own _redis(), for the identical reason.
_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


def _configured_models() -> set[str]:
    return {settings.PRIMARY_LLM_MODEL, settings.FALLBACK_LLM_MODEL, *SUPPORTED_MODEL_OVERRIDES}


async def _check_one_model(model: str) -> dict:
    provider = _provider_for_model(model)
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            if provider == "gemini":
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
                    params={"key": settings.GEMINI_API_KEY},
                )
            else:
                r = await client.get(
                    f"https://api.groq.com/openai/v1/models/{model}",
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                )
    except Exception as exc:
        return {"model": model, "provider": provider, "status": "error", "detail": str(exc)}

    if r.status_code == 200:
        return {"model": model, "provider": provider, "status": "ok"}
    if r.status_code == 404:
        return {"model": model, "provider": provider, "status": "not_found", "detail": r.text[:300]}
    return {"model": model, "provider": provider, "status": "error", "detail": f"HTTP {r.status_code}: {r.text[:300]}"}


async def check_configured_models(force: bool = False) -> dict:
    """Returns {"checked_at": iso, "results": [...], "cached": bool}.
    force=True (the health endpoint's own recheck path, and tests)
    bypasses the Redis cache; a plain boot-time call never does, so a
    fleet-wide restart within CACHE_TTL_SECONDS of the last check is
    genuinely free."""
    if not force:
        cached = await _redis().get(CACHE_KEY)
        if cached:
            payload = json.loads(cached)
            payload["cached"] = True
            # Still logged on every call, cache hit or miss -- a dead
            # model must stay loud on every boot within the cache
            # window, not just the one boot that happened to do the
            # real check. A silent cache hit here would mean a fleet
            # restart 2 minutes after a real failure logs nothing at
            # all, undoing the whole point of this check.
            dead = [r for r in payload["results"] if r["status"] != "ok"]
            if dead:
                log.error("model_liveness_check_failed", dead_models=dead, cached=True)
            return payload

    results = await asyncio.gather(*(_check_one_model(m) for m in sorted(_configured_models())))
    payload = {"checked_at": datetime.now(timezone.utc).isoformat(), "results": results, "cached": False}

    dead = [r for r in results if r["status"] != "ok"]
    if dead:
        log.error("model_liveness_check_failed", dead_models=dead, cached=False)
    else:
        log.info("model_liveness_check_ok", models=[r["model"] for r in results])

    await _redis().set(CACHE_KEY, json.dumps({k: v for k, v in payload.items() if k != "cached"}), ex=CACHE_TTL_SECONDS)
    return payload
