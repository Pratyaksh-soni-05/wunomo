import uuid
import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Incident, IncidentSeverity, IncidentStatus, PipelineRun, RunStatus


async def _register(client, prefix="pipedelete"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Pipeline Delete Test",
        "tenant_name": f"Pipeline Delete Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


@pytest.mark.asyncio
async def test_delete_pipeline_with_a_real_run_succeeds(client):
    """Regression: Pipeline's FKs from PipelineRun/QualityRule/Incident have
    no ON DELETE CASCADE, so a pipeline that has ever been triggered (the
    normal case, not an edge case) used to 500 on delete with an unhandled
    IntegrityError."""
    token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    pipe = await client.post("/api/v1/pipelines/", json={"name": "Runs Pipeline"}, headers=headers)
    pipeline_id = pipe.json()["id"]

    trigger = await client.post(f"/api/v1/pipelines/{pipeline_id}/trigger", headers=headers)
    assert trigger.status_code == 200

    r = await client.delete(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        remaining = await db.execute(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id))
        assert remaining.scalars().first() is None


@pytest.mark.asyncio
async def test_delete_pipeline_with_a_quality_rule_succeeds(client):
    token, tenant_id = await _register(client, "pipedeleterule")
    headers = {"Authorization": f"Bearer {token}"}

    pipe = await client.post("/api/v1/pipelines/", json={"name": "Rule Pipeline"}, headers=headers)
    pipeline_id = pipe.json()["id"]

    rule = await client.post("/api/v1/quality/", json={
        "pipeline_id": pipeline_id, "name": "not null check", "rule_type": "not_null", "column_name": "id",
    }, headers=headers)
    assert rule.status_code == 200

    r = await client.delete(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_pipeline_preserves_incident_history_with_refs_cleared(client):
    """Incidents are historical audit records, not pipeline-owned — they
    must survive pipeline deletion with their now-dangling FK columns
    cleared, not be deleted or block the delete."""
    token, tenant_id = await _register(client, "pipedeleteinc")
    headers = {"Authorization": f"Bearer {token}"}

    pipe = await client.post("/api/v1/pipelines/", json={"name": "Incident Pipeline"}, headers=headers)
    pipeline_id = pipe.json()["id"]

    async with AsyncSessionLocal() as db:
        run = PipelineRun(id=str(uuid.uuid4()), pipeline_id=pipeline_id, tenant_id=tenant_id, status=RunStatus.FAILED)
        db.add(run)
        await db.flush()
        incident = Incident(
            id=str(uuid.uuid4()), tenant_id=tenant_id, pipeline_id=pipeline_id, run_id=run.id,
            title="Real incident tied to this pipeline", severity=IncidentSeverity.HIGH, status=IncidentStatus.OPEN,
        )
        db.add(incident)
        await db.commit()
        incident_id = incident.id

    r = await client.delete(f"/api/v1/pipelines/{pipeline_id}", headers=headers)
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Incident).where(Incident.id == incident_id))
        surviving = result.scalar_one_or_none()
        assert surviving is not None, "incident must survive pipeline deletion"
        assert surviving.pipeline_id is None
        assert surviving.run_id is None
        assert surviving.title == "Real incident tied to this pipeline"


@pytest.mark.asyncio
async def test_delete_pipeline_is_tenant_scoped(client):
    token_a, tenant_a = await _register(client, "pipedeltena")
    token_b, tenant_b = await _register(client, "pipedeltenb")

    pipe = await client.post("/api/v1/pipelines/", json={"name": "Tenant A Pipeline"},
                              headers={"Authorization": f"Bearer {token_a}"})
    pipeline_id = pipe.json()["id"]

    r = await client.delete(f"/api/v1/pipelines/{pipeline_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 404
