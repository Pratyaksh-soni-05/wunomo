from services.celery_app import celery_app   # ✅ correct — Celery boots from /app, services is a package
from datetime import datetime, timezone
import structlog


log = structlog.get_logger()


def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def execute_pipeline_run(self, run_id: str, pipeline_id: str, tenant_id: str):
    """Execute a pipeline run — called by trigger_run()."""
    import asyncio
    from database import engine

    async def _run():
        # Celery calls asyncio.run() fresh per task invocation/retry, but the
        # shared async engine's connection pool is a long-lived singleton —
        # without disposing first, a pooled connection checked out under a
        # previous (now-closed) loop gets reused here and blows up with
        # "attached to a different loop" / "Event loop is closed".
        await engine.dispose()
        await _execute_run(run_id, pipeline_id, tenant_id)

    try:
        asyncio.run(_run())
    except Exception as exc:
        log.error("pipeline_run_failed", run_id=run_id, error=str(exc))
        raise self.retry(exc=exc)


async def _execute_run(run_id: str, pipeline_id: str, tenant_id: str):
    from modules.orchestration.dag_manager import DAGManager
    from models.all_models import RunStatus
    dag = DAGManager(tenant_id)

    await dag.update_run_status(
        run_id, RunStatus.RUNNING,
        log_entry={"event": "run_started", "pipeline_id": pipeline_id}
    )
    try:
        from database import AsyncSessionLocal           # ✅ absolute import
        from sqlalchemy import select
        from models.all_models import Pipeline, DataSource
        from modules.ingestion.connector_manager import ConnectorManager

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
            pipeline = r.scalars().first()
            if not pipeline:
                raise ValueError(f"Pipeline {pipeline_id} not found")

        rows_processed = 0
        quality_score  = 100.0
        output_summary = {}

        if pipeline.source_id:
            sync_result = await ConnectorManager(tenant_id).sync(
                pipeline.source_id, mode="incremental"
            )
            output_summary["sync"] = sync_result
            # ConnectorManager.sync() catches its own exceptions and returns
            # {"error": ..., "status": "failed"} as a normal dict instead of
            # raising — without this check the run was unconditionally
            # marked SUCCESS even when the sync never actually happened
            # (e.g. the uploaded file wasn't visible to this container).
            if sync_result.get("error"):
                raise RuntimeError(f"Source sync failed: {sync_result['error']}")
            rows_processed = sync_result.get("total_rows", 0)
            await dag.update_run_status(
                run_id, RunStatus.RUNNING,
                log_entry={"event": "source_synced", "result": sync_result}
            )

        from modules.quality.rule_engine import QualityRuleEngine
        qe = QualityRuleEngine(tenant_id)
        quality_result = await qe.run_checks(pipeline_id)
        quality_score  = quality_result.get("score", 100.0)
        output_summary["quality"] = quality_result
        await dag.update_run_status(
            run_id, RunStatus.RUNNING,
            log_entry={"event": "quality_checked", "score": quality_score}
        )

        await dag.update_run_status(
            run_id, RunStatus.SUCCESS,
            rows_processed=rows_processed,
            rows_failed=0,
            quality_score=quality_score,
            output_summary=output_summary,
            log_entry={"event": "run_completed"}
        )
        log.info("pipeline_run_success", run_id=run_id, score=quality_score)

    except Exception as e:
        await dag.update_run_status(
            run_id, RunStatus.FAILED,
            error_message=str(e),
            log_entry={"event": "run_failed", "error": str(e)}
        )
        log.error("pipeline_run_error", run_id=run_id, error=str(e))
        raise


@celery_app.task
def check_all_freshness():
    import asyncio
    from database import engine

    async def _run():
        await engine.dispose()
        await _check_freshness()

    asyncio.run(_run())


async def _check_freshness():
    from database import AsyncSessionLocal
    from sqlalchemy import select
    from models.all_models import Tenant, DataSource, Incident, IncidentSeverity
    import uuid

    async with AsyncSessionLocal() as db:
        tenants = await db.execute(select(Tenant).where(Tenant.is_active == True))
        for tenant in tenants.scalars().all():
            sources = await db.execute(
                select(DataSource).where(
                    DataSource.tenant_id == tenant.id,
                    DataSource.is_active == True,
                    DataSource.last_profiled_at != None
                )
            )
            for src in sources.scalars().all():
                hours_since = (utcnow() - src.last_profiled_at).total_seconds() / 3600
                sla_hours   = 24
                if hours_since > sla_hours:
                    incident = Incident(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant.id,
                        title=f"Stale data: {src.name} ({round(hours_since,1)}h overdue)",
                        description=f"Source '{src.name}' has not been synced in {round(hours_since,1)} hours. SLA: {sla_hours}h.",
                        severity=IncidentSeverity.HIGH if hours_since > sla_hours * 2
                                 else IncidentSeverity.MEDIUM,
                        affected_assets=[src.id],
                        detected_at=utcnow()
                    )
                    db.add(incident)
        await db.commit()
    log.info("freshness_check_complete")


@celery_app.task
def run_anomaly_detection():
    import asyncio
    asyncio.run(_anomaly_detection())


async def _anomaly_detection():
    """Placeholder — full implementation in Phase 3."""
    log.info("anomaly_detection_run")


@celery_app.task
def generate_daily_reports():
    import asyncio
    asyncio.run(_daily_reports())


async def _daily_reports():
    """Placeholder — full implementation in Phase 3."""
    log.info("daily_reports_generated")