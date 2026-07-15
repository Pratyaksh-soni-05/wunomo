import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline, PipelineRun, SourceType, PipelineStatus, RunStatus


async def _make_active_pipeline_with_failed_run(tenant_id: str):
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name="enum-regression source",
            source_type=SourceType.CSV,
            connection_config={"file_path": "/does/not/matter.csv"},
        )
        db.add(source)
        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source.id,
            name="enum-regression pipeline",
            status=PipelineStatus.ACTIVE,
            sla_minutes=60,
        )
        db.add(pipeline)
        run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline.id,
            tenant_id=tenant_id,
            status=RunStatus.FAILED,
            error_message="simulated failure",
        )
        db.add(run)
        await db.commit()
        await db.refresh(pipeline)
        await db.refresh(run)
        return pipeline, run


async def _register_tenant(client, name):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"enumtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Enum Regression Test",
        "tenant_name": name,
    })
    return reg.json()["tenant_id"]


@pytest.mark.asyncio
async def test_monitor_methods_no_attribute_error(client):
    """Regression test: Monitor.check_freshness()/get_system_health()/
    get_pipeline_stats() compared against PipelineStatus.active/RunStatus.success/
    RunStatus.failed (lowercase), which don't exist on these uppercase-member
    enums. Every call raised AttributeError, silently swallowed by the method's
    own try/except into {"error": "..."}. Must now return real data."""
    from modules.observability.monitor import Monitor

    tenant_id = await _register_tenant(client, "Monitor Enum Test Corp")
    pipeline, run = await _make_active_pipeline_with_failed_run(tenant_id)
    mon = Monitor(tenant_id)

    freshness = await mon.check_freshness()
    assert isinstance(freshness, list), f"expected a list, got error: {freshness}"

    health = await mon.get_system_health()
    assert "error" not in health, f"get_system_health failed: {health}"
    assert health["active_pipelines"] == 1
    assert health["total_runs_7d"] == 1
    assert health["failed_runs_7d"] == 1

    stats = await mon.get_pipeline_stats(pipeline.id)
    assert "error" not in stats, f"get_pipeline_stats failed: {stats}"
    assert stats["total_runs"] == 1
    assert stats["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_anomaly_detector_no_attribute_error(client):
    """Regression test for the same RunStatus.success/failed and
    PipelineStatus.active lowercase-attribute bug in anomaly_detector.py."""
    from modules.observability.anomaly_detector import AnomalyDetector

    tenant_id = await _register_tenant(client, "Anomaly Enum Test Corp")
    pipeline, run = await _make_active_pipeline_with_failed_run(tenant_id)
    detector = AnomalyDetector(tenant_id)

    single = await detector.detect_anomalies(pipeline.id)
    assert "error" not in single, f"detect_anomalies failed: {single}"

    all_result = await detector.detect_all_anomalies()
    assert "error" not in all_result, f"detect_all_anomalies failed: {all_result}"
    assert all_result["pipelines_checked"] == 1


@pytest.mark.asyncio
async def test_scheduler_sync_all_no_attribute_error(client):
    """Regression test for the same PipelineStatus.active lowercase-attribute
    bug in scheduler.py's register()/sync_all()."""
    from modules.orchestration.scheduler import Scheduler

    tenant_id = await _register_tenant(client, "Scheduler Enum Test Corp")
    pipeline, run = await _make_active_pipeline_with_failed_run(tenant_id)
    sched = Scheduler()

    result = await sched.sync_all(tenant_id)
    assert "error" not in result, f"sync_all failed: {result}"
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_business_rules_pipeline_success_rate_no_attribute_error(client):
    """Regression test for two bugs in business_rules.py: (1) importing a
    nonexistent RuleEngine class (real name: QualityRuleEngine), which made
    the whole module unimportable; (2) RunStatus.success/failed lowercase
    attribute access in _check_pipeline_success_rate."""
    from modules.quality.business_rules import BusinessRules

    tenant_id = await _register_tenant(client, "BusinessRules Enum Test Corp")
    pipeline, run = await _make_active_pipeline_with_failed_run(tenant_id)
    rules = BusinessRules(tenant_id)

    result = await rules._check_pipeline_success_rate({
        "pipeline_id": pipeline.id, "min_success_rate_pct": 90, "window_days": 7,
    })
    assert result["status"] == "fail"
    assert result["total_runs"] == 1
    assert result["success_runs"] == 0


@pytest.mark.asyncio
async def test_report_generator_all_modes_no_attribute_error(client):
    """Regression test for RunStatus.success/failed, PipelineStatus.active, and
    IncidentStatus.open/investigating/resolved lowercase-attribute bugs across
    report_generator.py's generate_status_report(), covering all 4 personality
    modes since each mode section reads a different combination of the buggy
    fields."""
    from modules.reporting.report_generator import ReportGenerator

    tenant_id = await _register_tenant(client, "Report Enum Test Corp")
    pipeline, run = await _make_active_pipeline_with_failed_run(tenant_id)
    rg = ReportGenerator(tenant_id)

    for mode in ["engineer", "founder", "analyst", "auditor"]:
        report = await rg.generate_status_report(mode)
        assert "error" not in report, f"generate_status_report({mode}) failed: {report}"
        assert report["summary"]["active_pipelines"] == 1
        assert report["summary"]["total_runs_7d"] == 1
