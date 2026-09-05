"""JWT revocation: per-token blocklist and per-user token epoch.

    WHY THIS EXISTS WHEN get_current_user ALREADY RE-READS THE USER
    ---------------------------------------------------------------
    get_current_user re-reads is_active/role from the database on every
    request, which already closes the original Item #4 exploit (a token
    captured before removal is rejected afterwards — verified against the
    pre-fix commit, where it returned 200). This module covers what that
    per-request read structurally cannot:

      * revoking ONE stolen token while the user stays legitimately active —
        nothing about the user row changes, so re-reading it proves nothing
      * "log out all devices" — no mechanism existed at all
      * revocation that also applies BEFORE authentication runs, so a revoked
        token cannot set an RLS tenant context or consume a rate-limit bucket
        on its way to being rejected

TWO MECHANISMS, DELIBERATELY

`jti` blocklist — revokes one specific token. Keyed by the token's own id,
with a TTL set to that token's remaining lifetime, so an entry never outlives
the token it blocks and the keyspace cannot grow without bound.

Token epoch — revokes every token a user currently holds. A single integer per
user; a token is valid only if it was issued at or after the user's current
epoch. Bumping the counter invalidates every previously-issued token at once.

The epoch is why "log out all devices" is cheap. The alternative — recording
every issued jti so they can all be blocklisted later — needs a per-user set
that grows with every login and must be reconciled on expiry. One counter does
the same job in O(1) with no bookkeeping.

    FAIL-OPEN IS DELIBERATE, AND IS THE ONE JUDGEMENT CALL HERE
    -----------------------------------------------------------
    If Redis is unreachable, `is_revoked()` returns False — the token is
    treated as valid. That is a real, conscious trade: a Redis outage would
    otherwise 401 every authenticated request in the product simultaneously,
    turning a cache outage into a total outage.

    It is defensible ONLY because this module is defence-in-depth rather than
    the primary control: removal and demotion are still caught by
    get_current_user's database read, which does not depend on Redis. What is
    lost during a Redis outage is narrower — a specifically-revoked token, or
    a "log out all devices", stops being enforced until Redis returns.

    If revocation ever becomes the primary control (for example if the
    per-request DB read is removed as an optimisation), this must be revisited:
    at that point failing open would mean a Redis outage silently disables
    authentication enforcement entirely.
"""

import asyncio
import time
from typing import Optional

from redis import asyncio as aioredis

from config import settings

# Distinct prefixes so the test-isolation fixture can clear them, and so an
# operator can see at a glance which keys are revocation state. `rl:` is the
# rate limiter's; `otp:` is auth_service's email-code limiter.
BLOCKLIST_PREFIX = "revoked:jti"
EPOCH_PREFIX = "revoked:epoch"

# A token epoch has no natural expiry: it must outlive every token issued
# before it, and a user may not log in again for a long time. Bounded anyway so
# an abandoned account's key is eventually reclaimed — well beyond any token's
# 60-minute life, so it can never expire while a token it should block is still
# valid.
EPOCH_TTL_SECONDS = 90 * 24 * 3600  # 90 days


_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    """Lazy, loop-aware singleton — same pattern as auth_service and
    rate_limit, and for the same reason: a `redis.asyncio` client created at
    import time binds to whichever event loop exists then and raises
    "Event loop is closed" the first time a different loop uses it. Invisible
    in the app (one loop per process), fatal across pytest-asyncio's loops."""
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


# ── Per-token revocation ─────────────────────────────────────────────────────

async def revoke_jti(jti: str, exp: Optional[int]) -> None:
    """Blocklist one token until it would have expired anyway.

    `exp` is the token's own `exp` claim (unix seconds). The TTL is the real
    remaining lifetime, so the entry disappears exactly when the token stops
    being dangerous — a fixed TTL would either expire early (re-enabling a
    revoked token) or linger for nothing.
    """
    if not jti:
        return
    ttl = int(exp - time.time()) if exp else 0
    if ttl <= 0:
        # Already expired: the JWT layer rejects it regardless, so a blocklist
        # entry would be dead weight.
        return
    try:
        await _redis().set(f"{BLOCKLIST_PREFIX}:{jti}", "1", ex=ttl)
    except Exception:
        # See the module docstring on fail-open.
        pass


# ── Per-user revocation (all devices) ────────────────────────────────────────

async def current_epoch(user_id: str) -> int:
    """The user's current token epoch. 0 when never revoked, which is also the
    value every token issued before this feature carries."""
    try:
        raw = await _redis().get(f"{EPOCH_PREFIX}:{user_id}")
        return int(raw) if raw else 0
    except Exception:
        return 0


async def bump_epoch(user_id: str) -> int:
    """Invalidate every token this user currently holds. Returns the new epoch.

    INCR is atomic, so two concurrent revocations cannot land on the same value
    and leave one caller believing it revoked when it did not.
    """
    key = f"{EPOCH_PREFIX}:{user_id}"
    try:
        new_epoch = await _redis().incr(key)
        await _redis().expire(key, EPOCH_TTL_SECONDS)
        return int(new_epoch)
    except Exception:
        return 0


# ── The check ────────────────────────────────────────────────────────────────

async def is_revoked(payload: dict) -> bool:
    """True if this token has been revoked, individually or by epoch bump.

    Takes the decoded payload rather than the raw token so callers that have
    already decoded (all three of them) do not pay for a second decode.
    """
    try:
        jti = payload.get("jti")
        if jti and await _redis().exists(f"{BLOCKLIST_PREFIX}:{jti}"):
            return True

        user_id = payload.get("sub")
        if not user_id:
            return False

        # A token minted before its user's current epoch is stale. `>=` not `>`:
        # a token issued in the same epoch as the current one is valid, and
        # bump_epoch() moves to a NEW epoch that no existing token carries.
        token_epoch = int(payload.get("epoch") or 0)
        return token_epoch < await current_epoch(user_id)
    except Exception:
        # See the module docstring: a Redis outage must not 401 the product.
        return False
