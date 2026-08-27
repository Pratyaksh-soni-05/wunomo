import uuid
import pytest
from sqlalchemy import delete

from database import AsyncSessionLocal
from models.all_models import DataSource, Incident, Pipeline, PipelineRun, User, UserWorkspacePreference, Tenant, SourceType, PipelineStatus, RunStatus
from modules.orchestration.dag_manager import DAGManager
from services.tasks import _execute_run


async def _delete_tenant_cascade(tenant_id: str):
    """Item 56: this file's two tests register a real tenant (via the real
    /auth/register endpoint, against the real shared dev DB - APP_ENV=test
    resolves to the same DB, see GOTCHAS.md) and previously never tore it
    down. One of them (test_run_marked_failed_when_sync_errors) leaves
    behind a DataSource whose last_profiled_at gets set once, at test-run
    time, by ConnectorManager.sync() (it stamps this even on a caught sync
    failure) and then never touched again - exactly the shape
    _check_freshness() flags as stale 24h later, so a leftover, un-torn-down
    tenant here silently starts accumulating real staleness incidents.
    Deletes in FK-safe order: PipelineRun/Incident reference pipelines and
    data_sources, which reference tenants, which users also reference."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PipelineRun).where(PipelineRun.tenant_id == tenant_id))
        await db.execute(delete(Incident).where(Incident.tenant_id == tenant_id))
        await db.execute(delete(Pipeline).where(Pipeline.tenant_id == tenant_id))
        await db.execute(delete(DataSource).where(DataSource.tenant_id == tenant_id))
        # issue_token_and_remember() (item 1's "log into last workspace
        # used" fix) writes one of these on every register/login - keyed by
        # email, FK to tenant_id, so it must go before the Tenant delete too.
        await db.execute(delete(UserWorkspacePreference).where(UserWorkspacePreference.tenant_id == tenant_id))
        await db.execute(delete(User).where(User.tenant_id == tenant_id))
        await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await db.commit()


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

    try:
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
    finally:
        await _delete_tenant_cascade(tenant_id)


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

    try:
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
    finally:
        await _delete_tenant_cascade(tenant_id)
