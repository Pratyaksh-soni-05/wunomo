"""Regression test for check_post_deploy_health / _check_all_monitored()
(Integration Phase 4, the fifth confirmed instance of "a Celery/beat
function uses a bare/unscoped session and RLS silently hides every row" --
see GOTCHAS). _check_all_monitored() used to open its own fresh engine
with no tenant context at all and query pipeline_deployments (RLS-
protected) completely unscoped -- under real RLS that returned zero rows,
for every tenant, on every tick. check_post_deploy_health is the CI/CD
auto-rollback safety net, so this was silently disabling it in production,
not just a test gap.

The property that was silently false and must be pinned down: a deployment
belonging to ANY tenant is visible and gets processed when the sweep runs,
not just that the sweep runs without erroring. A single-tenant test would
not have caught the original bug (a single unscoped query can still
"happen" to return that one tenant's own rows under some RLS
misconfigurations); two independent tenants, both processed in the same
sweep, is what actually proves the per-tenant scoping loop works."""
import uuid

import pytest

from models.all_models import Pipeline, PipelineStatus
from models.cicd import PipelineCommit, PipelineDeployment, DeploymentStatus
from services.cicd_monitor import _check_all_monitored, MONITORING_RUN_WINDOW, MAX_ALLOWED_FAILURES
from services.tenant_context import tenant_session


async def _register(client, prefix):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "CICD Monitor Test",
        "tenant_name": f"CICD Monitor Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()["tenant_id"]


async def _seed_failing_deployment(tenant_id: str) -> str:
    """A deployment already past both thresholds -- monitoring_active,
    run_count >= MONITORING_RUN_WINDOW, failure_count >= MAX_ALLOWED_
    FAILURES -- so a real sweep that finds it will always roll it back."""
    pipeline_id = str(uuid.uuid4())
    commit_id = str(uuid.uuid4())
    deployment_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        db.add(Pipeline(id=pipeline_id, tenant_id=tenant_id, name="p", status=PipelineStatus.ACTIVE))
        await db.flush()
        db.add(PipelineCommit(id=commit_id, tenant_id=tenant_id, pipeline_id=pipeline_id,
                               commit_sha="a" * 40, branch="main"))
        await db.flush()
        db.add(PipelineDeployment(
            id=deployment_id, tenant_id=tenant_id, pipeline_id=pipeline_id, commit_id=commit_id,
            commit_sha="a" * 40, status=DeploymentStatus.active, monitoring_active=True,
            post_deploy_run_count=MONITORING_RUN_WINDOW,
            post_deploy_failure_count=MAX_ALLOWED_FAILURES,
            rollback_commit_sha="b" * 40,
        ))
        await db.commit()
    return deployment_id


async def _deployment_status(tenant_id: str, deployment_id: str):
    from sqlalchemy import select
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(PipelineDeployment).where(PipelineDeployment.id == deployment_id))
        return r.scalar_one()


@pytest.mark.asyncio
async def test_check_post_deploy_health_processes_deployments_across_multiple_tenants(client):
    """The exact property that was silently false before this fix: a
    deployment belonging to a tenant that is NOT whichever tenant happens
    to run first must still be found and processed in the same sweep.
    Before the fix this asserted 0 == 2 -- _check_all_monitored() found
    nothing for either tenant, ever."""
    tenant_a = await _register(client, "cicdmonA")
    tenant_b = await _register(client, "cicdmonB")

    deployment_a = await _seed_failing_deployment(tenant_a)
    deployment_b = await _seed_failing_deployment(tenant_b)

    await _check_all_monitored()

    row_a = await _deployment_status(tenant_a, deployment_a)
    row_b = await _deployment_status(tenant_b, deployment_b)

    assert row_a.status == DeploymentStatus.rolled_back, \
        "tenant A's failing deployment was not found/processed by the sweep"
    assert row_b.status == DeploymentStatus.rolled_back, \
        "tenant B's failing deployment was not found/processed by the sweep " \
        "(this is the cross-tenant visibility that was silently broken)"
    assert row_a.monitoring_active is False
    assert row_b.monitoring_active is False
    assert row_a.rolled_back_at is not None
    assert row_b.rolled_back_at is not None


@pytest.mark.asyncio
async def test_check_post_deploy_health_leaves_healthy_deployment_untouched(client):
    """A deployment that hasn't crossed the failure threshold must survive
    the sweep unchanged -- proves the fix's per-tenant loop isn't somehow
    rolling back everything it touches regardless of state."""
    tenant_id = await _register(client, "cicdmonC")
    pipeline_id = str(uuid.uuid4())
    commit_id = str(uuid.uuid4())
    deployment_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        db.add(Pipeline(id=pipeline_id, tenant_id=tenant_id, name="p", status=PipelineStatus.ACTIVE))
        await db.flush()
        db.add(PipelineCommit(id=commit_id, tenant_id=tenant_id, pipeline_id=pipeline_id,
                               commit_sha="c" * 40, branch="main"))
        await db.flush()
        db.add(PipelineDeployment(
            id=deployment_id, tenant_id=tenant_id, pipeline_id=pipeline_id, commit_id=commit_id,
            commit_sha="c" * 40, status=DeploymentStatus.active, monitoring_active=True,
            post_deploy_run_count=MONITORING_RUN_WINDOW, post_deploy_failure_count=0,
            rollback_commit_sha="d" * 40,
        ))
        await db.commit()

    await _check_all_monitored()

    row = await _deployment_status(tenant_id, deployment_id)
    assert row.status == DeploymentStatus.active
    assert row.monitoring_active is False  # healthy -> monitoring turned off, not rolled back
    assert row.rolled_back_at is None
