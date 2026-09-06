"""Wunomo Projects Phase 4, slice 14: per-agent scheduled work. A
ScheduledAgentTask fires a fixed tool call on a cron schedule, with no
LLM replanning -- see that model's own docstring (models/all_models.py)
and modules/orchestration/scheduled_tasks.py for the full design.

Covers: creation-time validation (structural, owner, agent, source),
reactivation re-running the identical validation, the no-overlap skip,
real firing (Task + TaskStep creation), deactivation-with-notification
for each of the three causes (owner lost access, agent offboarded,
source deleted) with cause-specific messages, the offboarding cascade,
and the beat tick's cron-matching/dispatch behavior.
"""
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import modules.reporting.notification_service as notification_service_module
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, DataSource, OperationMode,
    PersonalityMode, ScheduledAgentTask, SourceType, Task, TaskShape, TaskStatus,
    TaskStep, TaskStepSource, TaskStepStatus, TERMINAL_TASK_STATUSES, User,
)
from modules.orchestration.scheduled_tasks import (
    ScheduleValidationError, fire_scheduled_task, validate_schedule_can_run,
)
from services.auth_service import hash_password, issue_token_for_user
from services.tasks import _check_scheduled_agent_tasks


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _spy_urlopen(monkeypatch, captured: list):
    def fake_urlopen(req, timeout=10):
        captured.append(json.loads(req.data.decode("utf-8")))
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda self, *a: None
        return mock_resp
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", fake_urlopen)


async def _register(client, prefix="schedagent"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Scheduled Agent Test",
        "tenant_name": f"Scheduled Agent Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _member(tenant_id, role, prefix="member"):
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name=prefix, role=role,
            is_active=True, email_verified=True,
        )
        db.add(user)
        await db.commit()
        return issue_token_for_user(user, "password"), user.id


async def _hire_agent(tenant_id, name="Scheduler Agent"):
    async with AsyncSessionLocal() as db:
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, employee_type=AgentEmployeeType.DATAOPS,
            personality=PersonalityMode.ENGINEER, operation_mode=OperationMode.ASSISTED,
            model="gemini-3.5-flash", status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        await db.commit()
        return agent.id


async def _create_source(tenant_id, name="Marketing Warehouse"):
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            source_type=SourceType.POSTGRES, connection_config={"host": "postgres"},
        )
        db.add(source)
        await db.commit()
        return source.id


async def _create_schedule(
    tenant_id, agent_id, owner_user_id, tool_args, active=True, schedule_cron="0 3 * * *", **overrides,
):
    async with AsyncSessionLocal() as db:
        schedule = ScheduledAgentTask(
            id=str(uuid.uuid4()), tenant_id=tenant_id, agent_id=agent_id, created_by_user_id=owner_user_id,
            task_shape=TaskShape.SYNC_PROFILE_QUALITY, description="Nightly sync",
            tool_name="sync_source", tool_args=tool_args, schedule_cron=schedule_cron, active=active,
            **overrides,
        )
        db.add(schedule)
        await db.commit()
        return schedule.id


async def _get_schedule(schedule_id):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ScheduledAgentTask).where(ScheduledAgentTask.id == schedule_id))
        return r.scalar_one()


async def _set_user(user_id, **fields):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        for k, v in fields.items():
            setattr(user, k, v)
        await db.commit()


# ---------------------------------------------------------------------------
# Creation-time validation (confirmed requirement: fail at the click, not
# at 3am)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_schedule_succeeds_with_valid_tool_and_source(client):
    token, tenant_id, user_id = await _register(client, "createok")
    agent_id = await _hire_agent(tenant_id)
    source_id = await _create_source(tenant_id)

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "Nightly sync",
        "tool_name": "sync_source", "tool_args": {"source_id": source_id}, "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body["created_by_user_id"] == user_id
    assert body["deactivation_reason"] is None


@pytest.mark.asyncio
async def test_create_schedule_rejects_unknown_task_shape(client):
    token, tenant_id, _ = await _register(client, "createbadshape")
    agent_id = await _hire_agent(tenant_id)

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "not_a_real_shape", "description": "x",
        "tool_name": "sync_source", "tool_args": {}, "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 400
    assert "task_shape" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_schedule_rejects_tool_not_allowed_for_shape(client):
    """A typo'd or wrong tool_name must fail at creation -- validate_step_plan
    is the structural check that catches this, reused unchanged from the
    real task-planning path."""
    token, tenant_id, _ = await _register(client, "createbadtool")
    agent_id = await _hire_agent(tenant_id)

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "triage_incident",  # belongs to INVESTIGATE_INCIDENT, not SYNC_PROFILE_QUALITY
        "tool_args": {}, "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 400
    assert "not permitted for shape" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_schedule_rejects_missing_required_arg(client):
    token, tenant_id, _ = await _register(client, "createmissingarg")
    agent_id = await _hire_agent(tenant_id)

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "sync_source", "tool_args": {},  # missing required source_id
        "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 400
    assert "missing required argument" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_schedule_rejects_deleted_or_nonexistent_source(client):
    """The confirmation point raised during design: an arg referencing a
    deleted/nonexistent source must fail at creation, not at 3am --
    agent_scope_denial_reason() deliberately never catches this (see its
    own docstring), so this is a new check specific to schedules."""
    token, tenant_id, _ = await _register(client, "createbadsource")
    agent_id = await _hire_agent(tenant_id)

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "sync_source", "tool_args": {"source_id": "does-not-exist"},
        "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 400
    assert "no longer exists" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_schedule_rejects_offboarded_agent(client):
    token, tenant_id, _ = await _register(client, "createoffboarded")
    agent_id = await _hire_agent(tenant_id)
    await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "sync_source", "tool_args": {}, "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 409
    assert "offboarded" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_schedule_rejects_invalid_cron(client):
    token, tenant_id, _ = await _register(client, "createbadcron")
    agent_id = await _hire_agent(tenant_id)

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "sync_source", "tool_args": {"source_id": "x"}, "schedule_cron": "not a cron",
    }, headers=_auth(token))
    assert r.status_code == 400
    assert "cron" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_schedule_requires_agents_manage_permission(client):
    token, tenant_id, _ = await _register(client, "createperm")
    agent_id = await _hire_agent(tenant_id)
    analyst_token, _ = await _member(tenant_id, "data_analyst", "createpermanalyst")

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "sync_source", "tool_args": {}, "schedule_cron": "0 3 * * *",
    }, headers=_auth(analyst_token))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_schedule_404_for_nonexistent_agent(client):
    token, tenant_id, _ = await _register(client, "createnoagent")

    r = await client.post("/api/v1/agents/does-not-exist/schedules", json={
        "task_shape": "sync_profile_quality", "description": "x",
        "tool_name": "sync_source", "tool_args": {}, "schedule_cron": "0 3 * * *",
    }, headers=_auth(token))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_schedules_returns_created_schedule(client):
    token, tenant_id, user_id = await _register(client, "listsched")
    agent_id = await _hire_agent(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {})

    r = await client.get(f"/api/v1/agents/{agent_id}/schedules", headers=_auth(token))
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()["schedules"]}
    assert schedule_id in ids


# ---------------------------------------------------------------------------
# Reactivation re-runs the identical validation (explicit requirement)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reactivate_is_idempotent_when_already_active(client):
    token, tenant_id, user_id = await _register(client, "reactivateidem")
    agent_id = await _hire_agent(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {})

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules/{schedule_id}/reactivate", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["active"] is True


@pytest.mark.asyncio
async def test_reactivate_fails_again_when_cause_still_true(client):
    """The core requirement: turning a deactivated schedule back on with
    its cause unfixed fails at the click, not at the next firing."""
    token, tenant_id, user_id = await _register(client, "reactivatefail")
    agent_id = await _hire_agent(tenant_id)
    schedule_id = await _create_schedule(
        tenant_id, agent_id, user_id, {"source_id": "gone"},
        active=False, deactivation_reason="source deleted",
    )

    r = await client.post(f"/api/v1/agents/{agent_id}/schedules/{schedule_id}/reactivate", headers=_auth(token))
    assert r.status_code == 400
    assert "no longer exists" in r.json()["detail"]

    schedule = await _get_schedule(schedule_id)
    assert schedule.active is False  # unchanged -- reactivation did not silently succeed


@pytest.mark.asyncio
async def test_reactivate_succeeds_once_cause_is_fixed(client):
    """Owner permission is the one cause genuinely fixable without
    deleting and recreating the schedule -- restoring the role and
    reactivating must succeed."""
    token, tenant_id, _ = await _register(client, "reactivatefix")
    agent_id = await _hire_agent(tenant_id)
    analyst_token, analyst_id = await _member(tenant_id, "data_analyst", "reactivatefixowner")
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(
        tenant_id, agent_id, analyst_id, {"source_id": source_id}, active=False,
        deactivation_reason="lost permission",
    )
    await _set_user(analyst_id, role="viewer")  # confirm it would still fail
    r = await client.post(f"/api/v1/agents/{agent_id}/schedules/{schedule_id}/reactivate", headers=_auth(token))
    assert r.status_code == 400

    await _set_user(analyst_id, role="data_analyst")  # restore -- now it should pass
    r = await client.post(f"/api/v1/agents/{agent_id}/schedules/{schedule_id}/reactivate", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["active"] is True
    assert r.json()["deactivation_reason"] is None


@pytest.mark.asyncio
async def test_reactivate_404_for_wrong_agent(client):
    token, tenant_id, user_id = await _register(client, "reactivatewrongagent")
    agent_id = await _hire_agent(tenant_id)
    other_agent_id = await _hire_agent(tenant_id, name="Other Agent")
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {}, active=False)

    r = await client.post(
        f"/api/v1/agents/{other_agent_id}/schedules/{schedule_id}/reactivate", headers=_auth(token),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Deletion -- the real fix for the two causes reactivation can't solve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_schedule_succeeds_and_preserves_existing_tasks(client):
    token, tenant_id, user_id = await _register(client, "deletesched")
    agent_id = await _hire_agent(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {})

    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            originating_schedule_id=schedule_id, goal="Nightly sync", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.COMPLETED, step_budget_max=20,
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    r = await client.delete(f"/api/v1/agents/{agent_id}/schedules/{schedule_id}", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ScheduledAgentTask).where(ScheduledAgentTask.id == schedule_id))
        assert r.scalar_one_or_none() is None
        # The task itself survives, untouched, only losing the back-reference.
        r = await db.execute(select(Task).where(Task.id == task_id))
        surviving_task = r.scalar_one()
        assert surviving_task.status == TaskStatus.COMPLETED
        assert surviving_task.originating_schedule_id is None


@pytest.mark.asyncio
async def test_delete_schedule_404_for_nonexistent(client):
    token, tenant_id, _ = await _register(client, "deletesched404")
    agent_id = await _hire_agent(tenant_id)

    r = await client.delete(f"/api/v1/agents/{agent_id}/schedules/does-not-exist", headers=_auth(token))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Firing -- fixed step, no replanning, no-overlap skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_creates_a_queued_task_with_a_single_scheduled_step(client):
    token, tenant_id, user_id = await _register(client, "firebasic")
    agent_id = await _hire_agent(tenant_id)
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {"source_id": source_id})

    outcome = await fire_scheduled_task(schedule_id)
    assert outcome["outcome"] == "fired"
    task_id = outcome["task_id"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        assert task.status == TaskStatus.QUEUED
        assert task.user_id == user_id
        assert task.agent_id == agent_id
        assert task.originating_schedule_id == schedule_id
        assert task.goal == "Nightly sync"

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        step = r.scalar_one()
        assert step.source == TaskStepSource.SCHEDULED
        assert step.tool_name == "sync_source"
        assert step.tool_args == {"source_id": source_id}
        assert step.status == TaskStepStatus.PENDING

    schedule = await _get_schedule(schedule_id)
    assert schedule.last_fired_at is not None


@pytest.mark.asyncio
async def test_fire_skips_without_creating_a_task_while_previous_run_is_non_terminal(client):
    """The core requirement: a daily schedule hitting an approval gate
    must not stack a second pending task before the first's 48-hour
    window even closes."""
    token, tenant_id, user_id = await _register(client, "fireoverlap")
    agent_id = await _hire_agent(tenant_id)
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {"source_id": source_id})

    first = await fire_scheduled_task(schedule_id)
    assert first["outcome"] == "fired"

    second = await fire_scheduled_task(schedule_id)
    assert second["outcome"] == "skipped_overlap"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.originating_schedule_id == schedule_id))
        assert len(r.scalars().all()) == 1  # still just the one


@pytest.mark.asyncio
async def test_fire_fires_again_once_previous_run_reaches_a_terminal_status(client):
    token, tenant_id, user_id = await _register(client, "firereterm")
    agent_id = await _hire_agent(tenant_id)
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {"source_id": source_id})

    first = await fire_scheduled_task(schedule_id)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == first["task_id"]))
        task = r.scalar_one()
        task.status = TaskStatus.COMPLETED
        await db.commit()

    second = await fire_scheduled_task(schedule_id)
    assert second["outcome"] == "fired"
    assert second["task_id"] != first["task_id"]


@pytest.mark.asyncio
async def test_fire_is_a_noop_for_an_already_inactive_schedule(client):
    token, tenant_id, user_id = await _register(client, "fireinactive")
    agent_id = await _hire_agent(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {}, active=False)

    outcome = await fire_scheduled_task(schedule_id)
    assert outcome["outcome"] == "not_found_or_inactive"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.originating_schedule_id == schedule_id))
        assert r.first() is None


# ---------------------------------------------------------------------------
# Deactivation with notification -- three causes, three specific messages
# (explicit requirement: names the cause and the fix, not just "stopped")
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_deactivates_and_notifies_when_owner_is_deactivated(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "fireownerdead")
    agent_id = await _hire_agent(tenant_id)
    analyst_token, analyst_id = await _member(tenant_id, "data_analyst", "fireownerdeadowner")
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, analyst_id, {"source_id": source_id})
    await _set_user(analyst_id, is_active=False)

    captured = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await fire_scheduled_task(schedule_id)
    assert outcome == {"outcome": "deactivated", "cause": "owner_inactive"}

    schedule = await _get_schedule(schedule_id)
    assert schedule.active is False
    assert "no longer an active member" in schedule.deactivation_reason
    assert "Fix:" in schedule.deactivation_reason

    assert len(captured) == 1
    payload_text = json.dumps(captured[0])
    assert "no longer an active member" in payload_text
    assert "owner_inactive" in payload_text

    # No task was created for a run that can't proceed.
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.originating_schedule_id == schedule_id))
        assert r.first() is None


@pytest.mark.asyncio
async def test_fire_deactivates_and_notifies_when_owner_loses_permission(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "fireownerperm")
    agent_id = await _hire_agent(tenant_id)
    analyst_token, analyst_id = await _member(tenant_id, "data_analyst", "fireownerpermowner")
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, analyst_id, {"source_id": source_id})
    await _set_user(analyst_id, role="viewer")  # viewer lacks sources.profile

    captured = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await fire_scheduled_task(schedule_id)
    assert outcome == {"outcome": "deactivated", "cause": "owner_permission"}

    schedule = await _get_schedule(schedule_id)
    assert "no longer has permission" in schedule.deactivation_reason
    assert "sync_source" in schedule.deactivation_reason
    assert "restore their role" in schedule.deactivation_reason

    payload_text = json.dumps(captured[0])
    assert "owner_permission" in payload_text
    assert "no longer has permission" in payload_text


@pytest.mark.asyncio
async def test_fire_deactivates_and_notifies_when_agent_is_offboarded(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "fireagentoff")
    agent_id = await _hire_agent(tenant_id)
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {"source_id": source_id})
    await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    # offboarding already deactivates active schedules for this agent (see
    # its own cascade test below); re-activate it here purely to exercise
    # fire_scheduled_task's OWN defensive re-check independently.
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ScheduledAgentTask).where(ScheduledAgentTask.id == schedule_id))
        schedule = r.scalar_one()
        schedule.active = True
        schedule.deactivation_reason = None
        await db.commit()

    captured = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await fire_scheduled_task(schedule_id)
    assert outcome == {"outcome": "deactivated", "cause": "agent_offboarded"}

    schedule = await _get_schedule(schedule_id)
    assert "offboarded" in schedule.deactivation_reason
    assert "different agent" in schedule.deactivation_reason

    payload_text = json.dumps(captured[0])
    assert "agent_offboarded" in payload_text


@pytest.mark.asyncio
async def test_fire_deactivates_and_notifies_when_source_is_deleted(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "firesourcegone")
    agent_id = await _hire_agent(tenant_id)
    source_id = await _create_source(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {"source_id": source_id})

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(DataSource.id == source_id))
        await db.delete(r.scalar_one())
        await db.commit()

    captured = []
    _spy_urlopen(monkeypatch, captured)

    outcome = await fire_scheduled_task(schedule_id)
    assert outcome == {"outcome": "deactivated", "cause": "source_missing"}

    schedule = await _get_schedule(schedule_id)
    assert "no longer exists" in schedule.deactivation_reason
    assert "source_id" in schedule.deactivation_reason

    payload_text = json.dumps(captured[0])
    assert "source_missing" in payload_text


@pytest.mark.asyncio
async def test_deactivation_notification_is_best_effort(client, monkeypatch):
    """A notification-delivery failure must never prevent the actual
    deactivation it's describing -- same contract as every other
    notification call site in this codebase."""
    token, tenant_id, _ = await _register(client, "firenotifyfail")
    agent_id = await _hire_agent(tenant_id)
    analyst_token, analyst_id = await _member(tenant_id, "data_analyst", "firenotifyfailowner")
    schedule_id = await _create_schedule(tenant_id, agent_id, analyst_id, {})
    await _set_user(analyst_id, is_active=False)

    def broken_urlopen(req, timeout=10):
        raise ConnectionError("simulated notification outage")
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", broken_urlopen)

    outcome = await fire_scheduled_task(schedule_id)  # must not raise
    assert outcome["outcome"] == "deactivated"

    schedule = await _get_schedule(schedule_id)
    assert schedule.active is False  # the real state change still happened


# ---------------------------------------------------------------------------
# Offboarding cascade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offboarding_deactivates_active_schedules_with_notification(client, monkeypatch):
    """Explicit decision: deactivate-with-notification, not block --
    matching the agent_sources/channel-membership/project-membership
    precedent (standing config survives offboarding, never gates it),
    not the non-terminal-task block (which is about live, in-flight
    execution)."""
    token, tenant_id, user_id = await _register(client, "offboardcascade")
    agent_id = await _hire_agent(tenant_id)
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {})

    captured = []
    _spy_urlopen(monkeypatch, captured)

    r = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert r.status_code == 200

    schedule = await _get_schedule(schedule_id)
    assert schedule.active is False
    assert "offboarded" in schedule.deactivation_reason

    payload_text = json.dumps(captured[-1])
    assert "agent_offboarded" in payload_text


@pytest.mark.asyncio
async def test_offboarding_does_not_touch_other_agents_schedules(client):
    token, tenant_id, user_id = await _register(client, "offboardscope")
    agent_id = await _hire_agent(tenant_id, name="Offboarded One")
    other_agent_id = await _hire_agent(tenant_id, name="Untouched One")
    schedule_id = await _create_schedule(tenant_id, agent_id, user_id, {})
    other_schedule_id = await _create_schedule(tenant_id, other_agent_id, user_id, {})

    await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))

    assert (await _get_schedule(schedule_id)).active is False
    assert (await _get_schedule(other_schedule_id)).active is True


@pytest.mark.asyncio
async def test_offboarding_still_blocked_by_non_terminal_task_regardless_of_active_schedules(client):
    """Confirms the existing precedent (point 1 of offboard_agent) is
    unchanged by this slice: a live, in-flight task still blocks
    offboarding even though a dormant schedule now deactivates instead."""
    token, tenant_id, user_id = await _register(client, "offboardstillblocked")
    agent_id = await _hire_agent(tenant_id)
    await _create_schedule(tenant_id, agent_id, user_id, {})
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="still running", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.RUNNING, step_budget_max=20,
        )
        db.add(task)
        await db.commit()

    r = await client.post(f"/api/v1/agents/{agent_id}/offboard", headers=_auth(token))
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Beat tick: cron matching + dispatch (mirrors test_scheduled_pipelines.py's
# own technique for the sibling pipeline scheduler)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_scheduled_agent_tasks_fires_matching_cron_and_skips_others(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "beatcron")
    agent_id = await _hire_agent(tenant_id)
    due = await _create_schedule(tenant_id, agent_id, user_id, {}, schedule_cron="* * * * *")
    never_due = await _create_schedule(tenant_id, agent_id, user_id, {}, schedule_cron="0 0 1 1 *")
    inactive = await _create_schedule(tenant_id, agent_id, user_id, {}, schedule_cron="* * * * *", active=False)

    import services.tasks as tasks_module
    fired = []

    class FakeDelay:
        def delay(self, schedule_id):
            fired.append(schedule_id)
    monkeypatch.setattr(tasks_module, "fire_scheduled_agent_task", FakeDelay())

    dispatched = await _check_scheduled_agent_tasks()

    assert due in fired
    assert never_due not in fired
    assert inactive not in fired
    # Not an exact count: _check_scheduled_agent_tasks() is deliberately
    # unscoped across every tenant (same as its sibling
    # _check_scheduled_pipelines()), so any other due, active schedule
    # already sitting in the shared dev DB fires alongside this test's own
    # -- the three membership assertions above are what actually verify
    # this function's behavior, not the total dispatched count.
    assert dispatched >= 1
    assert dispatched == len(fired)


@pytest.mark.asyncio
async def test_check_scheduled_agent_tasks_invalid_cron_does_not_crash(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "beatbadcron")
    agent_id = await _hire_agent(tenant_id)
    bad = await _create_schedule(tenant_id, agent_id, user_id, {}, schedule_cron="not a cron")
    good = await _create_schedule(tenant_id, agent_id, user_id, {}, schedule_cron="* * * * *")

    import services.tasks as tasks_module
    fired = []

    class FakeDelay:
        def delay(self, schedule_id):
            fired.append(schedule_id)
    monkeypatch.setattr(tasks_module, "fire_scheduled_agent_task", FakeDelay())

    await _check_scheduled_agent_tasks()  # must not raise

    assert good in fired
    assert bad not in fired
