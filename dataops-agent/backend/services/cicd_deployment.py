import structlog
from celery import shared_task
from datetime import datetime, timezone
from sqlalchemy import select, update

from database import AsyncSessionLocal
from models.cicd import PipelineCommit, PipelineDeployment, DeploymentStatus

log = structlog.get_logger()


@shared_task(bind=True, name="cicd.deploy_pipeline", max_retries=2)
def deploy_pipeline(self, commit_id: str, tenant_id: str, approved_by: str = "auto"):
    import asyncio
    try:
        asyncio.run(_deploy(commit_id, tenant_id, approved_by))
    except Exception as exc:
        log.error("cicd.deploy_task_failed", commit_id=commit_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)


async def _deploy(commit_id: str, tenant_id: str, approved_by: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PipelineCommit).where(PipelineCommit.id == commit_id)
        )
        commit = result.scalar_one_or_none()
        if not commit:
            log.error("cicd.deploy_commit_not_found", commit_id=commit_id)
            return
        if not commit.pipeline_id:
            log.info("cicd.deploy_skipped", reason="no pipeline_id on commit", commit_id=commit_id)
            return

        tid = str(tenant_id)

        # Get current active deployment SHA for rollback reference
        rollback_sha = None
        try:
            result2 = await db.execute(
                select(PipelineDeployment)
                .where(
                    PipelineDeployment.pipeline_id == commit.pipeline_id,
                    PipelineDeployment.status == DeploymentStatus.active,
                )
                .order_by(PipelineDeployment.deployed_at.desc())
                .limit(1)
            )
            prev = result2.scalar_one_or_none()
            if prev:
                rollback_sha = prev.commit_sha
        except Exception:
            pass

        approval_type = "auto" if approved_by == "auto" else "manual"
        deployment = PipelineDeployment(
            tenant_id=tid,
            pipeline_id=commit.pipeline_id,
            commit_id=commit.id,
            commit_sha=commit.commit_sha,
            approved_by=approved_by,
            approval_type=approval_type,
            risk_score=commit.risk_score,
            rollback_commit_sha=rollback_sha,
            status=DeploymentStatus.deploying,
            monitoring_active=True,
        )
        db.add(deployment)
        await db.flush()

        log.info("cicd.deployment_started", deployment_id=str(deployment.id), sha=commit.commit_sha[:8])

        success = await activate_pipeline(db, commit, tid)

        if success:
            deployment.status = DeploymentStatus.active
            deployment.deployed_at = datetime.now(timezone.utc)

            # Supersede any previously active deployment
            await db.execute(
                update(PipelineDeployment)
                .where(
                    PipelineDeployment.pipeline_id == commit.pipeline_id,
                    PipelineDeployment.id != deployment.id,
                    PipelineDeployment.status == DeploymentStatus.active,
                )
                .values(status=DeploymentStatus.rolled_back)
            )
        else:
            deployment.status = DeploymentStatus.failed

        await db.commit()
        log.info(
            "cicd.deployment_done",
            status=deployment.status,
            deployment_id=str(deployment.id),
        )


async def activate_pipeline(db, commit: PipelineCommit, tenant_id) -> bool:
    try:
        if not commit.pipeline_id:
            log.info("cicd.no_pipeline_to_activate")
            return True

        from models.all_models import Pipeline                  # ✅ correct path

        result = await db.execute(
            select(Pipeline).where(
                Pipeline.id == commit.pipeline_id,
                Pipeline.tenant_id == str(tenant_id),
            )
        )
        pipeline = result.scalar_one_or_none()
        if not pipeline:
            log.warning("cicd.pipeline_not_found_for_deploy", pipeline_id=str(commit.pipeline_id))
            return False

        pipeline.status = "ACTIVE"                              # ✅ only safe update
        await db.flush()
        log.info("cicd.pipeline_activated", pipeline_id=str(pipeline.id))
        return True

    except Exception as e:
        log.error("cicd.activate_failed", error=str(e))
        return False