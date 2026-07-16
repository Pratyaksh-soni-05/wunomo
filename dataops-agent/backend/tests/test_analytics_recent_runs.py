import uuid
import pytest
from datetime import datetime, timedelta

from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline, PipelineRun, SourceType, PipelineStatus, RunStatus


async def _register(client, prefix="recentruns"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Recent Runs Test",
        "tenant_name": f"Recent Runs Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


async def _make_pipeline_with_runs(tenant_id, run_specs):
    """run_specs: list of (status, minutes_ago, rows_processed) tuples,
    oldest listed first — returns the created run ids in insertion order."""
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="test source",
            source_type=SourceType.CSV, connection_config={},
        )
        db.add(source)
        pipeline = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, source_id=source.id,
            name="Test Pipeline", status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.flush()

        run_ids = []
        for status, minutes_ago, rows in run_specs:
            run = PipelineRun(
                id=str(uuid.uuid4()), pipeline_id=pipeline.id, tenant_id=tenant_id,
                status=status, rows_processed=rows,
                created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            )
            db.add(run)
            run_ids.append(run.id)
        await db.commit()
    return pipeline.id, run_ids


@pytest.mark.asyncio
async def test_recent_runs_returns_real_data_newest_first(client):
    token, tenant_id = await _register(client)
    pipeline_id, run_ids = await _make_pipeline_with_runs(tenant_id, [
        (RunStatus.SUCCESS, 30, 100),
        (RunStatus.FAILED, 10, 0),
        (RunStatus.SUCCESS, 1, 250),
    ])

    r = await client.get("/api/v1/analytics/recent-runs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    runs = r.json()["runs"]

    assert len(runs) == 3
    # Newest first: the run created "1 minute ago" must be first.
    assert runs[0]["rows_processed"] == 250
    assert runs[0]["status"] == "success"
    assert runs[0]["pipeline_name"] == "Test Pipeline"
    assert runs[1]["status"] == "failed"
    assert runs[2]["rows_processed"] == 100


@pytest.mark.asyncio
async def test_recent_runs_respects_limit(client):
    token, tenant_id = await _register(client, "recentrunslimit")
    await _make_pipeline_with_runs(tenant_id, [
        (RunStatus.SUCCESS, 40, 1), (RunStatus.SUCCESS, 30, 2),
        (RunStatus.SUCCESS, 20, 3), (RunStatus.SUCCESS, 10, 4),
    ])

    r = await client.get("/api/v1/analytics/recent-runs?limit=2", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()["runs"]) == 2


@pytest.mark.asyncio
async def test_recent_runs_is_tenant_scoped(client):
    token_a, tenant_a = await _register(client, "recentrunsa")
    token_b, tenant_b = await _register(client, "recentrunsb")

    await _make_pipeline_with_runs(tenant_a, [(RunStatus.SUCCESS, 5, 111)])
    await _make_pipeline_with_runs(tenant_b, [(RunStatus.SUCCESS, 5, 222)])

    r_a = await client.get("/api/v1/analytics/recent-runs", headers={"Authorization": f"Bearer {token_a}"})
    r_b = await client.get("/api/v1/analytics/recent-runs", headers={"Authorization": f"Bearer {token_b}"})

    rows_a = {r["rows_processed"] for r in r_a.json()["runs"]}
    rows_b = {r["rows_processed"] for r in r_b.json()["runs"]}

    assert rows_a == {111}
    assert rows_b == {222}
