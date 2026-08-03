"""End-to-end proof that approving a blocked AXIOM action actually
executes it -- the exact thing execute_approved_action()'s dispatch bug
broke for all 11 registered actions, and the exact thing that was
invisible for months because no test asserted the real side effect ever
happened (see CLAUDE.md's "PolicyEngine.execute_approved_action()"
Known-broken row).

Each test creates real state, requests approval via the real
PolicyEngine.create_request(), approves it, then re-reads the DB
directly to confirm the real underlying action genuinely ran -- not
just that the API response looked successful.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    ApprovalStatus, Incident, IncidentSeverity, IncidentStatus,
    Pipeline, PipelineStatus,
)
from modules.governance.policy_engine import PolicyEngine


async def _register(client, prefix="approvexec"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Approval Execution Test",
        "tenant_name": f"Approval Exec Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()


async def _make_active_pipeline(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        pipeline = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="test-pipeline",
            status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.commit()
        return pipeline.id


async def _make_open_incident(tenant_id: str) -> str:
    async with AsyncSessionLocal() as db:
        incident = Incident(
            id=str(uuid.uuid4()), tenant_id=tenant_id, title="test incident",
            severity=IncidentSeverity.MEDIUM, status=IncidentStatus.OPEN,
        )
        db.add(incident)
        await db.commit()
        return incident.id


@pytest.mark.asyncio
async def test_approving_pause_pipeline_actually_pauses_it(client):
    """The core proof: approving a real pause_pipeline request must
    actually flip the pipeline's status, not just move the approval
    record to EXECUTED while the pipeline stays untouched."""
    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    pipeline_id = await _make_active_pipeline(tenant_id)

    engine = PolicyEngine(tenant_id)
    request = await engine.create_request(
        user_id=reg["user_id"], session_id="s1", action_name="pause_pipeline",
        action_args={"pipeline_id": pipeline_id}, risk_level="medium",
        reason="test",
    )
    assert "error" not in request

    result = await engine.approve(request["approval_id"], reviewer="test@example.com")

    assert result["status"] == "executed", result
    assert "error" not in result["execution_result"], result["execution_result"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
        pipeline = r.scalar_one()
        assert pipeline.status == PipelineStatus.PAUSED, "pipeline was never actually paused"


@pytest.mark.asyncio
async def test_approving_resolve_incident_actually_resolves_it(client):
    """A second, independent registered action, proving the fix isn't
    specific to one lucky case."""
    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    incident_id = await _make_open_incident(tenant_id)

    engine = PolicyEngine(tenant_id)
    request = await engine.create_request(
        user_id=reg["user_id"], session_id="s1", action_name="resolve_incident",
        # IncidentManager.resolve_incident()'s real parameter is `notes`,
        # not `resolution_notes` -- action_args must match the real
        # target method's parameter names exactly, since they're passed
        # straight through as **kwargs.
        action_args={"incident_id": incident_id, "notes": "fixed for real"},
        risk_level="medium", reason="test",
    )
    result = await engine.approve(request["approval_id"], reviewer="test@example.com")

    assert result["status"] == "executed", result

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Incident).where(Incident.id == incident_id))
        incident = r.scalar_one()
        assert incident.status == IncidentStatus.RESOLVED, "incident was never actually resolved"
        assert incident.resolution_notes == "fixed for real"


@pytest.mark.asyncio
async def test_approve_rest_endpoint_actually_executes_the_real_action(client):
    """Full HTTP round trip, not just a direct PolicyEngine call -- proves
    the fix works through the real POST /approvals/{id}/approve path a
    user's browser actually hits."""
    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    token = reg["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pipeline_id = await _make_active_pipeline(tenant_id)

    engine = PolicyEngine(tenant_id)
    request = await engine.create_request(
        user_id=reg["user_id"], session_id="s1", action_name="pause_pipeline",
        action_args={"pipeline_id": pipeline_id}, risk_level="medium",
        reason="test",
    )

    r = await client.post(
        f"/api/v1/approvals/{request['approval_id']}/approve",
        json={"notes": "looks fine"}, headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "executed", body

    async with AsyncSessionLocal() as db:
        pr = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
        assert pr.scalar_one().status == PipelineStatus.PAUSED
