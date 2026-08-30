"""Item 6 stage 7: notification wiring at task terminal/attention
transitions. 'Give it a task and walk away' only works if something tells
you when it's done or needs you -- before this, a task could reach any
terminal state (or need approval) with nothing proactively surfacing that
except polling. Uses the same urlopen-spy technique already established in
test_notification_wiring.py/test_notification_prefs.py -- trusting HTTP
status alone is a known false signal (Slack redirects a bad webhook path
to a 200 landing page).

Deliberately NOT covered here (see task_executor.py's _notify_task_stopped
docstring): PAUSED_FAILED_STEP and PAUSED_QUOTA_EXCEEDED transitions are
retry-prone/self-evident-on-check states that would spam on every failed
attempt -- their absence is asserted directly below, not just omitted.
"""
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
import modules.reporting.notification_service as notification_service_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import cancel_task, execute_next_step, reject_task_step, resume_task
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus, User
from services.settings_service import update_tenant_settings


async def _register(client, prefix="tasknotify"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Notify Test",
        "tenant_name": f"Task Notify Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _configure_webhook(tenant_id, url):
    await update_tenant_settings(tenant_id, {"notification_prefs": {"slack_webhook_url": url}})


def _spy_urlopen(monkeypatch, captured: list):
    def fake_urlopen(req, timeout=10):
        captured.append(req.full_url)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda self, *a: None
        return mock_resp
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", fake_urlopen)


async def _seed_task(tenant_id, user_id, steps: list[dict], **task_overrides):
    defaults = {
        "status": TaskStatus.QUEUED, "step_budget_max": 20,
        "task_shape": TaskShape.DIAGNOSE_PIPELINE_FAILURE,
    }
    defaults.update(task_overrides)
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="notify test goal", **defaults,
        )
        db.add(task)
        await db.flush()
        step_ids = []
        for s in steps:
            ts = TaskStep(id=str(uuid.uuid4()), task_id=task.id, **s)
            db.add(ts)
            step_ids.append(ts.id)
        await db.commit()
        return task.id, step_ids


async def _fresh(task_id):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        return r.scalar_one()


@pytest.mark.asyncio
async def test_wall_clock_termination_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifywallclock")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/WALLCLOCK")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow() - timedelta(hours=999))

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_wall_clock"
    assert captured == ["https://hooks.slack.com/services/WALLCLOCK"]


@pytest.mark.asyncio
async def test_step_budget_termination_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifystepbudget")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/STEPBUDGET")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow(), step_budget_max=5, step_budget_used=5)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_step_budget"
    assert captured == ["https://hooks.slack.com/services/STEPBUDGET"]


@pytest.mark.asyncio
async def test_loop_detected_termination_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifyloop")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/LOOP")
    identical = {"tool_args": {"pipeline_id": "stuck-pl"}}
    task_id, _ = await _seed_task(tenant_id, user_id, [
        {"step_index": 0, "description": "attempt 1", "source": TaskStepSource.LLM_PLANNED,
         "tool_name": "get_pipeline_run_history", "status": TaskStepStatus.SUCCEEDED, **identical},
        {"step_index": 1, "description": "attempt 2", "source": TaskStepSource.HUMAN_EDITED,
         "tool_name": "get_pipeline_run_history", "status": TaskStepStatus.SUCCEEDED, **identical},
        {"step_index": 2, "description": "attempt 3", "source": TaskStepSource.HUMAN_EDITED,
         "tool_name": "get_pipeline_run_history", "status": TaskStepStatus.PENDING, **identical},
    ], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_loop_detected"
    assert captured == ["https://hooks.slack.com/services/LOOP"]


@pytest.mark.asyncio
async def test_task_completed_notifies_with_the_real_goal(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifycomplete")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/COMPLETE")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _ok(tenant_id, tool_name, tool_args, **kwargs):
        return {"status": "ok"}

    monkeypatch.setattr(executor_module, "_call_tool", _ok)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    await execute_next_step(task_id)  # runs the one step
    final = await execute_next_step(task_id)  # detects completion
    assert final["outcome"] == "task_completed"
    assert captured == ["https://hooks.slack.com/services/COMPLETE"]


@pytest.mark.asyncio
async def test_completed_with_unconfirmed_steps_notifies_naming_the_stuck_step(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifyunconfirmed")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/UNCONFIRMED")
    long_ago = datetime.utcnow() - timedelta(seconds=99999)
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "verify the stuck run", "source": TaskStepSource.SYSTEM_INSERTED,
        "tool_name": "run_pipeline", "tool_args": {}, "status": TaskStepStatus.VERIFYING,
        "raw_result": {"run_id": "run-stuck"}, "started_at": long_ago,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _still_pending(tool_name, dispatch_result):
        return {"terminal": False, "success": None, "detail": "still running"}

    monkeypatch.setattr(executor_module, "_poll_dispatch_status", _still_pending)
    monkeypatch.setattr(executor_module, "VERIFY_TIMEOUT_SECONDS", 300)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "task_completed_with_unconfirmed_steps"
    assert captured == ["https://hooks.slack.com/services/UNCONFIRMED"]


@pytest.mark.asyncio
async def test_blocked_needs_approval_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifyapproval")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/NEEDSAPPROVAL")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "sync a source", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "sync_source", "tool_args": {"source_id": "src-1"}, "status": TaskStepStatus.PENDING,
    }], task_shape=TaskShape.SYNC_PROFILE_QUALITY)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_needs_approval"
    assert captured == ["https://hooks.slack.com/services/NEEDSAPPROVAL"]


@pytest.mark.asyncio
async def test_expiry_on_resume_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifyexpireresume")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/EXPIRERESUME")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "sync a source", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "sync_source", "tool_args": {"source_id": "src-1"}, "status": TaskStepStatus.PENDING,
    }], task_shape=TaskShape.SYNC_PROFILE_QUALITY)
    await execute_next_step(task_id)  # blocks, paused_at = now

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.paused_at = datetime.utcnow() - timedelta(hours=999)
        await db.commit()

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    result = await resume_task(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "expired"
    assert captured == ["https://hooks.slack.com/services/EXPIRERESUME"]


@pytest.mark.asyncio
async def test_expiry_on_reject_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifyexpirereject")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/EXPIREREJECT")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "sync a source", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "sync_source", "tool_args": {"source_id": "src-1"}, "status": TaskStepStatus.PENDING,
    }], task_shape=TaskShape.SYNC_PROFILE_QUALITY)
    await execute_next_step(task_id)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        task.paused_at = datetime.utcnow() - timedelta(hours=999)
        await db.commit()

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    result = await reject_task_step(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "expired"
    assert captured == ["https://hooks.slack.com/services/EXPIREREJECT"]


@pytest.mark.asyncio
async def test_cancel_notifies(client, monkeypatch):
    tenant_id, user_id = await _register(client, "notifycancel")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/CANCEL")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    result = await cancel_task(task_id, cancelled_by=user_id)
    assert result["outcome"] == "cancelled"
    assert captured == ["https://hooks.slack.com/services/CANCEL"]


@pytest.mark.asyncio
async def test_paused_failed_step_does_not_notify(client, monkeypatch):
    """Deliberately excluded -- retry-prone, would spam on every failed
    attempt within the same 3-attempt budget."""
    tenant_id, user_id = await _register(client, "notifynofailedstep")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/SHOULD_NOT_FIRE")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _always_fails(tenant_id, tool_name, tool_args, **kwargs):
        raise RuntimeError("simulated: the underlying service is down")

    monkeypatch.setattr(executor_module, "_call_tool", _always_fails)
    monkeypatch.setattr(executor_module, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_failed"
    assert captured == []


@pytest.mark.asyncio
async def test_paused_quota_exceeded_does_not_notify(client, monkeypatch):
    """Deliberately excluded -- self-evident the moment the caller checks
    (a 402-shaped outcome), and retry-prone the same way a failed step is."""
    tenant_id, user_id = await _register(client, "notifynoquota")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/SHOULD_NOT_FIRE")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check history", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_pipeline_run_history", "tool_args": {"pipeline_id": "bad-id"},
        "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow())

    async def _domain_error(tenant_id, tool_name, tool_args, **kwargs):
        return {"error": "Pipeline not found"}

    async def _quota_exceeded(tenant_id, resource):
        return {"resource": resource, "status": "exceeded", "used": 999999, "limit": 25000}

    monkeypatch.setattr(executor_module, "_call_tool", _domain_error)
    monkeypatch.setattr(executor_module, "get_quota_status", _quota_exceeded)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "paused_quota_exceeded"
    assert captured == []


@pytest.mark.asyncio
async def test_notification_failure_never_breaks_the_real_state_transition(client, monkeypatch):
    """The notification wiring must never break the actual feature it's
    attached to -- matches the established contract for every other
    notification call site in this codebase."""
    tenant_id, user_id = await _register(client, "notifybreak")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/WILL_BLOW_UP")
    task_id, _ = await _seed_task(tenant_id, user_id, [{
        "step_index": 0, "description": "check health", "source": TaskStepSource.LLM_PLANNED,
        "tool_name": "get_system_health", "tool_args": {}, "status": TaskStepStatus.PENDING,
    }], status=TaskStatus.RUNNING, started_at=datetime.utcnow() - timedelta(hours=999))

    def broken_urlopen(req, timeout=10):
        raise RuntimeError("simulated network failure")
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", broken_urlopen)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "terminated_wall_clock"  # real transition still happened

    task = await _fresh(task_id)
    assert task.status == TaskStatus.FAILED
    assert task.termination_reason is not None
