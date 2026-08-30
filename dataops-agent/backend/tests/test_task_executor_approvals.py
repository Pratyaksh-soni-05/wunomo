"""Item 6 stage 5: mid-task approvals (Q5). Mocked at the _call_tool
boundary for deterministic coverage of the state machine -- the four
things explicitly required to be proven LIVE (worker-restart survival,
precondition re-validation, authority-on-resume, pause-timeout expiry)
are proven against real infrastructure separately, recorded in CLAUDE.md.
This file still includes fast, deterministic regression tests for
authority-on-resume and expiry, since those are cheap to prove twice and
worth guarding against regression even though the live proof is the
real evidence.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import execute_next_step, reject_task_step, resume_task
from models.all_models import (
    ApprovalRequest, ApprovalStatus, Task, TaskShape, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus, User,
)


async def _register(client, prefix="taskapproval"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Approval Test",
        "tenant_name": f"Task Approval Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_queued_task(tenant_id, user_id, tool_name="sync_source", tool_args=None):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.QUEUED, step_budget_max=20,
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="sync a source", source=TaskStepSource.LLM_PLANNED,
            tool_name=tool_name, tool_args=tool_args or {"source_id": "src-1"},
            status=TaskStepStatus.PENDING,
        )
        db.add(step)
        await db.commit()
        return task.id, step.id


async def _fresh(task_id, step_id=None):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        if step_id is None:
            return task
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        return task, r.scalar_one()


@pytest.mark.asyncio
async def test_medium_risk_step_blocks_and_creates_a_real_approval_request(client):
    tenant_id, user_id = await _register(client, "approvalblock")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_needs_approval"
    assert outcome["risk_level"] == "medium"

    task, step = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.PAUSED_NEEDS_APPROVAL
    assert task.paused_at is not None
    assert step.status == TaskStepStatus.BLOCKED_APPROVAL
    assert step.approval_request_id is not None

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval = r.scalar_one()
        assert approval.status == ApprovalStatus.PENDING
        assert approval.action_name == "sync_source"
        assert approval.user_id == user_id


@pytest.mark.asyncio
async def test_resume_approves_and_continues_execution(client, monkeypatch):
    tenant_id, user_id = await _register(client, "approvalresume")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)
    await execute_next_step(task_id)  # blocks

    async def _ok(tenant_id, tool_name, tool_args, **kwargs):
        return {"status": "synced", "rows": 5}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    approver_id = str(uuid.uuid4())
    result = await resume_task(task_id, resolved_by=approver_id, notes="looks fine")
    assert result["outcome"] == "step_succeeded"

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.SUCCEEDED
    # Completion is detected on the NEXT call, not automatically after a
    # step's own success -- the same "one call, one thing" model stages
    # 3/4 already established (see test_task_completes_only_once_no_
    # pending_steps_remain). Confirm that next call really does finish it.
    assert task.status == TaskStatus.RUNNING
    final = await execute_next_step(task_id)
    assert final["outcome"] == "task_completed"
    task, _ = await _fresh(task_id, step_id)
    assert task.status == TaskStatus.COMPLETED

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval = r.scalar_one()
        assert approval.status == ApprovalStatus.APPROVED
        assert approval.resolved_by == approver_id
        assert approval.resolution_note == "looks fine"
        assert approval.resolved_at is not None


@pytest.mark.asyncio
async def test_reject_step_fails_the_step_and_pauses_the_task(client):
    tenant_id, user_id = await _register(client, "approvalreject")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)
    await execute_next_step(task_id)  # blocks

    approver_id = str(uuid.uuid4())
    result = await reject_task_step(task_id, resolved_by=approver_id, notes="too risky right now")
    assert result["outcome"] == "step_rejected"

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert "too risky right now" in step.error_message
    assert task.status == TaskStatus.PAUSED_FAILED_STEP

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval = r.scalar_one()
        assert approval.status == ApprovalStatus.REJECTED
        assert approval.resolved_by == approver_id


@pytest.mark.asyncio
async def test_resume_on_a_task_not_awaiting_approval_is_not_resumable(client):
    tenant_id, user_id = await _register(client, "approvalnotwaiting")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id, tool_name="get_system_health", tool_args={})

    result = await resume_task(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "not_resumable"
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_authority_is_re_validated_on_resume_not_trusted_from_when_it_was_blocked(client):
    """Fast, deterministic regression companion to the live proof: the
    task's initiating user demoted to a role that no longer has
    sources.profile (sync_source's real capability) during the pause
    must be caught fresh on resume, not waved through because it was
    valid when the step was first blocked."""
    tenant_id, user_id = await _register(client, "approvalauth")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)
    await execute_next_step(task_id)  # blocks, user is still "owner" here

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()

    result = await resume_task(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "blocked_permission"

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert "no longer" in step.error_message
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


@pytest.mark.asyncio
async def test_resume_past_the_timeout_expires_instead_of_resuming(client, monkeypatch):
    tenant_id, user_id = await _register(client, "approvalexpire")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)
    await execute_next_step(task_id)  # blocks, paused_at = now

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.paused_at = datetime.utcnow() - timedelta(hours=999)
        await db.commit()

    result = await resume_task(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "expired"

    task = await _fresh(task_id)
    assert task.status == TaskStatus.EXPIRED

    # And it stays expired -- a second resume attempt doesn't somehow
    # revive it (status is no longer PAUSED_NEEDS_APPROVAL at all).
    result2 = await resume_task(task_id, resolved_by=str(uuid.uuid4()))
    assert result2["outcome"] == "not_resumable"


@pytest.mark.asyncio
async def test_reject_past_the_timeout_also_expires_rather_than_rejecting(client):
    tenant_id, user_id = await _register(client, "approvalexpirereject")
    task_id, step_id = await _seed_queued_task(tenant_id, user_id)
    await execute_next_step(task_id)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.paused_at = datetime.utcnow() - timedelta(hours=999)
        await db.commit()

    result = await reject_task_step(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "expired"
    task = await _fresh(task_id)
    assert task.status == TaskStatus.EXPIRED
