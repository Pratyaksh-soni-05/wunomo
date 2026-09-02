import os
os.environ["APP_ENV"] = "test"  # MUST be before all project imports

import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from contextlib import asynccontextmanager
from database import AsyncSessionLocal


@pytest_asyncio.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def client():
    from main import app  # imported AFTER env var is set
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# Item 47: services/auth_service.py's email-code rate limiter writes real,
# TTL'd Redis state (otp:hourly:{email}, otp:ip:{ip}, otp:cooldown:{email},
# otp:lockout:{email}, otp:exhausted_streak:{email}) that outlives any
# single test. Every test client request goes through the same source
# "IP" (the ASGI test transport), so otp:ip:{ip} in particular accumulates
# across every test in the run regardless of which file or email is
# involved - a sufficiently broad pytest selection can exhaust
# MAX_REQUESTS_PER_IP_PER_HOUR purely from the suite's own combined
# request volume, spuriously failing whichever email-code test happens to
# run once the shared budget is gone (this is exactly what made
# test_email_code_auth.py's rate-limit tests order/selection-dependent -
# see WALKTHROUGH_FINDINGS_2026-08.md item 47). Autouse + function-scoped:
# every test starts with a guaranteed-clean rate-limit slate, so the
# result no longer depends on what ran before it or how broad -k was.
@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limit_state():
    """Clears BOTH Redis-backed limiters before every test.

    `otp:*` is auth_service's email-code limiter (the original reason this
    fixture exists). `rl:*` is services/rate_limit.py's per-minute burst
    limiter, added 2026-09-01 — it has exactly the same problem and would
    otherwise reintroduce the exact order-dependence this fixture was written
    to remove: every test client shares one source "IP", so the per-IP buckets
    accumulate across every test in the run, and a later test fails with 429
    for reasons that have nothing to do with its own logic. Per-tenant buckets
    are keyed by a fresh uuid per test and would not collide, but they are
    cleared too rather than relying on that.
    """
    import services.auth_service as auth_service
    redis = auth_service._redis()
    for pattern in ("otp:*", "rl:*"):
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
    yield

# ── RLS-aware test sessions ──────────────────────────────────────────────────
# Every tenant-scoped table is protected by Row-Level Security (migration
# b7d419e3f2a8), and the policy reads `app.current_tenant_id`, set per
# transaction from a ContextVar. In the running app that ContextVar is
# populated by TenantContextMiddleware (HTTP) or the Celery task wrappers
# (background) — neither of which exists when a test seeds rows directly.
#
# So a bare `AsyncSessionLocal()` in a test has no tenant, and RLS correctly
# refuses the write ("new row violates row-level security policy"). Use
# `services.tenant_context.tenant_session(tenant_id)` instead: it opens a
# session already inside that tenant's context, which is the same path
# production takes. It lives in services/ rather than here because conftest is
# a pytest plugin, not an importable module.
#
# Deliberately NOT solved by pointing the test suite at the superuser role.
# That would make everything pass while proving nothing — RLS would be bypassed
# in every test, and a regression dropping tenant context would go unnoticed.
# test_rls_cross_tenant.py depends on the suite genuinely running under RLS.
