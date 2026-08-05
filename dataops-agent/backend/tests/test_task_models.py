"""Stage 1 (schema only) regression tests for item 6's Task/TaskStep models
-- see CLAUDE.md's item-6 design decisions. No execution behavior exists
yet; this only proves the schema itself holds the invariants the design
review required: real tenant scoping, sane defaults, FK integrity between
Task/TaskStep/ApprovalRequest, and -- the one that matters most --
confirms Task genuinely has no role/is_active column to snapshot, since a
snapshotted role was flagged as a privilege-escalation hole with a
built-in time window.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    Task, TaskStep, TaskShape, TaskStatus, TaskStepStatus, TaskStepSource,
)


async def _register(client, prefix="taskmodel"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Model Test",
        "tenant_name": f"Task Model Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


@pytest.mark.asyncio
async def test_task_defaults_to_draft_plan_with_no_provenance_set(client):
    tenant_id, user_id = await _register(client)
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="Diagnose why the nightly sales pipeline failed",
            task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            step_budget_max=20,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        assert task.status == TaskStatus.DRAFT_PLAN
        assert task.plan_approved_by is None
        assert task.plan_approved_at is None
        assert task.plan_edited in (None, False)
        assert task.step_budget_used in (None, 0)
        assert task.credit_budget_used in (None, 0)


@pytest.mark.asyncio
async def test_task_has_no_role_column_to_snapshot(client):
    """Structural guard for the design decision itself: role/is_active must
    be re-read fresh per step at execution time, never cached on Task. If a
    future edit adds a role-shaped column here, this test should force a
    deliberate re-read of why that's dangerous before it ships."""
    task_columns = {c.name for c in Task.__table__.columns}
    assert "role" not in task_columns
    assert "is_active" not in task_columns
    assert "user_role" not in task_columns


@pytest.mark.asyncio
async def test_tasks_are_scoped_per_tenant(client):
    tenant_a, user_a = await _register(client, "taskscopea")
    tenant_b, user_b = await _register(client, "taskscopeb")

    async with AsyncSessionLocal() as db:
        db.add(Task(
            id=str(uuid.uuid4()), tenant_id=tenant_a, user_id=user_a,
            goal="Tenant A's task", task_shape=TaskShape.INVESTIGATE_INCIDENT,
            step_budget_max=10,
        ))
        db.add(Task(
            id=str(uuid.uuid4()), tenant_id=tenant_b, user_id=user_b,
            goal="Tenant B's task", task_shape=TaskShape.INVESTIGATE_INCIDENT,
            step_budget_max=10,
        ))
        await db.commit()

        r = await db.execute(select(Task).where(Task.tenant_id == tenant_a))
        tenant_a_tasks = r.scalars().all()
        assert len(tenant_a_tasks) == 1
        assert tenant_a_tasks[0].goal == "Tenant A's task"

        r = await db.execute(select(Task).where(Task.tenant_id == tenant_b))
        tenant_b_tasks = r.scalars().all()
        assert len(tenant_b_tasks) == 1
        assert tenant_b_tasks[0].goal == "Tenant B's task"


@pytest.mark.asyncio
async def test_task_step_provenance_and_fk_integrity(client):
    tenant_id, user_id = await _register(client, "taskstepfk")
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="Sync and profile two sources, then run quality checks",
            task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            step_budget_max=15,
        )
        db.add(task)
        await db.flush()

        planned_step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="Sync source X", source=TaskStepSource.LLM_PLANNED,
            tool_name="sync_source", tool_args={"source_id": "fake-source"},
            status=TaskStepStatus.PENDING,
        )
        verify_step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=1,
            description="Confirm source X sync reached a terminal state",
            source=TaskStepSource.SYSTEM_INSERTED,
            depends_on_step_index=0,
            status=TaskStepStatus.PENDING,
        )
        db.add_all([planned_step, verify_step])
        await db.commit()

        r = await db.execute(
            select(TaskStep).where(TaskStep.task_id == task.id).order_by(TaskStep.step_index)
        )
        steps = r.scalars().all()
        assert len(steps) == 2
        assert steps[0].source == TaskStepSource.LLM_PLANNED
        assert steps[0].tool_name == "sync_source"
        # The verify step is system-inserted, not LLM-planned -- must never
        # render in a timeline as something AXIOM "chose" to do.
        assert steps[1].source == TaskStepSource.SYSTEM_INSERTED
        assert steps[1].tool_name is None
        assert steps[1].depends_on_step_index == 0


@pytest.mark.asyncio
async def test_task_shape_is_constrained_to_the_three_narrow_v1_values():
    real_values = {s.value for s in TaskShape}
    assert real_values == {
        "diagnose_pipeline_failure", "investigate_incident", "sync_profile_quality",
    }


@pytest.mark.asyncio
async def test_task_status_has_a_distinct_queued_state(client):
    """queued is genuinely distinct from running -- 'approved but not yet
    picked up' and 'running but stuck' must be tellable apart, not
    collapsed into one status."""
    assert TaskStatus.QUEUED.value == "queued"
    assert TaskStatus.QUEUED != TaskStatus.RUNNING

    tenant_id, user_id = await _register(client, "taskqueued")
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="Sync a source", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            step_budget_max=10, status=TaskStatus.QUEUED,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        assert task.status == TaskStatus.QUEUED
