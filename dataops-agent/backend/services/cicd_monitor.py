# backend/services/cicd_monitor.py

import asyncio
import structlog
from celery import shared_task
from datetime import datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from config import settings
from models.cicd import PipelineDeployment, DeploymentStatus, CICDIncident

log = structlog.get_logger()

MONITORING_RUN_WINDOW = 3
MAX_ALLOWED_FAILURES  = 2


@shared_task(name="cicd.check_post_deploy_health")
def check_post_deploy_health():
    """Celery Beat task — runs every 60s to monitor post-deploy health."""
    # Bug fix: this used to hand-roll asyncio.new_event_loop()/set_event_loop()/
    # loop.close() without ever clearing the process-global "current loop"
    # afterward. Celery's prefork pool reuses this same worker process for many
    # tasks, so the dangling closed-loop reference corrupted whichever task ran
    # next on this worker (surfacing as unrelated-looking crashes like
    # "No module named 'modules'"). asyncio.run() tears down cleanly instead.
    asyncio.run(_check_all_monitored())


async def _check_all_monitored():
    # Fresh engine per invocation (this runs in a long-lived Celery worker
    # process, invoked repeatedly by Beat) — must dispose it when done so we
    # don't leak a new connection pool every 60 seconds.
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            result = await db.execute(
                select(PipelineDeployment).where(
                    PipelineDeployment.monitoring_active == True,
                    PipelineDeployment.status == DeploymentStatus.active,
                )
            )
            monitored = result.scalars().all()
            log.info("cicd.post_deploy_check", count=len(monitored))
            for deployment in monitored:
                await _check_one(db, deployment)
    finally:
        await engine.dispose()


async def _check_one(db, deployment: PipelineDeployment):
    try:
        run_count     = deployment.post_deploy_run_count
        failure_count = deployment.post_deploy_failure_count

        log.info(
            "cicd.checking_deployment",
            deployment_id=str(deployment.id),
            runs=run_count,
            failures=failure_count,
        )

        if run_count >= MONITORING_RUN_WINDOW:
            if failure_count >= MAX_ALLOWED_FAILURES:
                log.warning(
                    "cicd.rollback_triggered",
                    deployment_id=str(deployment.id),
                    failures=failure_count,
                    runs=run_count,
                )
                await _trigger_rollback(db, deployment)
            else:
                deployment.monitoring_active = False
                log.info("cicd.deployment_healthy", deployment_id=str(deployment.id))

                # ── Notify deployment is healthy ──────────────────────────────
                await _safe_notify("deployment_complete", {
                    "sha": deployment.commit_sha,
                    "deployment_id": str(deployment.id),
                })

            await db.commit()

    except Exception as e:
        log.error("cicd.health_check_error", error=str(e), deployment_id=str(deployment.id))


async def _trigger_rollback(db, deployment: PipelineDeployment):
    if not deployment.rollback_commit_sha:
        log.warning("cicd.no_rollback_sha", deployment_id=str(deployment.id))
        deployment.monitoring_active = False
        return

    try:
        # ✅ Update pipeline status via raw SQL — avoids pipeline.metadata
        #    column name conflicting with SQLAlchemy's internal MetaData object
        await db.execute(
            text("""
                UPDATE pipelines
                SET status = 'ACTIVE',
                    updated_at = NOW()
                WHERE id = :pipeline_id
                AND tenant_id = :tenant_id
            """),
            {
                "pipeline_id": deployment.pipeline_id,
                "tenant_id": deployment.tenant_id,
            }
        )
        await db.flush()

        deployment.status           = DeploymentStatus.rolled_back
        deployment.monitoring_active = False
        deployment.rolled_back_at   = datetime.now(timezone.utc)

        await _create_incident(db, deployment)

        # ── Notify rollback triggered ─────────────────────────────────────────
        await _safe_notify("rollback_triggered", {
            "deployment_id": str(deployment.id),
            "sha": deployment.commit_sha,
            "failures": deployment.post_deploy_failure_count,
            "runs": deployment.post_deploy_run_count,
        })

        log.info("cicd.rollback_complete", deployment_id=str(deployment.id))

    except Exception as e:
        log.error("cicd.rollback_error", error=str(e))


async def _create_incident(db, deployment: PipelineDeployment):
    try:
        incident = CICDIncident(
            tenant_id=deployment.tenant_id,
            pipeline_id=deployment.pipeline_id,
            deployment_id=deployment.id,
            severity="HIGH",
            status="OPEN",
            title=f"Auto-rollback triggered for commit {deployment.commit_sha[:8]}",
            description=(
                f"Pipeline failed {deployment.post_deploy_failure_count} of "
                f"{deployment.post_deploy_run_count} post-deploy runs. "
                f"Auto-rolled back to {deployment.rollback_commit_sha[:8]}. "
                f"Deployment ID: {deployment.id}"
            ),
            root_cause="Post-deploy health check failure",
        )
        db.add(incident)
        await db.flush()
        log.info("cicd.incident_created", incident_id=str(incident.id))
    except Exception as e:
        log.warning("cicd.incident_create_failed", error=str(e))


# ─── Safe Notify Helper ───────────────────────────────────────────────────────

async def _safe_notify(event: str, payload: dict) -> None:
    """
    Fire-and-forget Slack notification.
    Never raises — a broken Slack webhook must never crash the monitor.
    """
    try:
        from services.cicd_notify import notify
        await notify(event, payload)
    except Exception as e:
        log.warning("cicd.notify_skipped", notify_event=event, error=str(e))