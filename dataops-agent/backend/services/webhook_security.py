"""HMAC verification, raw-body size cap, and replay protection for the
GitHub CI/CD webhook (Security Master Ranking Item #16).

Secrets are per-pipeline, never global -- see api/v1/cicd.py's own webhook
docstring for why a single shared secret is wrong for this product
specifically (every tenant who connects a repo would hold a value capable
of forging another tenant's deployment events). Every WebhookRejected
reason gets the identical generic 401 body from the route, so a caller
can never learn from the response alone whether a pipeline exists, has a
secret configured, or just failed the signature check. ReplayCheckUnavailable
is the one deliberate exception to "identical body": Redis being down is
a 503, not a 401, because it is a different kind of fact (infrastructure,
not the caller's own request) and fails CLOSED -- see
ReplayCheckUnavailable's own docstring for why.
"""
import asyncio
import hashlib
import hmac
from typing import Optional

from redis import asyncio as aioredis
from redis.exceptions import RedisError
import structlog

from config import settings

log = structlog.get_logger()

# GitHub's own webhook payload limit is 25 MB, but every push this app
# actually processes (a pipeline-definition-file change, a handful of
# commits) is a few KB. Capping here means a payload sent purely to burn
# CPU on the HMAC hash never gets that far.
MAX_WEBHOOK_BODY_BYTES = 1 * 1024 * 1024  # 1 MB

# Comfortably longer than GitHub's own redelivery window (a stuck delivery
# is typically retried within minutes, not hours), short enough that the
# Redis key space this creates doesn't grow without bound.
REPLAY_TTL_SECONDS = 6 * 60 * 60

_REPLAY_KEY_PREFIX = "webhook:delivery"


class WebhookRejected(Exception):
    """Raised for any rejection reason. `reason` is for logging only --
    never surfaced in the HTTP response, which must stay identical across
    every reason so the signature's own secrecy is the only thing a
    caller's probing can run into."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def enforce_body_size(raw_body: bytes) -> None:
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise WebhookRejected("body_too_large")


def check_signature_header_shape(signature_header: Optional[str]) -> None:
    """Pure shape check, no secret needed -- factored out so the cheap,
    database-free rejection pass below and verify_signature (which does
    need the secret) share one definition of "malformed" rather than two
    that could drift."""
    if not signature_header or not signature_header.startswith("sha256="):
        raise WebhookRejected("missing_or_malformed_signature_header")


def enforce_cheap_rejections(
    raw_body: bytes, signature_header: Optional[str], delivery_id: Optional[str],
) -> None:
    """Every rejection that needs neither a database round trip nor the
    per-pipeline secret, checked first so a malformed, oversized, or
    clearly-non-GitHub request never costs a query. A missing delivery id
    is rejected here (not silently tolerated) -- GitHub always sends
    X-GitHub-Delivery in practice, and accepting a request that omits it
    would mean replay protection could never apply to that caller at all,
    for free, which is a worse trade than a flat rejection."""
    check_signature_header_shape(signature_header)
    enforce_body_size(raw_body)
    if not delivery_id:
        raise WebhookRejected("missing_delivery_id")


def verify_signature(raw_body: bytes, signature_header: Optional[str], secret: str) -> None:
    """Must be called with the RAW bytes read off the request, before any
    JSON parsing -- verifying a re-serialized body would validate a
    signature against bytes GitHub never actually signed."""
    check_signature_header_shape(signature_header)
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookRejected("signature_mismatch")


# Lazy, loop-aware singleton against the app's existing REDIS_URL -- same
# pattern and same reason as services/rate_limit.py's _redis() and
# auth_service._redis(): a client created at import time binds to whatever
# event loop exists then and dies with "Event loop is closed" the first
# time a different loop uses it, which is invisible in the real app (one
# loop per process) but fatal across pytest-asyncio's loop boundaries.
_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


class ReplayCheckUnavailable(Exception):
    """Raised when check_replay cannot reach Redis at all. The route turns
    this into a 503 (generic body, no mention of Redis) rather than
    treating "no replay protection available" as "let it through".

    Reversed from an earlier fail-open design once it became clear what a
    replay actually does downstream: a successfully-processed push can
    reach services/cicd_deployment.py's deploy_pipeline (a real
    activate_pipeline call, a second PipelineDeployment superseding the
    first) -- not a cheaply-repeatable action like a token check, and not
    recoverable by just trying again. Failing closed here is recoverable
    the other way instead: GitHub redelivers on its own, and this request
    is simply rejected (503, not the signature's own 401) until Redis is
    back. See docs/context/GOTCHAS.md's Item #16 entry for the full
    fail-open-vs-fail-closed principle this follows.
    """


async def check_replay(delivery_id: Optional[str]) -> None:
    """Raises WebhookRejected("replay") if this exact X-GitHub-Delivery id
    was already processed within REPLAY_TTL_SECONDS. Raises
    ReplayCheckUnavailable if Redis itself cannot be reached -- never
    silently treats that as "no replay possible, proceed".

    A missing delivery id is NOT rejected here -- the route's own
    enforce_cheap_rejections already turns that into a hard 401 before
    this is ever reached. This defensive no-op stays for any other
    caller of this function that doesn't go through that pre-check.
    """
    if not delivery_id:
        return
    try:
        redis = _redis()
        key = f"{_REPLAY_KEY_PREFIX}:{delivery_id}"
        # SET ... NX is atomic — only the first caller to reach this exact
        # key gets a True back, so two near-simultaneous deliveries with
        # the same id can't both slip through a non-atomic "check then set".
        first_seen = await redis.set(key, "1", nx=True, ex=REPLAY_TTL_SECONDS)
    except (RedisError, OSError) as exc:
        raise ReplayCheckUnavailable(str(exc)) from exc
    if not first_seen:
        raise WebhookRejected("replay")


async def release_replay(delivery_id: Optional[str]) -> None:
    """Deletes the replay-dedup key for this delivery id. Called when
    something fails AFTER check_replay has already marked the id seen but
    BEFORE the resulting PipelineCommit is actually persisted -- without
    this, a GitHub redelivery of the exact same push (same
    X-GitHub-Delivery, which is what a redelivery is) would be rejected
    as a replay for the rest of REPLAY_TTL_SECONDS even though nothing
    was ever actually recorded for it.

    Best-effort: a failure here is logged, never raised -- letting a
    release failure mask the real error that triggered it would be worse
    than just leaving the key in place for this one delivery.
    """
    if not delivery_id:
        return
    try:
        await _redis().delete(f"{_REPLAY_KEY_PREFIX}:{delivery_id}")
    except (RedisError, OSError) as exc:
        log.warning("cicd.webhook_replay_release_failed", delivery_id=delivery_id, error=str(exc))
