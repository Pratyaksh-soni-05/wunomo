"""HMAC verification, raw-body size cap, and replay protection for the
GitHub CI/CD webhook (Security Master Ranking Item #16).

Secrets are per-pipeline, never global -- see api/v1/cicd.py's own webhook
docstring for why a single shared secret is wrong for this product
specifically (every tenant who connects a repo would hold a value capable
of forging another tenant's deployment events). Every rejection path here
raises the same exception type; the route catches it once and returns the
identical generic body regardless of which reason fired, so a caller can
never learn from the response alone whether a pipeline exists, has a
secret configured, or just failed the signature check.
"""
import asyncio
import hashlib
import hmac
from typing import Optional

from redis import asyncio as aioredis
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


def verify_signature(raw_body: bytes, signature_header: Optional[str], secret: str) -> None:
    """Must be called with the RAW bytes read off the request, before any
    JSON parsing -- verifying a re-serialized body would validate a
    signature against bytes GitHub never actually signed."""
    if not signature_header or not signature_header.startswith("sha256="):
        raise WebhookRejected("missing_or_malformed_signature_header")
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


async def check_replay(delivery_id: Optional[str]) -> None:
    """Raises WebhookRejected if this exact X-GitHub-Delivery id was
    already processed within REPLAY_TTL_SECONDS.

    A missing delivery id is NOT rejected on its own -- GitHub always sends
    one in practice, but treating "no id, so dedup can't run" as a hard
    failure would make this check load-bearing for every delivery; the
    signature remains the real gate either way, this only narrows the
    window a captured-and-replayed valid signature stays useful.
    """
    if not delivery_id:
        return
    redis = _redis()
    key = f"{_REPLAY_KEY_PREFIX}:{delivery_id}"
    # SET ... NX is atomic — only the first caller to reach this exact key
    # gets a True back, so two near-simultaneous deliveries with the same
    # id can't both slip through a non-atomic "check then set".
    first_seen = await redis.set(key, "1", nx=True, ex=REPLAY_TTL_SECONDS)
    if not first_seen:
        raise WebhookRejected("replay")
