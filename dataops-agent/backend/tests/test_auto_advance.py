"""Wunomo Projects Phase 3, item 71 / slice 10: the auto-advance loop's
selection logic (services/tasks.py's _select_tasks_to_advance()). The
real per-task work (execute_next_step(), dispatched by advance_one_task)
is already covered by tests/test_task_lock.py and
tests/test_task_executor*.py -- this file is only about which tasks the
beat tick selects, in what order, and how many, matching item 74's own
finding (a real 1,243-task backlog in this dev DB is why the design
dispatches instead of running inline, and why the batch is capped).

This file deletes every task it creates (see the autouse _cleanup
fixture below) -- found live, the hard way: an earlier version left
its own fixtures behind, and this file's OWN prior runs (all anchored
to the same "guaranteed oldest" timestamp) started out-ranking its
current run, since ties at an identical updated_at break arbitrarily.
Real teardown here isn't just hygiene, it's what makes these specific
tests deterministic -- the item 74 backlog everywhere else in this dev
DB is a separate, much larger, deliberately-not-fixed-here problem.
"""
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus
from services.tasks import ADVANCE_BATCH_SIZE, _select_tasks_to_advance


@pytest_asyncio.fixture
async def created_task_ids():
    ids = []
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(TaskStep.__table__.delete().where(TaskStep.task_id.in_(ids)))
        await db.execute(Task.__table__.delete().where(Task.id.in_(ids)))
        await db.commit()


async def _register(client, prefix="autoadvance"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Auto Advance Test",
        "tenant_name": f"Auto Advance Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_task(tenant_id, user_id, status, created_task_ids, updated_at=None, **overrides):
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
        created_task_ids.append(task.id)
        return task.id


# item 74: this dev DB has ~1,200+ pre-existing runnable tasks from
# earlier test runs with no teardown, most with a real (old) updated_at.
# ORDER BY updated_at ASC LIMIT N means a freshly-seeded task with
# updated_at="now" would rank BEHIND all of that noise and never appear
# in the selected batch at all -- backdating far enough into the past
# guarantees a seeded task ranks first regardless of how large that
# pre-existing pool ever grows, without needing to touch or clean it up.
# Fixed absolute epoch (not "utcnow() - timedelta(days=N)", which would
# recompute later every run) -- combined with created_task_ids' own
# real cleanup above, this file's own tasks never accumulate or tie
# against each other across repeated runs.
_GUARANTEED_OLDEST = datetime(1990, 1, 1)


@pytest.mark.asyncio
async def test_selects_queued_and_running_and_quota_paused_tasks(client, created_task_ids):
    tenant_id, user_id = await _register(client, "selectruntypes")
    queued = await _seed_task(tenant_id, user_id, TaskStatus.QUEUED, created_task_ids, updated_at=_GUARANTEED_OLDEST)
    running = await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, created_task_ids, updated_at=_GUARANTEED_OLDEST)
    quota_paused = await _seed_task(
        tenant_id, user_id, TaskStatus.PAUSED_QUOTA_EXCEEDED, created_task_ids,
        paused_at=datetime.utcnow(), updated_at=_GUARANTEED_OLDEST,
    )
    source_locked = await _seed_task(
        tenant_id, user_id, TaskStatus.PAUSED_SOURCE_LOCKED, created_task_ids,
        paused_at=datetime.utcnow(), updated_at=_GUARANTEED_OLDEST,
    )

    selected, _total = await _select_tasks_to_advance()
    assert {queued, running, quota_paused, source_locked} <= set(selected)


@pytest.mark.asyncio
async def test_excludes_tasks_waiting_on_a_human_or_already_terminal(client, created_task_ids):
    tenant_id, user_id = await _register(client, "selectexclude")
    needs_approval = await _seed_task(
        tenant_id, user_id, TaskStatus.PAUSED_NEEDS_APPROVAL, created_task_ids, paused_at=datetime.utcnow(),
    )
    completed = await _seed_task(tenant_id, user_id, TaskStatus.COMPLETED, created_task_ids)
    failed = await _seed_task(tenant_id, user_id, TaskStatus.FAILED, created_task_ids)
    draft = await _seed_task(tenant_id, user_id, TaskStatus.DRAFT_PLAN, created_task_ids)

    selected, _total = await _select_tasks_to_advance()
    selected = set(selected)
    assert needs_approval not in selected, "a task waiting on a human must never be auto-selected"
    assert completed not in selected
    assert failed not in selected
    assert draft not in selected


@pytest.mark.asyncio
async def test_selection_is_oldest_updated_first(client, created_task_ids):
    """The whole point of ordering by updated_at ASC: a task that's been
    sitting untouched the longest gets picked before one that just
    changed state a moment ago, so nothing starves behind a busier
    tenant's tasks."""
    tenant_id, user_id = await _register(client, "selectorder")
    # All three anchored to _GUARANTEED_OLDEST (not "now") so all three
    # are guaranteed to rank ahead of item 74's real pre-existing
    # backlog and actually appear in the batch -- only their relative
    # order to each other is what this test is actually about.
    newest = await _seed_task(
        tenant_id, user_id, TaskStatus.RUNNING, created_task_ids, updated_at=_GUARANTEED_OLDEST + timedelta(hours=2),
    )
    oldest = await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, created_task_ids, updated_at=_GUARANTEED_OLDEST)
    middle = await _seed_task(
        tenant_id, user_id, TaskStatus.RUNNING, created_task_ids, updated_at=_GUARANTEED_OLDEST + timedelta(hours=1),
    )

    selected, _total = await _select_tasks_to_advance()
    ours_in_order = [t for t in selected if t in (newest, oldest, middle)]
    assert ours_in_order == [oldest, middle, newest]


@pytest.mark.asyncio
async def test_selection_never_exceeds_the_batch_cap(client, created_task_ids):
    """item 74: this dev DB alone already has over a thousand runnable
    tasks from test fixtures with no teardown -- the cap is what keeps
    a single beat tick's dispatch bounded regardless of how large that
    backlog gets."""
    tenant_id, user_id = await _register(client, "selectcap")
    for _ in range(ADVANCE_BATCH_SIZE + 5):
        await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, created_task_ids)

    selected, _total = await _select_tasks_to_advance()
    assert len(selected) <= ADVANCE_BATCH_SIZE


@pytest.mark.asyncio
async def test_total_runnable_count_reflects_the_real_backlog_not_just_the_capped_batch(client, created_task_ids):
    """Backlog visibility (added after slice 10 shipped, per instruction):
    the whole point of returning total_runnable separately from the
    capped selection is to be able to tell a draining backlog from a
    growing one -- which is impossible if the only number available is
    already clamped to ADVANCE_BATCH_SIZE."""
    tenant_id, user_id = await _register(client, "selecttotal")
    before_selected, before_total = await _select_tasks_to_advance()

    n_new = ADVANCE_BATCH_SIZE + 3
    for _ in range(n_new):
        await _seed_task(tenant_id, user_id, TaskStatus.RUNNING, created_task_ids, updated_at=_GUARANTEED_OLDEST)

    after_selected, after_total = await _select_tasks_to_advance()
    assert after_total == before_total + n_new
    # The count grew by more than a batch, but the selection itself
    # still never exceeds the cap -- the two numbers can and do diverge.
    assert len(after_selected) <= ADVANCE_BATCH_SIZE


# ---------------------------------------------------------------------------
# GET /health/tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_tasks_reflects_a_real_new_runnable_task(client, created_task_ids):
    tenant_id, user_id = await _register(client, "healthtasks")
    before = (await client.get("/health/tasks")).json()

    await _seed_task(tenant_id, user_id, TaskStatus.QUEUED, created_task_ids)

    after = (await client.get("/health/tasks")).json()
    assert after["total_runnable"] == before["total_runnable"] + 1
    assert after["by_status"]["queued"] == before["by_status"].get("queued", 0) + 1
    assert after["batch_size"] == ADVANCE_BATCH_SIZE


@pytest.mark.asyncio
async def test_health_tasks_excludes_paused_for_approval_and_terminal_statuses(client, created_task_ids):
    tenant_id, user_id = await _register(client, "healthtasksexcl")
    before = (await client.get("/health/tasks")).json()

    await _seed_task(tenant_id, user_id, TaskStatus.PAUSED_NEEDS_APPROVAL, created_task_ids, paused_at=datetime.utcnow())
    await _seed_task(tenant_id, user_id, TaskStatus.COMPLETED, created_task_ids)

    after = (await client.get("/health/tasks")).json()
    assert after["total_runnable"] == before["total_runnable"], \
        "a task waiting on a human or already terminal must never count as runnable backlog"
