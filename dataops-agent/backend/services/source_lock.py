"""Wunomo Projects Phase 2, item 5: per-source advisory locking.

Nova and Atlas (or a scheduled pipeline run) can all call sync_source on
the same source_id today with nothing stopping them from racing each
other -- see WUNOMO_PROJECTS_PROPOSAL_v2.md's "worked in testing" framing
("Two agents cannot run the same source at once"). A Redis advisory lock
closes that: whoever holds source_lock:{source_id} is the only caller
allowed to touch that source's real connection until it releases.

Two chokepoints hold this lock (both apply it, neither is consolidated
onto the other in this pass -- see CLAUDE.md Hard Rule 1's already-logged
exception and GOTCHAS.md for why python_runner.py/sql_runner.py build
their own connections independently of PostgresConnector; consolidating
them is its own follow-up item, not bundled into this one):
  - modules/ingestion/connector_manager.py (ConnectorManager.sync/preview)
    and modules/ingestion/schema_profiler.py (SchemaProfiler.profile/
    detect_drift) -- covers ingestion tool calls, task steps, and Celery
    pipeline runs, since all three funnel into these same methods.
  - modules/transformation/python_runner.py's _load_dataframe and
    sql_runner.py's run_on_source -- covers transformation tool calls,
    which bypass ConnectorManager entirely.

Deliberately fails fast, never queues/blocks: the caller decides what
"denied" means for its own context --
  - chat (agent_node's synchronous tool call): the error dict returned
    here surfaces straight to the LLM/user, which IS fail-fast.
  - a task step (task_executor.py's _call_tool): catches SourceLockHeld
    and pauses the step (TaskStatus.PAUSED_SOURCE_LOCKED, the same
    pause/resume shape as quota_paused_attempt) instead of failing it --
    resumption naturally retries once the lock frees.
  - Celery (services/tasks.py's _execute_run): already raises+retries
    (max_retries=3, default_retry_delay=60) on any {"error": ...} result,
    and the next 60s beat tick re-checks the schedule regardless -- no
    new code needed there, a lock conflict is just another sync failure
    to that existing mechanism.
"""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import structlog
from redis import asyncio as aioredis

from config import settings

log = structlog.get_logger()

LOCK_KEY_PREFIX = "source_lock:"

# Short base TTL, refreshed every REFRESH_INTERVAL_SECONDS while work is
# genuinely still in flight (see the refresher loop below) -- NOT the
# primary release mechanism. The lock is actively released in the
# finally block on every normal exit and every exception, exactly like
# any other try/finally. TTL only matters when release itself never runs
# at all (a SIGKILL, an OOM kill) -- try/finally cannot survive that,
# Redis's own key expiry can. Treat TTL purely as the crash-safety net.
BASE_TTL_SECONDS = 30
REFRESH_INTERVAL_SECONDS = 10

# A real sync/profile/transform pass still running after this long is a
# bug (a hung connector, a runaway query) -- not a workload this lock
# should accommodate by refreshing indefinitely. Refreshing stops here
# and the lock is left to expire on its own TTL; the run itself is left
# to fail or finish on its own, only the LOCK stops protecting it. This
# is surfaced loudly (log.error) specifically because it should never
# happen in normal operation.
HARD_CEILING_SECONDS = 300

_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    # Lazy singleton, not a module-level client built at import time --
    # same pattern as services/auth_service.py's own _redis() and
    # services/model_liveness.py's copy of it, for the identical reason
    # (binding to whatever event loop happens to exist at import time
    # breaks across pytest-asyncio's test/loop boundaries).
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


def _lock_key(source_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}{source_id}"


class SourceLockHeld(Exception):
    """Raised when another caller already holds source_id's lock. Carries
    the raw holder identity (agent_id, possibly None for a Celery-
    triggered scheduled run, plus the ISO timestamp it acquired the lock)
    -- resolving agent_id into a human-readable name ("Nova") is the
    caller's job via describe_holder(), since this module has no DB
    session of its own and shouldn't need one just to fail fast."""

    def __init__(self, source_id: str, holder_agent_id: Optional[str], started_at_iso: str):
        self.source_id = source_id
        self.holder_agent_id = holder_agent_id
        self.started_at_iso = started_at_iso
        super().__init__(f"Source {source_id} is already locked (since {started_at_iso}).")


async def describe_holder(db, agent_id: Optional[str]) -> str:
    """Resolves a lock's holder_agent_id into the human-readable label a
    denial message should show. None means the holder is a Celery-
    triggered scheduled pipeline run, not any particular agent."""
    if agent_id is None:
        return "a scheduled pipeline run"
    from models.all_models import AgentInstance
    agent = await db.get(AgentInstance, agent_id)
    return agent.name if agent else agent_id


def format_lock_denial(source_id: str, holder_label: str, started_at_iso: str) -> str:
    """'in use by Nova since 09:14' -- never the bare word "locked"."""
    try:
        started = datetime.fromisoformat(started_at_iso).strftime("%H:%M UTC")
    except ValueError:
        started = started_at_iso
    return f"This source is currently in use by {holder_label} (since {started})."


@asynccontextmanager
async def acquire_source_lock(source_id: str, agent_id: Optional[str]):
    """Advisory lock keyed on source_id -- see this module's docstring for
    the full design. Raises SourceLockHeld immediately if another caller
    already holds it; never blocks or queues."""
    token = str(uuid.uuid4())
    started_at_iso = datetime.now(timezone.utc).isoformat()
    value = json.dumps({"agent_id": agent_id, "started_at": started_at_iso, "token": token})

    acquired = await _redis().set(_lock_key(source_id), value, nx=True, ex=BASE_TTL_SECONDS)
    if not acquired:
        existing = await _redis().get(_lock_key(source_id))
        holder = json.loads(existing) if existing else {}
        raise SourceLockHeld(
            source_id,
            holder.get("agent_id"),
            holder.get("started_at", datetime.now(timezone.utc).isoformat()),
        )

    stop = asyncio.Event()

    async def _refresher():
        elapsed = 0
        while elapsed < HARD_CEILING_SECONDS:
            try:
                await asyncio.wait_for(stop.wait(), timeout=REFRESH_INTERVAL_SECONDS)
                return  # the protected work finished; stop() was set below
            except asyncio.TimeoutError:
                pass
            elapsed += REFRESH_INTERVAL_SECONDS
            current = await _redis().get(_lock_key(source_id))
            if current is None or json.loads(current).get("token") != token:
                log.warning("source_lock_lost_before_refresh", source_id=source_id, agent_id=agent_id)
                return
            await _redis().expire(_lock_key(source_id), BASE_TTL_SECONDS)
        log.error(
            "source_lock_hard_ceiling_exceeded", source_id=source_id, agent_id=agent_id,
            ceiling_seconds=HARD_CEILING_SECONDS,
        )

    refresher_task = asyncio.create_task(_refresher())
    try:
        yield
    finally:
        stop.set()
        await refresher_task
        current = await _redis().get(_lock_key(source_id))
        if current and json.loads(current).get("token") == token:
            await _redis().delete(_lock_key(source_id))
