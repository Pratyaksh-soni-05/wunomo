"""Wunomo Projects Phase 3, item 71 / slice 10: the auto-advance loop's
selection logic (services/tasks.py's _select_tasks_to_advance()). The
real per-task work (execute_next_step(), dispatched by advance_one_task)
is already covered by tests/test_task_lock.py and
tests/test_task_executor*.py -- this file is only about which tasks the
beat tick selects, in what order, and how many, matching item 74's own
finding (a real 1,243-task backlog in this dev DB is why the design
dispatches instead of running inline, and why the batch is capped).
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus
from services.tasks import ADVANCE_BATCH_SIZE, _select_tasks_to_advance


async def _register(client, prefix="autoadvance"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Auto Advance Test",
        "tenant_name": f"Auto Advance Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_task(tenant_id, user_id, status, updated_at=None, **overrides):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=status, step_budget_max=20, **overrides,
        )
        db.add(task)
        await db.commit()
        if updated_at is not None:
            # Bypass onupdate=datetime.utcnow (which would otherwise
            # stamp "now" on this very commit) to simulate a task that's
            # genuinely been sitting untouched for a while.
            await db.execute(
                Task.__table__.update().where(Task.id == task.id).values(updated_at=updated_at)
            )
            await db.commit()
        return task.id


# item 74: this dev DB has ~1,200+ pre-existing runnable tasks from
# earlier test runs with no teardown, most with a real (old) updated_at.
# ORDER BY updated_at ASC LIMIT N means a freshly-seeded task with
# updated_at="now" would rank BEHIND all of that noise and never appear
# in the selected batch at all -- backdating far enough into the past
# guarantees a seeded task ranks first regardless of how large that
# pre-existing pool ever grows, without needing to touch or clean it up.
_GUARANTEED_OLDEST = datetime.utcnow() - timedelta(days=3650)


@pytest.mark.asyncio
async def test_selects_queued_and_running_and_quota_paused_tasks(client):
    tenant_id, user_id = await _register(client, "selectruntypes")
    queued = await _seed_task(tenant_id, user_id, TaskStatus.QUEUED, updated_at=_GUARANTEED_OLDEST)
    running = await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, updated_at=_GUARANTEED_OLDEST)
    quota_paused = await _seed_task(
        tenant_id, user_id, TaskStatus.PAUSED_QUOTA_EXCEEDED,
        paused_at=datetime.utcnow(), updated_at=_GUARANTEED_OLDEST,
    )
    source_locked = await _seed_task(
        tenant_id, user_id, TaskStatus.PAUSED_SOURCE_LOCKED,
        paused_at=datetime.utcnow(), updated_at=_GUARANTEED_OLDEST,
    )

    selected = set(await _select_tasks_to_advance())
    assert {queued, running, quota_paused, source_locked} <= selected


@pytest.mark.asyncio
async def test_excludes_tasks_waiting_on_a_human_or_already_terminal(client):
    tenant_id, user_id = await _register(client, "selectexclude")
    needs_approval = await _seed_task(tenant_id, user_id, TaskStatus.PAUSED_NEEDS_APPROVAL, paused_at=datetime.utcnow())
    completed = await _seed_task(tenant_id, user_id, TaskStatus.COMPLETED)
    failed = await _seed_task(tenant_id, user_id, TaskStatus.FAILED)
    draft = await _seed_task(tenant_id, user_id, TaskStatus.DRAFT_PLAN)

    selected = set(await _select_tasks_to_advance())
    assert needs_approval not in selected, "a task waiting on a human must never be auto-selected"
    assert completed not in selected
    assert failed not in selected
    assert draft not in selected


@pytest.mark.asyncio
async def test_selection_is_oldest_updated_first(client):
    """The whole point of ordering by updated_at ASC: a task that's been
    sitting untouched the longest gets picked before one that just
    changed state a moment ago, so nothing starves behind a busier
    tenant's tasks."""
    tenant_id, user_id = await _register(client, "selectorder")
    # All three anchored to _GUARANTEED_OLDEST (not "now") so all three
    # are guaranteed to rank ahead of item 74's real pre-existing
    # backlog and actually appear in the batch -- only their relative
    # order to each other is what this test is actually about.
    newest = await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, updated_at=_GUARANTEED_OLDEST + timedelta(hours=2))
    oldest = await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, updated_at=_GUARANTEED_OLDEST)
    middle = await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, updated_at=_GUARANTEED_OLDEST + timedelta(hours=1))

    selected = await _select_tasks_to_advance()
    ours_in_order = [t for t in selected if t in (newest, oldest, middle)]
    assert ours_in_order == [oldest, middle, newest]


@pytest.mark.asyncio
async def test_selection_never_exceeds_the_batch_cap(client):
    """item 74: this dev DB alone already has over a thousand runnable
    tasks from test fixtures with no teardown -- the cap is what keeps
    a single beat tick's dispatch bounded regardless of how large that
    backlog gets."""
    tenant_id, user_id = await _register(client, "selectcap")
    for _ in range(ADVANCE_BATCH_SIZE + 5):
        await _seed_task(tenant_id, user_id, TaskStatus.RUNNING)

    selected = await _select_tasks_to_advance()
    assert len(selected) <= ADVANCE_BATCH_SIZE
