"""Model liveness check (2026-09-03, see GOTCHAS.md's Groq-deprecation
entry) -- services/model_liveness.py pings every configured model via a
cheap provider-side model-metadata GET (never a real generation call, so
these tests mock httpx rather than spend real tokens or hit real
providers on every suite run).
"""
import json

import pytest

import services.model_liveness as liveness_module
from services.model_liveness import _configured_models, check_configured_models


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self, status_by_model: dict):
        self._status_by_model = status_by_model

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        for model, status in self._status_by_model.items():
            if model in url:
                if status == 200:
                    return _FakeResponse(200)
                if status == 404:
                    return _FakeResponse(404, f"model_not_found: {model}")
                return _FakeResponse(status, "error")
        return _FakeResponse(404, "unrecognized model in fake")


def _patch_client(monkeypatch, status_by_model: dict):
    monkeypatch.setattr(
        liveness_module.httpx, "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(status_by_model),
    )


async def _clear_cache():
    await liveness_module._redis().delete(liveness_module.CACHE_KEY)


@pytest.fixture(autouse=True)
async def _reset_liveness_cache():
    """This cache key is real, shared Redis state -- the same one
    GET /health/models and the real boot-time check read (see the
    codebase's own "test suite hits whatever Redis APP_ENV=test resolves
    to" Gotcha). Without this, a test that deliberately writes a fake
    "dead model" result leaves the REAL health endpoint reporting a
    false positive for up to CACHE_TTL_SECONDS after the suite finishes
    -- caught live: running this file once left gemini-3.5-flash
    reporting not_found against the real /health/models for several
    minutes. Clean on both sides so test order/failures can't leak a
    stale result either way."""
    await _clear_cache()
    yield
    await _clear_cache()


def test_configured_models_includes_primary_fallback_and_overrides():
    models = _configured_models()
    from config import settings
    from services.llm_service import SUPPORTED_MODEL_OVERRIDES
    assert settings.PRIMARY_LLM_MODEL in models
    assert settings.FALLBACK_LLM_MODEL in models
    for m in SUPPORTED_MODEL_OVERRIDES:
        assert m in models


@pytest.mark.asyncio
async def test_all_models_ok(client, monkeypatch):
    await _clear_cache()
    _patch_client(monkeypatch, {m: 200 for m in _configured_models()})

    payload = await check_configured_models(force=True)
    assert payload["cached"] is False
    assert all(r["status"] == "ok" for r in payload["results"])
    assert {r["model"] for r in payload["results"]} == _configured_models()


@pytest.mark.asyncio
async def test_a_dead_model_is_reported_not_found(client, monkeypatch):
    await _clear_cache()
    models = sorted(_configured_models())
    dead_model = models[0]
    status_map = {m: 200 for m in models}
    status_map[dead_model] = 404
    _patch_client(monkeypatch, status_map)

    payload = await check_configured_models(force=True)
    dead = [r for r in payload["results"] if r["status"] == "not_found"]
    assert len(dead) == 1
    assert dead[0]["model"] == dead_model


@pytest.mark.asyncio
async def test_provider_network_error_is_reported_as_error_not_a_crash(client, monkeypatch):
    await _clear_cache()

    class _RaisingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise ConnectionError("simulated network failure")

    monkeypatch.setattr(liveness_module.httpx, "AsyncClient", lambda *a, **k: _RaisingClient())

    payload = await check_configured_models(force=True)
    assert all(r["status"] == "error" for r in payload["results"])


@pytest.mark.asyncio
async def test_result_is_cached_across_calls_without_force(client, monkeypatch):
    await _clear_cache()
    call_count = {"n": 0}

    class _CountingClient(_FakeAsyncClient):
        async def get(self, url, **kwargs):
            call_count["n"] += 1
            return await super().get(url, **kwargs)

    monkeypatch.setattr(
        liveness_module.httpx, "AsyncClient",
        lambda *a, **k: _CountingClient({m: 200 for m in _configured_models()}),
    )

    first = await check_configured_models(force=False)
    assert first["cached"] is False
    n_after_first = call_count["n"]
    assert n_after_first > 0

    second = await check_configured_models(force=False)
    assert second["cached"] is True
    assert call_count["n"] == n_after_first, "a cached call must not re-ping any provider"


@pytest.mark.asyncio
async def test_force_bypasses_the_cache(client, monkeypatch):
    await _clear_cache()
    _patch_client(monkeypatch, {m: 200 for m in _configured_models()})
    await check_configured_models(force=False)

    call_count = {"n": 0}

    class _CountingClient(_FakeAsyncClient):
        async def get(self, url, **kwargs):
            call_count["n"] += 1
            return await super().get(url, **kwargs)

    monkeypatch.setattr(
        liveness_module.httpx, "AsyncClient",
        lambda *a, **k: _CountingClient({m: 200 for m in _configured_models()}),
    )
    payload = await check_configured_models(force=True)
    assert payload["cached"] is False
    assert call_count["n"] > 0


# ---------------------------------------------------------------------------
# GET /health/models
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_models_endpoint_ok(client, monkeypatch):
    await _clear_cache()
    _patch_client(monkeypatch, {m: 200 for m in _configured_models()})
    r = await client.get("/health/models?force=true")
    assert r.status_code == 200
    assert all(x["status"] == "ok" for x in r.json()["results"])


@pytest.mark.asyncio
async def test_health_models_endpoint_503_when_a_model_is_dead(client, monkeypatch):
    await _clear_cache()
    models = sorted(_configured_models())
    status_map = {m: 200 for m in models}
    status_map[models[0]] = 404
    _patch_client(monkeypatch, status_map)

    r = await client.get("/health/models?force=true")
    assert r.status_code == 503
    assert any(x["status"] == "not_found" for x in r.json()["results"])
