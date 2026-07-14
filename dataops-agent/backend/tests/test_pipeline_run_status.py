import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline, PipelineRun, SourceType, PipelineStatus, RunStatus
from modules.orchestration.dag_manager import DAGManager
from services.tasks import _execute_run


@pytest.mark.asyncio
async def test_run_marked_failed_when_sync_errors(client):
    """Regression test: ConnectorManager.sync() catches its own exceptions
    and returns {"error": ..., "status": "failed"} as a normal dict instead
    of raising. _execute_run() previously never checked that dict, so a
    pipeline run whose source sync failed outright (e.g. an uploaded file
    not visible to this container) was still marked RunStatus.SUCCESS with
    rows_processed=0. It must now be marked FAILED with a real error message.
    """
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"runstatus-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Run Status Test",
        "tenant_name": "Run Status Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]

    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name="missing file source",
            source_type=SourceType.CSV,
            connection_config={"file_path": "/root/dataops_uploads/does-not-exist.csv"},
        )
        db.add(source)
        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source.id,
            name="test pipeline",
            status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(source)
        await db.refresh(pipeline)

    dag = DAGManager(tenant_id)
    trigger_result = await dag.trigger_run(pipeline.id, triggered_by="test")
    run_id = trigger_result["run_id"]

    # _execute_run marks the run FAILED and then re-raises (by design, so
    # Celery's own retry logic in execute_pipeline_run sees the failure) —
    # the assertion here is on the persisted run status, not on this call
    # completing without error.
    with pytest.raises(RuntimeError):
        await _execute_run(run_id, pipeline.id, tenant_id)

    async with AsyncSessionLocal() as db:
        run = await db.get(PipelineRun, run_id)

    assert run.status == RunStatus.FAILED, (
        f"expected FAILED, got {run.status} (rows_processed={run.rows_processed})"
    )
    assert run.error_message
    assert "sync failed" in run.error_message.lower()


@pytest.mark.asyncio
async def test_run_marked_success_when_sync_succeeds(client):
    """No-regression check: a pipeline with no source_id (nothing to sync)
    must still complete as SUCCESS as before."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"runstatus-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Run Status Test 2",
        "tenant_name": "Run Status Test Corp 2",
    })
    tenant_id = reg.json()["tenant_id"]

    async with AsyncSessionLocal() as db:
        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=None,
            name="sourceless pipeline",
            status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)

    dag = DAGManager(tenant_id)
    trigger_result = await dag.trigger_run(pipeline.id, triggered_by="test")
    run_id = trigger_result["run_id"]

    await _execute_run(run_id, pipeline.id, tenant_id)

    async with AsyncSessionLocal() as db:
        run = await db.get(PipelineRun, run_id)

    assert run.status == RunStatus.SUCCESS
