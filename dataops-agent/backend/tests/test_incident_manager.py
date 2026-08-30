import uuid
import pytest
from unittest.mock import AsyncMock
from langchain_core.messages import AIMessage

from database import AsyncSessionLocal
from models.all_models import Incident, IncidentStatus, IncidentSeverity, LlmUsageEvent
from modules.observability.incident_manager import IncidentManager
from services.llm_service import LLMService
import services.llm_service as llm_service_module


async def _make_incident(tenant_id: str, status=IncidentStatus.OPEN) -> Incident:
    async with AsyncSessionLocal() as db:
        incident = Incident(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            title="test incident",
            description="something broke",
            severity=IncidentSeverity.HIGH,
            status=status,
        )
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        return incident


@pytest.mark.asyncio
async def test_llm_service_complete_delegates_to_invoke_llm(monkeypatch):
    """Regression test: incident_manager.py imported a nonexistent `LLMService`
    class from services.llm_service — instantiating IncidentManager raised
    ImportError before this fix. LLMService must now exist and its .complete()
    must delegate to the already-tested invoke_llm() primary->fallback path."""
    captured = {}

    async def fake_invoke_llm(messages, temperature=0.0, **kwargs):
        captured["messages"] = messages
        captured["temperature"] = temperature
        captured["kwargs"] = kwargs
        return "fake completion"

    monkeypatch.setattr(llm_service_module, "invoke_llm", fake_invoke_llm)

    result = await LLMService().complete("do the thing", tenant_id="t1", request_type="incident_triage")
    assert result == "fake completion"
    assert captured["messages"][0].content == "do the thing"
    assert captured["kwargs"]["tenant_id"] == "t1"
    assert captured["kwargs"]["request_type"] == "incident_triage"


@pytest.mark.asyncio
async def test_resolve_incident_marks_resolved_and_rejects_double_resolve(client):
    """Regression test: resolve_incident() compared against IncidentStatus.resolved
    (lowercase attribute, doesn't exist on the uppercase-member enum) which raised
    AttributeError on every call. Must now use IncidentStatus.RESOLVED."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"incidenttest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Incident Test",
        "tenant_name": "Incident Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]
    incident = await _make_incident(tenant_id)

    mgr = IncidentManager(tenant_id)
    result = await mgr.resolve_incident(incident.id, "fixed it")
    assert result.get("status") == "resolved"
    assert "error" not in result

    async with AsyncSessionLocal() as db:
        refreshed = await db.get(Incident, incident.id)
    assert refreshed.status == IncidentStatus.RESOLVED
    assert refreshed.resolution_notes == "fixed it"

    # Calling resolve again must hit the "already resolved" branch, not crash.
    second = await mgr.resolve_incident(incident.id, "fixed it again")
    assert "already resolved" in second.get("error", "")


@pytest.mark.asyncio
async def test_triage_incident_updates_status_via_llm(client, monkeypatch):
    """Regression test: triage_incident() compared against/assigned
    IncidentStatus.open / IncidentStatus.investigating (lowercase), which
    raised AttributeError before this fix. Mocks the LLM call itself (same
    pattern as test_llm_service.py's _FakeLLM) so this test doesn't depend on
    external LLM quota."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"incidenttest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Incident Test 2",
        "tenant_name": "Incident Test Corp 2",
    })
    tenant_id = reg.json()["tenant_id"]
    incident = await _make_incident(tenant_id, status=IncidentStatus.OPEN)

    async def fake_complete(self, prompt, temperature=0.0, **kwargs):
        return (
            '{"root_cause": "disk full", "remediation_actions": ["free space"], '
            '"suggested_severity": "high", "confidence": "high", "summary": "disk full"}'
        )

    monkeypatch.setattr(LLMService, "complete", fake_complete)

    mgr = IncidentManager(tenant_id)
    result = await mgr.triage_incident(incident.id)

    assert "error" not in result
    assert result["root_cause"] == "disk full"

    async with AsyncSessionLocal() as db:
        refreshed = await db.get(Incident, incident.id)
    assert refreshed.status == IncidentStatus.INVESTIGATING
    assert refreshed.root_cause == "disk full"


@pytest.mark.asyncio
async def test_observability_tools_call_real_incident_manager_methods(client, monkeypatch):
    """Regression test for the original bug: agent/tools/observability_tools.py
    called IncidentManager.list_open()/.triage()/.resolve(), none of which
    exist (real methods: list_incidents/triage_incident/resolve_incident).
    Calls the actual @tool-wrapped functions the agent invokes, not the
    IncidentManager methods directly, so a future rename mismatch is caught
    here again."""
    from agent.tools.observability_tools import (
        list_open_incidents, triage_incident, resolve_incident,
    )

    reg = await client.post("/api/v1/auth/register", json={
        "email": f"incidenttest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Incident Test 3",
        "tenant_name": "Incident Test Corp 3",
    })
    tenant_id = reg.json()["tenant_id"]
    incident = await _make_incident(tenant_id, status=IncidentStatus.OPEN)

    listed = await list_open_incidents.ainvoke({"tenant_id": tenant_id})
    assert isinstance(listed, list)
    assert any(i["incident_id"] == incident.id for i in listed)

    async def fake_complete(self, prompt, temperature=0.0, **kwargs):
        return '{"root_cause": "x", "remediation_actions": [], "suggested_severity": "low", "confidence": "low", "summary": "x"}'
    monkeypatch.setattr(LLMService, "complete", fake_complete)

    triaged = await triage_incident.ainvoke({"tenant_id": tenant_id, "incident_id": incident.id})
    assert "error" not in triaged

    resolved = await resolve_incident.ainvoke({
        "tenant_id": tenant_id, "incident_id": incident.id, "resolution_notes": "done",
    })
    assert resolved.get("status") == "resolved"


@pytest.mark.asyncio
async def test_triage_incident_tool_threads_task_id_and_user_id_to_a_real_usage_row(client, monkeypatch):
    """End-to-end proof for the task_id/user_id injection convention: calling
    the triage_incident TOOL (not IncidentManager directly, and not mocking
    LLMService.complete like the other tests here) with task_id/user_id must
    produce a real llm_usage_events row carrying both - this is the
    proof-of-concept that a tool-internal LLM call (invisible to
    task_executor's own accounting today) can now be attributed to the task
    that triggered it. Mocks get_primary_llm (not LLMService.complete) so
    invoke_llm()'s real body runs, including its real log_llm_usage() call -
    same pattern as test_llm_usage_metering.py's
    test_invoke_llm_passes_usage_metadata_to_logger."""
    from sqlalchemy import select
    from agent.tools.observability_tools import triage_incident

    reg = await client.post("/api/v1/auth/register", json={
        "email": f"incidenttest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Incident Test 4",
        "tenant_name": "Incident Test Corp 4",
    })
    tenant_id = reg.json()["tenant_id"]
    incident = await _make_incident(tenant_id, status=IncidentStatus.OPEN)

    fake_primary = AsyncMock()
    fake_primary.ainvoke = AsyncMock(return_value=AIMessage(
        content='{"root_cause": "x", "remediation_actions": [], "suggested_severity": "low", '
                '"confidence": "low", "summary": "x"}',
        usage_metadata={"input_tokens": 11, "output_tokens": 22, "total_tokens": 33},
    ))
    monkeypatch.setattr(llm_service_module, "get_primary_llm", lambda temperature=0.0: fake_primary)

    fake_task_id = str(uuid.uuid4())
    fake_user_id = str(uuid.uuid4())
    result = await triage_incident.ainvoke({
        "tenant_id": tenant_id, "incident_id": incident.id,
        "user_id": fake_user_id, "task_id": fake_task_id,
    })
    assert "error" not in result

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(LlmUsageEvent).where(
                LlmUsageEvent.tenant_id == tenant_id, LlmUsageEvent.request_type == "incident_triage",
            )
        )
        events = r.scalars().all()

    assert len(events) == 1
    assert events[0].task_id == fake_task_id
    assert events[0].user_id == fake_user_id
    assert events[0].total_tokens == 33
