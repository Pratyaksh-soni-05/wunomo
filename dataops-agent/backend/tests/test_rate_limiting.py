"""Per-minute burst rate limiting (Security Master Ranking Item #3).

Rate limiting and quota are separate systems and these tests keep them separate:
a 429 here means "too fast", never "out of monthly credits" (which is a 402 from
quota_service). Nothing in this file touches quota.

The isolation test is the point of the exercise. Redis keys are the same class
of shared-namespace hazard that RLS closed for database rows: one tenant
exhausting a bucket must not consume another tenant's, and a bug that keyed on
something global would look completely fine until two tenants used the product
at once.
"""
import uuid

import pytest

from services.rate_limit import (
    AXIOM_RPM_BY_PLAN, DEFAULT_RPM_PER_TENANT, EXPENSIVE_RPM_PER_TENANT,
    KEY_PREFIX, PREAUTH_RPM_PER_IP, RateLimitCategory, categorise,
    check_rate_limit, rpm_for_plan,
)
from services.tenant_context import async_tenant_context, tenant_session
from database import AsyncSessionLocal
from models.all_models import Tenant, User
from services.auth_service import hash_password, issue_token_for_user


async def _make_tenant(plan: str) -> tuple[str, str]:
    """A real tenant + owner on `plan`, returning (tenant_id, bearer token)."""
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    async with async_tenant_context(tenant_id), AsyncSessionLocal() as db:
        db.add(Tenant(id=tenant_id, name=f"RL {tenant_id[:8]}",
                      slug=f"rl-{tenant_id[:8]}", plan=plan))
        await db.flush()
        user = User(
            id=user_id, tenant_id=tenant_id,
            email=f"rl-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"),
            role="owner", is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = issue_token_for_user(user, "password")
    return tenant_id, token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Path categorisation ──────────────────────────────────────────────────────

def test_paths_map_to_the_intended_limit_buckets():
    """Categorisation is prefix-based across 126 routes, so a mistake here
    silently mis-limits whole families of endpoints."""
    assert categorise("/health") == RateLimitCategory.EXEMPT
    assert categorise("/api/v1/auth/login") == RateLimitCategory.PREAUTH
    assert categorise("/api/v1/auth/register") == RateLimitCategory.PREAUTH
    assert categorise("/api/v1/chat/") == RateLimitCategory.AXIOM
    assert categorise("/api/v1/tasks/") == RateLimitCategory.AXIOM
    assert categorise("/api/v1/transformations/run/sql") == RateLimitCategory.EXPENSIVE
    assert categorise("/api/v1/pipelines/abc/run") == RateLimitCategory.EXPENSIVE
    assert categorise("/api/v1/sources/abc/profile") == RateLimitCategory.EXPENSIVE
    assert categorise("/api/v1/sources/") == RateLimitCategory.DEFAULT
    assert categorise("/api/v1/incidents/") == RateLimitCategory.DEFAULT


def test_email_code_endpoints_are_not_double_limited():
    """auth_service already rate limits the email-code flow (5/email/hour,
    20/IP/hour, cooldown, lockout). Adding a second limiter on the same path
    would double-count and make the documented OTP behaviour wrong."""
    assert categorise("/api/v1/auth/email-code/request") != RateLimitCategory.PREAUTH


def test_unknown_plan_falls_back_to_the_most_restrictive_tier():
    """An unresolvable plan must throttle, never hand out a free pass."""
    assert rpm_for_plan(None) == AXIOM_RPM_BY_PLAN["standard"]
    assert rpm_for_plan("not-a-real-plan") == AXIOM_RPM_BY_PLAN["standard"]
    assert rpm_for_plan("enterprise") == AXIOM_RPM_BY_PLAN["enterprise"]


def test_tier_rpm_values_are_strictly_ordered():
    """If two tiers ever collide, the tier-differentiation test below can pass
    while actually proving nothing."""
    assert (AXIOM_RPM_BY_PLAN["standard"]
            <= AXIOM_RPM_BY_PLAN["starter_plus"]
            < AXIOM_RPM_BY_PLAN["premium"]
            < AXIOM_RPM_BY_PLAN["enterprise"])


# ── The primitive ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_limit_allows_up_to_the_cap_then_blocks_with_a_real_retry_after():
    ident = f"probe-{uuid.uuid4().hex[:8]}"
    for i in range(5):
        allowed, retry_after = await check_rate_limit("test", ident, 5)
        assert allowed is True, f"request {i + 1} of 5 should be allowed"
        assert retry_after == 0

    allowed, retry_after = await check_rate_limit("test", ident, 5)
    assert allowed is False
    # A real remaining TTL, not a hard-coded 60 — telling a caller to wait 60s
    # when the window resets in 3s wastes 57 seconds of their time.
    assert 0 < retry_after <= 60


@pytest.mark.asyncio
async def test_two_identifiers_do_not_share_a_bucket():
    a, b = f"a-{uuid.uuid4().hex[:8]}", f"b-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        assert (await check_rate_limit("test", a, 3))[0] is True
    assert (await check_rate_limit("test", a, 3))[0] is False
    # b is untouched by a's exhaustion.
    assert (await check_rate_limit("test", b, 3))[0] is True


# ── Tenant isolation, end to end through the real app ────────────────────────

@pytest.mark.asyncio
async def test_tenant_a_exhausting_its_limit_does_not_affect_tenant_b(client):
    """The Redis-key equivalent of the cross-tenant leak RLS closed."""
    tenant_a, token_a = await _make_tenant("standard")
    tenant_b, token_b = await _make_tenant("standard")

    # Drive tenant A past the expensive-category limit on a real endpoint.
    blocked_a = False
    for _ in range(EXPENSIVE_RPM_PER_TENANT + 3):
        r = await client.post(
            "/api/v1/transformations/run/sql",
            json={"source_id": "nope", "sql": "SELECT 1"}, headers=_auth(token_a),
        )
        if r.status_code == 429:
            blocked_a = True
            break
    assert blocked_a, "tenant A should have hit the expensive-category limit"

    # Tenant B's very next request must not be 429.
    r = await client.post(
        "/api/v1/transformations/run/sql",
        json={"source_id": "nope", "sql": "SELECT 1"}, headers=_auth(token_b),
    )
    assert r.status_code != 429, (
        "tenant B was rate limited by tenant A's traffic — the bucket is not "
        "keyed per tenant"
    )


@pytest.mark.asyncio
async def test_expensive_endpoints_are_tighter_than_the_general_default(client):
    """A transform or pipeline run spawns real Celery work or runs generated
    code through the exec() sandbox; it must not share the page-load budget."""
    assert EXPENSIVE_RPM_PER_TENANT < DEFAULT_RPM_PER_TENANT
    _, token = await _make_tenant("standard")

    statuses = []
    for _ in range(EXPENSIVE_RPM_PER_TENANT + 3):
        r = await client.post(
            "/api/v1/transformations/run/sql",
            json={"source_id": "nope", "sql": "SELECT 1"}, headers=_auth(token),
        )
        statuses.append(r.status_code)
    assert 429 in statuses
    # And it triggered at the tighter limit, not the default one.
    assert statuses.index(429) <= EXPENSIVE_RPM_PER_TENANT + 1


@pytest.mark.asyncio
async def test_429_carries_a_retry_after_header_and_leaks_no_config(client):
    _, token = await _make_tenant("standard")
    limited = None
    for _ in range(EXPENSIVE_RPM_PER_TENANT + 3):
        r = await client.post(
            "/api/v1/transformations/run/sql",
            json={"source_id": "nope", "sql": "SELECT 1"}, headers=_auth(token),
        )
        if r.status_code == 429:
            limited = r
            break
    assert limited is not None

    assert "retry-after" in {k.lower() for k in limited.headers}
    assert int(limited.headers["Retry-After"]) > 0

    body = limited.text.lower()
    assert "rate_limited" in body
    # No internal configuration in the response: the limit, the window, the
    # remaining count and the Redis key are all absent by design.
    for leak in ("redis", "rl:", "window", "per minute", "/min"):
        assert leak not in body, f"429 body leaked internal config: {leak!r}"
    assert str(EXPENSIVE_RPM_PER_TENANT) not in body


# ── Pre-auth, IP-keyed ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_repeated_login_attempts_are_rate_limited_by_ip(client):
    """Brute force needs thousands of attempts; this makes it useless. Keyed on
    IP, not on the submitted email — otherwise rotating the email defeats it."""
    statuses = []
    for i in range(PREAUTH_RPM_PER_IP + 4):
        r = await client.post("/api/v1/auth/login", json={
            "email": f"attacker-{i}@example.com", "password": "wrong-password",
        })
        statuses.append(r.status_code)

    assert 429 in statuses, f"login was never rate limited: {statuses}"
    assert statuses.index(429) <= PREAUTH_RPM_PER_IP + 1


@pytest.mark.asyncio
async def test_register_is_rate_limited_on_the_same_ip_bucket_as_login(client):
    """Both are pre-auth credential endpoints on one IP budget — otherwise an
    attacker alternates between them and doubles their effective allowance."""
    for i in range(PREAUTH_RPM_PER_IP):
        await client.post("/api/v1/auth/login", json={
            "email": f"drain-{i}@example.com", "password": "x"})

    r = await client.post("/api/v1/auth/register", json={
        "email": f"new-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Blocked", "tenant_name": "Blocked Co",
    })
    assert r.status_code == 429


# ── Tier differentiation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_standard_and_enterprise_tenants_get_different_axiom_limits(client):
    """The tiers must genuinely differ, not merely be configured to.

    Driven through the real middleware: an enterprise tenant is pushed past
    standard's limit and must still be served, which is only true if the
    middleware actually read its plan from the database.

    The request body is deliberately INVALID (no `message` field). The rate
    limiter is middleware, so it counts the request before FastAPI validates
    the body and long before the chat handler would call an LLM — the limiter
    is exercised for real while the request dies at 422 instead of spending
    Gemini/Groq quota. An earlier version of this test sent a valid body and
    made real LLM calls on every iteration, which is exactly the
    tests-cost-real-money trap documented in GOTCHAS.
    """
    _, standard_token = await _make_tenant("standard")
    _, enterprise_token = await _make_tenant("enterprise")

    standard_cap = AXIOM_RPM_BY_PLAN["standard"]

    standard_statuses = []
    for _ in range(standard_cap + 3):
        r = await client.post("/api/v1/chat/", json={},
                              headers=_auth(standard_token))
        standard_statuses.append(r.status_code)
    assert 429 in standard_statuses, "standard tenant was never limited"
    assert 422 in standard_statuses, (
        "expected the pre-limit requests to fail validation rather than reach "
        "the LLM — if this is not 422 the test may be spending real quota"
    )

    # The enterprise tenant sends the same volume that just blocked standard.
    enterprise_statuses = []
    for _ in range(standard_cap + 3):
        r = await client.post("/api/v1/chat/", json={},
                              headers=_auth(enterprise_token))
        enterprise_statuses.append(r.status_code)
    assert 429 not in enterprise_statuses, (
        "enterprise was limited at standard's rate — the middleware is not "
        "resolving the tenant's plan"
    )
