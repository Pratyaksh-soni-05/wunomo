"""Wunomo Projects Phase 3, slice 10: per-task advisory locking.

execute_next_step() opens its own AsyncSessionLocal(), reads Task/
TaskStep state, and only commits after mutating it -- with no row lock
of any kind. Two concurrent calls on the same task_id (a beat tick and a
human's manual /advance click, or two overlapping ticks) can both read
the same step as PENDING before either commits, and both proceed to
call that step's tool -- a genuine double-execution race that existed
before auto-advance was ever built (see WALKTHROUGH_FINDINGS_2026-08.md
item 73: two overlapping human /advance clicks already hit this). Auto-
advance just makes it certain to be hit routinely instead of rarely.

Same shape as services/source_lock.py (Redis advisory lock, short TTL
refreshed while work is in flight, a hard ceiling that force-expires),
deliberately a sibling module rather than a generalization of it: this
lock has no holder identity worth describing to a denied caller (unlike
a source lock, nobody needs to be told "in use by Nova" here) -- the
denied caller, whether a beat tick or a human click, just backs off and
tries again next cycle. Fails fast, never queues.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from redis import asyncio as aioredis

from config import settings

log = structlog.get_logger()

LOCK_KEY_PREFIX = "task_lock:"

# Same parameters as services/source_lock.py, for the same reasons --
# see that module's own comments. TTL is the crash-safety net, not the
# primary release path; the lock is actively released in a finally
# block on every normal exit and exception.
BASE_TTL_SECONDS = 30
REFRESH_INTERVAL_SECONDS = 10
HARD_CEILING_SECONDS = 300

_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


def _lock_key(task_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}{task_id}"


class TaskLockHeld(Exception):
    """Raised when another caller (a beat tick, or a concurrent human
    /advance click) already holds task_id's lock. No holder identity to
    carry -- the denied caller just backs off, there's nothing to show
    a user beyond "try again shortly"."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task {task_id} is already being advanced by another caller.")


@asynccontextmanager
async def acquire_task_lock(task_id: str):
    """Advisory lock keyed on task_id. Raises TaskLockHeld immediately if
    another caller already holds it; never blocks or queues. Held for
    the full duration of one execute_next_step() call, including its
    internal retry-backoff sleeps, so a beat tick and a human click (or
    two overlapping ticks) can never both act on the same task's current
    step at once."""
    import uuid

    token = str(uuid.uuid4())
    acquired = await _redis().set(_lock_key(task_id), token, nx=True, ex=BASE_TTL_SECONDS)
    if not acquired:
        raise TaskLockHeld(task_id)

    stop = asyncio.Event()

    async def _refresher():
        elapsed = 0
        while elapsed < HARD_CEILING_SECONDS:
            try:
                await asyncio.wait_for(stop.wait(), timeout=REFRESH_INTERVAL_SECONDS)
                return
            except asyncio.TimeoutError:
                pass
            elapsed += REFRESH_INTERVAL_SECONDS
            current = await _redis().get(_lock_key(task_id))
            if current != token:
                log.warning("task_lock_lost_before_refresh", task_id=task_id)
                return
            await _redis().expire(_lock_key(task_id), BASE_TTL_SECONDS)
        log.error("task_lock_hard_ceiling_exceeded", task_id=task_id, ceiling_seconds=HARD_CEILING_SECONDS)

    refresher_task = asyncio.create_task(_refresher())
    try:
        yield
    finally:
        stop.set()
        await refresher_task
        current = await _redis().get(_lock_key(task_id))
        if current == token:
            await _redis().delete(_lock_key(task_id))
