"""Per-minute burst rate limiting. Distinct from quota — do not conflate them.

    QUOTA (services/quota_service.py)   RATE LIMIT (this module)
    monthly ai_credits per plan tier    per-minute request bursts
    team-scaled, checked before an LLM  independent of quota remaining
    call, returns 402 quota_exceeded    returns 429 + Retry-After
    business/billing concern            abuse and brute-force protection

A tenant with plenty of monthly credits left can still be rate limited, and a
tenant at their monthly cap gets 402 rather than 429. The two never substitute
for each other.

WHY THESE NUMBERS ARE NOT DERIVED FROM CREDITS

The original design called for deriving requests/min from each tier's
`credits_per_day_per_user`. That derivation degenerates: using only the
grounded figure of 5,108 credits per real `agent_chat` LLM call (n=76 measured
events), Standard's entire 24,990-credit monthly cap buys 4.9 LLM calls — so
every tier's derived rate floors to the same 1 request/minute and the tiers
stop differing at all, which is the one property the limits need. See
GOTCHAS.md's entry on the credit-cap magnitude gap; that is an open pricing
question, not something to paper over by inventing a scaling constant here.

So the AXIOM limits below are set directly, as defensible burst protection,
and are explicitly PROVISIONAL: once real credit caps exist after dogfooding,
this is worth revisiting as a genuine credit-derived calculation.

WINDOW SEMANTICS

A fixed window (INCR + EXPIRE), matching the mechanism auth_service already
uses for the email-code limiter rather than introducing a second, different
one. A fixed window permits up to 2x the limit across a window boundary — for
burst protection at these magnitudes that is acceptable, and the simplicity is
worth more than the precision of a sliding log.
"""

import asyncio
import time
from typing import Optional

from redis import asyncio as aioredis

from config import settings

# All keys share this prefix so the test suite can clear them wholesale. See
# GOTCHAS.md #22: Redis state outlives a test run, and a rate-limit counter
# left over from a previous run makes a later test fail for reasons that have
# nothing to do with its own logic.
KEY_PREFIX = "rl"

WINDOW_SECONDS = 60


# ── Limits ───────────────────────────────────────────────────────────────────

# AXIOM chat/task endpoints, per tenant per minute. Provisional; see the module
# docstring for why these are not credit-derived.
#
# Sizing rationale: a real chat turn takes 1.1-2.8s end to end on
# gemini-3.5-flash (measured, see GOTCHAS), so a human at a keyboard sustains
# perhaps 2-5 requests/minute. Every value here sits well above genuine
# interactive use and well below what a script needs to be useful. They are
# per-TENANT, not per-user, so the higher tiers buy headroom for a whole team
# sharing one tenant rather than a faster individual.
AXIOM_RPM_BY_PLAN = {
    "standard":     10,   # ~1 request/6s sustained: ~2-5x real single-user pace
    "starter_plus": 15,   # same shape as standard, modest headroom for the paid step up
    "premium":      30,   # a small team (up to 15 seats) working concurrently
    "enterprise":   60,   # 1/s sustained; unlimited seats, plus room for automation
}
# Used when a tenant's plan cannot be resolved. Deliberately the *most*
# restrictive tier rather than the most generous: an unresolvable plan is an
# anomaly, and the failure mode should be a slow tenant, never a free pass.
AXIOM_RPM_FALLBACK = AXIOM_RPM_BY_PLAN["standard"]

# Everything else authenticated, per tenant per minute. The real UI fans out
# ~7 calls on a dashboard load, so 120 leaves an order of magnitude of headroom
# for legitimate page loads while stopping a scripted hammer.
DEFAULT_RPM_PER_TENANT = 120

# Pipeline runs, transformations, sandboxed execution. Tighter than the default
# because each one spawns real Celery work or runs generated code through
# python_runner's `exec()` sandbox — which its own docstring says is "sufficient"
# only for already-LLM-validated code, not untrusted input (GOTCHAS). Cost and
# blast radius per request are both far higher here than for a page load.
EXPENSIVE_RPM_PER_TENANT = 10

# Pre-authentication endpoints, per IP per minute. A credential-stuffing or
# brute-force run needs thousands of attempts to be worth anything; 10/min makes
# it useless. A human who mistypes a password three times never notices.
#
# NOT applied to the email-code endpoints: auth_service already rate limits
# those (5/email/hour, 20/IP/hour, 60s cooldown, 30min lockout after 3
# exhaustions). Stacking a second limiter on the same flow would double-count.
PREAUTH_RPM_PER_IP = 10

# Backstop for unauthenticated traffic on any other path, per IP per minute.
# Higher than the per-tenant default because one IP can legitimately carry
# several users (office NAT, shared egress), and this exists to stop a flood
# before it reaches auth or the database, not to be the primary control.
UNAUTH_BACKSTOP_RPM_PER_IP = 240


# ── Path categorisation ──────────────────────────────────────────────────────
#
# Prefix-based, not per-route decorators. There are 126 routes; decorating each
# one means a new route silently ships with no limit, and the reviewer has 126
# places to check instead of one table.

# Strict, IP-keyed, tier-independent.
PREAUTH_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    # Item #13: the MFA second step is pre-auth and a natural guessing target;
    # same per-IP bucket as login, plus a per-challenge attempt cap in
    # services/mfa_service.py.
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/password-reset",
    "/api/v1/auth/forgot-password",
)

# Tier-aware, tenant-keyed.
AXIOM_PATHS = (
    "/api/v1/chat",
    "/api/v1/tasks",
)

# Tight, tenant-keyed.
EXPENSIVE_PATHS = (
    "/api/v1/transformations",
    "/api/v1/uploads",
)
# Substring matches, for the run-triggering routes that sit under a broader
# prefix (e.g. /api/v1/pipelines/{id}/run) and cannot be matched by prefix alone.
EXPENSIVE_SUBSTRINGS = (
    "/run",
    "/trigger",
    "/profile",
    "/sync",
    "/advance",
)

# Never rate limited: liveness/readiness probes must answer under load, and
# rate-limiting them turns a traffic spike into a false "service is down".
EXEMPT_PATHS = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class RateLimitCategory:
    EXEMPT = "exempt"
    PREAUTH = "preauth"
    AXIOM = "axiom"
    EXPENSIVE = "expensive"
    DEFAULT = "default"


def categorise(path: str) -> str:
    """Which limit bucket a request path falls into. Order matters: the most
    specific and most restrictive categories are tested first."""
    if any(path.startswith(p) for p in EXEMPT_PATHS):
        return RateLimitCategory.EXEMPT
    if any(path.startswith(p) for p in PREAUTH_PATHS):
        return RateLimitCategory.PREAUTH
    if any(path.startswith(p) for p in EXPENSIVE_PATHS):
        return RateLimitCategory.EXPENSIVE
    if any(s in path for s in EXPENSIVE_SUBSTRINGS):
        return RateLimitCategory.EXPENSIVE
    if any(path.startswith(p) for p in AXIOM_PATHS):
        return RateLimitCategory.AXIOM
    return RateLimitCategory.DEFAULT


# ── Redis ────────────────────────────────────────────────────────────────────

_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    """Lazy, loop-aware singleton against the app's existing REDIS_URL.

    Not a module-level global: a `redis.asyncio` client created at import time
    binds to whatever event loop exists then and dies with
    "Event loop is closed" the first time a different loop uses it — invisible
    in the real app (one loop per process) but fatal across pytest-asyncio's
    loop boundaries. Same pattern and same reason as auth_service._redis().
    """
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


async def check_rate_limit(bucket: str, identifier: str, limit: int,
                           window_seconds: int = WINDOW_SECONDS) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds).

    `retry_after` is the real remaining TTL of the current window, not a
    constant — a caller told to retry in 60s when the window resets in 3s wastes
    57 seconds, and one told 60s when it resets in 60s retries exactly once.
    """
    key = f"{KEY_PREFIX}:{bucket}:{identifier}"
    redis = _redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count <= limit:
        return True, 0
    ttl = await redis.ttl(key)
    # A missing/expired TTL (-1 = no expiry set, -2 = key gone) would otherwise
    # surface as a negative Retry-After. Fall back to the full window.
    return False, ttl if ttl and ttl > 0 else window_seconds


def rpm_for_plan(plan: Optional[str]) -> int:
    """AXIOM requests/minute for a plan key, falling back to the most
    restrictive tier when the plan is unknown or missing."""
    return AXIOM_RPM_BY_PLAN.get(plan or "", AXIOM_RPM_FALLBACK)
