"""Wunomo Projects Phase 2 frontend, slice 9: the three denial types
(scope, source lock, budget) actually telling a user what to do next, not
just what went wrong -- across chat, a task step, and an unattended beat
tick. Covers only the NEW backend logic this slice adds; the underlying
gates themselves (agent_scope.py, source_lock.py, quota_service.py) are
already covered by their own test files.
"""
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
import modules.reporting.notification_service as notification_service_module
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, AgentSource, DataSource, Incident,
    IncidentStatus, OperationMode, PersonalityMode, SourceType, Task, TaskShape, TaskStatus,
    TaskStep, TaskStepSource, TaskStepStatus,
)
from modules.orchestration.task_executor import _notify_scope_denial_once, execute_next_step
from services.settings_service import update_tenant_settings
from api.v1.chat import _extract_tool_trace


async def _register(client, prefix="denialui"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Denial UI Test",
        "tenant_name": f"Denial UI Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _make_source(tenant_id: str, name="Source") -> str:
    async with AsyncSessionLocal() as db:
        source = DataSource(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, source_type=SourceType.POSTGRES, connection_config={})
        db.add(source)
        await db.commit()
        return source.id


async def _make_agent(tenant_id: str, name="Nova") -> str:
    async with AsyncSessionLocal() as db:
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, employee_type=AgentEmployeeType.DATAOPS,
            personality=PersonalityMode.ENGINEER, operation_mode=OperationMode.ASSISTED,
            model="gemini-3.5-flash", status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        await db.commit()
        return agent.id


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


async def _seed_task(tenant_id, user_id, agent_id, tool_name, tool_args, created_ids):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="Sync the warehouse", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.RUNNING, step_budget_max=20, started_at=datetime.utcnow(),
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0, description="sync it",
            source=TaskStepSource.LLM_PLANNED, tool_name=tool_name, tool_args=tool_args,
            status=TaskStepStatus.PENDING,
        )
        db.add(step)
        await db.commit()
        created_ids.append(task.id)
        return task.id


@pytest.fixture
def created_task_ids():
    ids = []
    yield ids


# ---------------------------------------------------------------------------
# 1. Scope denial: structured fields carried through to the task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scope_denied_task_step_pause_reason_names_unresumable(client, created_task_ids):
    """The denial must say the task is unrecoverable, not just what went
    wrong -- explicit requirement. PAUSED_FAILED_STEP has no resume path
    for any cause, so this applies to the whole status, not just scope."""
    token, tenant_id, user_id = await _register(client, "denialA")
    source_id = await _make_source(tenant_id, "Warehouse")
    agent_id = await _make_agent(tenant_id, "Nova")
    task_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_id}, created_task_ids)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"

    resp = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))
    body = resp.json()
    assert body["status"] == "paused_failed_step"
    assert "isn't scoped" in body["pause_reason"]
    assert "can't be resumed" in body["pause_reason"]
    assert "start a new one" in body["pause_reason"]


@pytest.mark.asyncio
async def test_scope_denied_task_serializes_grant_ids_for_a_real_link(client, created_task_ids):
    """scope_denial{agent_id, source_id} lets the frontend build a real,
    pre-scoped 'Grant access' link without parsing ids out of prose."""
    token, tenant_id, user_id = await _register(client, "denialB")
    source_id = await _make_source(tenant_id, "Warehouse")
    agent_id = await _make_agent(tenant_id, "Nova")
    task_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_id}, created_task_ids)

    await execute_next_step(task_id)

    resp = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))
    body = resp.json()
    assert body["scope_denial"] == {"agent_id": agent_id, "source_id": source_id}


@pytest.mark.asyncio
async def test_non_scope_pause_has_no_scope_denial_ids(client, created_task_ids):
    """A task that completes normally (or fails for any other reason)
    must not carry stale/fabricated scope_denial data."""
    token, tenant_id, user_id = await _register(client, "denialC")
    agent_id = await _make_agent(tenant_id, "Nova")
    # get_system_health is NOT_SOURCE_SCOPED -- always allowed, real success.
    task_id = await _seed_task(tenant_id, user_id, agent_id, "get_system_health", {}, created_task_ids)

    await execute_next_step(task_id)

    resp = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))
    assert resp.json()["scope_denial"] is None


# ---------------------------------------------------------------------------
# 2. Scope-denial notification: fires once, names the fix, dedups
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scope_denial_notifies_with_the_fix_and_the_consequence(client, monkeypatch, created_task_ids):
    token, tenant_id, user_id = await _register(client, "denialD")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/DENIAL_TEST")
    source_id = await _make_source(tenant_id, "Warehouse")
    agent_id = await _make_agent(tenant_id, "Nova")
    task_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_id}, created_task_ids)

    captured_urls: list = []
    captured_payloads: list = []
    _spy_urlopen(monkeypatch, captured_urls)
    orig_urlopen = notification_service_module.urllib.request.urlopen

    def spy_and_capture_payload(req, timeout=10):
        captured_payloads.append(json.loads(req.data.decode("utf-8")))
        return orig_urlopen(req, timeout=timeout)
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", spy_and_capture_payload)

    await execute_next_step(task_id)

    assert len(captured_urls) == 1
    message_text = json.dumps(captured_payloads[0])
    assert "Nova" in message_text
    assert "Warehouse" in message_text
    assert "Sync the warehouse" in message_text  # the real task goal
    assert f"/agents/{agent_id}" in message_text  # the real grant link
    assert "can't be resumed" in message_text
    assert "start a new one" in message_text


@pytest.mark.asyncio
async def test_scope_denial_notification_deduped_across_tasks(client, monkeypatch, created_task_ids):
    """Explicit requirement: several tasks hitting the identical (agent,
    source) gap must not become several alerts for one real cause."""
    token, tenant_id, user_id = await _register(client, "denialE")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/DEDUP_TEST")
    source_id = await _make_source(tenant_id, "Warehouse")
    agent_id = await _make_agent(tenant_id, "Nova")
    task_a = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_id}, created_task_ids)
    task_b = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_id}, created_task_ids)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    await execute_next_step(task_a)
    await execute_next_step(task_b)

    assert len(captured) == 1, "one real (agent, source) cause must produce exactly one alert, not one per task"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Incident).where(
            Incident.tenant_id == tenant_id, Incident.status == IncidentStatus.OPEN, Incident.title.like("Scope gap:%"),
        ))
        incidents = r.scalars().all()
    assert len(incidents) == 1
    assert incidents[0].affected_assets == [agent_id, source_id]


@pytest.mark.asyncio
async def test_scope_denial_notification_not_deduped_across_different_causes(client, monkeypatch, created_task_ids):
    """A genuinely different (agent, source) pair is a different cause and
    must alert separately -- dedup must be keyed on the real pair, not
    just 'any scope denial happened'."""
    token, tenant_id, user_id = await _register(client, "denialF")
    await _configure_webhook(tenant_id, "https://hooks.slack.com/services/DEDUP_TEST2")
    source_1 = await _make_source(tenant_id, "Warehouse 1")
    source_2 = await _make_source(tenant_id, "Warehouse 2")
    agent_id = await _make_agent(tenant_id, "Nova")
    task_a = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_1}, created_task_ids)
    task_b = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_2}, created_task_ids)

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    await execute_next_step(task_a)
    await execute_next_step(task_b)

    assert len(captured) == 2


@pytest.mark.asyncio
async def test_notify_scope_denial_once_is_best_effort(client, monkeypatch):
    """Matches _notify_task_stopped's own contract: a delivery failure
    must never raise out of the caller -- the state transition it
    describes already committed."""
    token, tenant_id, user_id = await _register(client, "denialG")
    agent_id = await _make_agent(tenant_id, "Nova")
    source_id = await _make_source(tenant_id, "Warehouse")

    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.PAUSED_FAILED_STEP, step_budget_max=20,
        )
        db.add(task)
        await db.commit()

    async def _boom(*a, **k):
        raise RuntimeError("simulated notification transport failure")
    monkeypatch.setattr(notification_service_module.NotificationService, "send_alert", _boom)

    scope_denial = {
        "message": "denied", "agent_id": agent_id, "agent_name": "Nova",
        "source_id": source_id, "source_name": "Warehouse", "tool_name": "sync_source",
    }
    await _notify_scope_denial_once(task, scope_denial)  # must not raise


# ---------------------------------------------------------------------------
# 3. Budget exhaustion: agent_id in the 402, so the frontend can link to it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_budget_exceeded_402_carries_agent_id(client, monkeypatch):
    """Without agent_id, a frontend catching this 402 has no way to link
    to the one agent whose budget is actually the problem."""
    token, tenant_id, user_id = await _register(client, "denialH")
    agent_id = await _make_agent(tenant_id, "Nova")

    from api.v1 import auth as auth_module

    async def _exceeded(agent_id_arg):
        return {"resource": "agent_tokens", "status": "exceeded", "used": 5000, "limit": 5000}
    monkeypatch.setattr("services.quota_service.get_agent_quota_status", _exceeded)

    with pytest.raises(Exception) as exc_info:
        await auth_module.enforce_agent_budget(agent_id)
    detail = exc_info.value.detail
    assert detail["error"] == "agent_budget_exceeded"
    assert detail["agent_id"] == agent_id


# ---------------------------------------------------------------------------
# 4. Quota-paused reason: real cause, not hardcoded "tenant"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quota_paused_reason_reflects_real_agent_budget_cause_not_hardcoded_tenant(client, created_task_ids):
    """Two genuinely different causes shared PAUSED_QUOTA_EXCEEDED, and
    the read-time serializer used to always say "tenant's AI-credit
    quota" even when the real persisted cause (step.error_message) named
    the agent's own budget instead."""
    token, tenant_id, user_id = await _register(client, "denialI")
    agent_id = await _make_agent(tenant_id, "Nova")

    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.PAUSED_QUOTA_EXCEEDED, step_budget_max=20,
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0, description="check health",
            source=TaskStepSource.LLM_PLANNED, tool_name="get_system_health", tool_args={},
            status=TaskStepStatus.PENDING, attempt_count=1,
            error_message="Paused: this agent's monthly token budget (5000/5000 tokens) is exhausted.",
        )
        db.add(step)
        await db.commit()
        created_task_ids.append(task.id)

    resp = await client.get(f"/api/v1/tasks/{task.id}", headers=_auth(token))
    reason = resp.json()["quota_paused_reason"]
    assert "this agent's monthly token budget" in reason
    assert "tenant's AI-credit quota" not in reason


# ---------------------------------------------------------------------------
# 5. Chat trace: a source-lock conflict must not render as a plain success
# ---------------------------------------------------------------------------

def test_extract_tool_trace_flags_a_lock_conflict_result():
    """A lock conflict is discovered only after the tool actually runs --
    it returns a normal-looking {"error": ..., "lock_conflict": True}
    result, not a pre-flight denial like scope/role. Without this check
    it renders as an ordinary "completed" trace entry, indistinguishable
    from a real success at the badge level."""
    from langchain_core.messages import AIMessage as LCAIMessage, ToolMessage as LCToolMessage

    ai_msg = LCAIMessage(content="", tool_calls=[
        {"id": "call_1", "name": "sync_source", "args": {"source_id": "src-1"}},
    ])
    tool_msg = LCToolMessage(
        content=json.dumps({"error": "This source is currently in use by Nova (since 09:14 UTC).", "lock_conflict": True}),
        tool_call_id="call_1",
    )

    trace = _extract_tool_trace([ai_msg, tool_msg], blocked_tool_calls=[], role_denied_calls=[])
    assert len(trace) == 1
    assert trace[0]["status"] == "denied_source_locked"


def test_extract_tool_trace_leaves_a_real_success_as_completed():
    """The lock-conflict detection must not misfire on an ordinary
    successful result that happens to be a dict with no lock_conflict key."""
    from langchain_core.messages import AIMessage as LCAIMessage, ToolMessage as LCToolMessage

    ai_msg = LCAIMessage(content="", tool_calls=[
        {"id": "call_1", "name": "list_data_sources", "args": {}},
    ])
    tool_msg = LCToolMessage(content=json.dumps({"sources": [{"id": "src-1", "name": "Warehouse"}]}), tool_call_id="call_1")

    trace = _extract_tool_trace([ai_msg, tool_msg], blocked_tool_calls=[], role_denied_calls=[])
    assert len(trace) == 1
    assert trace[0]["status"] == "completed"


def test_extract_tool_trace_scope_denied_carries_structured_ids():
    """The frontend needs agent_id/source_id directly on the trace entry
    to build a real "grant access" link -- not just the prose reason."""
    scope_denial = {
        "message": "'Nova' isn't scoped to access 'Warehouse'.",
        "agent_id": "agent-1", "agent_name": "Nova", "source_id": "src-1",
        "source_name": "Warehouse", "tool_name": "sync_source",
    }
    trace = _extract_tool_trace(
        [], blocked_tool_calls=[], role_denied_calls=[],
        scope_denied_calls=[{"name": "sync_source", "args": {"source_id": "src-1"}, "scope_denial": scope_denial}],
    )
    assert len(trace) == 1
    assert trace[0]["status"] == "denied_out_of_scope"
    assert trace[0]["agent_id"] == "agent-1"
    assert trace[0]["source_id"] == "src-1"
    assert trace[0]["agent_name"] == "Nova"
    assert trace[0]["source_name"] == "Warehouse"
