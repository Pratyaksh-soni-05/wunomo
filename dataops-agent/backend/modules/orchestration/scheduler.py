import structlog
from datetime import datetime, timezone
from sqlalchemy import select
from database import AsyncSessionLocal
from models.all_models import Pipeline, PipelineStatus
from services.celery_app import celery_app

log = structlog.get_logger()

# Celery beat schedule entry name prefix
SCHEDULE_PREFIX = "axiom-pipeline-"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Scheduler:
    """
    Manages dynamic Celery-beat schedules for AXIOM pipelines.

    Uses Celery's beat scheduler (redis_scheduler or django_celery_beat depending on config).
    For portability, we use the in-memory/redis beat store pattern:
    schedules are written to the celery beat_schedule config at runtime.

    Each active pipeline with a schedule_cron gets a periodic task entry:
        axiom-pipeline-{pipeline_id} → execute_pipeline_run.apply_async

    Methods:
        register(pipeline_id):       add/update schedule for one pipeline
        unregister(pipeline_id):     remove schedule for one pipeline
        sync_all(tenant_id):         reconcile DB active pipelines → beat schedule
        list_scheduled():            return all currently scheduled pipeline IDs
    """

    # ------------------------------------------------------------------
    # 1. Register a single pipeline schedule
    # ------------------------------------------------------------------

    async def register(self, pipeline_id: str, tenant_id: str) -> dict:
        """
        Reads the pipeline's schedule_cron from DB and registers it in
        Celery beat's runtime schedule dict.

        If the pipeline has no schedule_cron or is not active, it is skipped.

        Returns:
            { "pipeline_id": ..., "cron": ..., "registered": True/False, "reason": ... }
        """
        log.info("scheduler.register", pipeline_id=pipeline_id, tenant_id=tenant_id)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Pipeline).where(
                        Pipeline.id == pipeline_id,
                        Pipeline.tenant_id == tenant_id,
                    )
                )
                pipeline = result.scalar_one_or_none()

            if pipeline is None:
                return {"error": f"Pipeline {pipeline_id} not found"}

            if pipeline.status != PipelineStatus.active:
                return {
                    "pipeline_id": pipeline_id,
                    "registered": False,
                    "reason": f"Pipeline is {pipeline.status.value}, not active",
                }

            if not pipeline.schedule_cron:
                return {
                    "pipeline_id": pipeline_id,
                    "registered": False,
                    "reason": "No schedule_cron defined for this pipeline",
                }

            cron = pipeline.schedule_cron.strip()
            entry_name = f"{SCHEDULE_PREFIX}{pipeline_id}"

            # Parse cron string into Celery crontab
            crontab = _parse_cron(cron)
            if "error" in crontab:
                return {
                    "pipeline_id": pipeline_id,
                    "registered": False,
                    "reason": crontab["error"],
                }

            from celery.schedules import crontab as CeleryTab

            celery_app.conf.beat_schedule[entry_name] = {
                "task": "services.tasks.execute_pipeline_run",
                "schedule": CeleryTab(**crontab),
                "args": [pipeline_id, tenant_id],
                "options": {"queue": "default"},
            }

            log.info(
                "scheduler.register.done",
                entry_name=entry_name,
                cron=cron,
            )
            return {
                "pipeline_id": pipeline_id,
                "entry_name": entry_name,
                "cron": cron,
                "registered": True,
            }

        except Exception as exc:
            log.error("scheduler.register.error", pipeline_id=pipeline_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. Unregister a pipeline schedule
    # ------------------------------------------------------------------

    def unregister(self, pipeline_id: str) -> dict:
        """
        Removes a pipeline's periodic task from Celery beat's schedule.
        Safe to call even if the pipeline was never scheduled.

        Returns:
            { "pipeline_id": ..., "removed": True/False }
        """
        log.info("scheduler.unregister", pipeline_id=pipeline_id)
        entry_name = f"{SCHEDULE_PREFIX}{pipeline_id}"
        if entry_name in celery_app.conf.beat_schedule:
            del celery_app.conf.beat_schedule[entry_name]
            log.info("scheduler.unregister.done", entry_name=entry_name)
            return {"pipeline_id": pipeline_id, "entry_name": entry_name, "removed": True}
        return {
            "pipeline_id": pipeline_id,
            "entry_name": entry_name,
            "removed": False,
            "reason": "Entry not found in beat schedule",
        }

    # ------------------------------------------------------------------
    # 3. Sync all active pipelines for a tenant
    # ------------------------------------------------------------------

    async def sync_all(self, tenant_id: str) -> dict:
        """
        Reconciles the Celery beat schedule with all active pipelines in DB.
        - Adds/updates entries for active pipelines with a schedule_cron
        - Removes stale entries for pipelines that are no longer active

        Designed to be called:
          - On Celery worker startup
          - After a pipeline is paused/activated/schedule-changed

        Returns:
            { "registered": [...], "skipped": [...], "removed": [...], "errors": [...] }
        """
        log.info("scheduler.sync_all.start", tenant_id=tenant_id)

        registered = []
        skipped = []
        removed = []
        errors = []

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Pipeline).where(Pipeline.tenant_id == tenant_id)
                )
                all_pipelines = result.scalars().all()

            active_with_cron = {
                str(p.id): p
                for p in all_pipelines
                if p.status == PipelineStatus.active and p.schedule_cron
            }

            # Register/update active scheduled pipelines
            for pid, pipeline in active_with_cron.items():
                result = await self.register(pid, tenant_id)
                if "error" in result:
                    errors.append({"pipeline_id": pid, "error": result["error"]})
                elif result.get("registered"):
                    registered.append(pid)
                else:
                    skipped.append({"pipeline_id": pid, "reason": result.get("reason")})

            # Remove stale entries: beat entries for this tenant's pipelines that are no longer active
            all_pipeline_ids = {str(p.id) for p in all_pipelines}
            for entry_name in list(celery_app.conf.beat_schedule.keys()):
                if not entry_name.startswith(SCHEDULE_PREFIX):
                    continue
                pid = entry_name[len(SCHEDULE_PREFIX):]
                # Only manage entries for pipelines that belong to this tenant
                if pid in all_pipeline_ids and pid not in active_with_cron:
                    del celery_app.conf.beat_schedule[entry_name]
                    removed.append(pid)
                    log.info("scheduler.sync_all.removed_stale", entry_name=entry_name)

            summary = {
                "tenant_id": tenant_id,
                "synced_at": utcnow().isoformat(),
                "registered": registered,
                "skipped": skipped,
                "removed": removed,
                "errors": errors,
                "total_active_scheduled": len(registered),
            }

            log.info(
                "scheduler.sync_all.done",
                tenant_id=tenant_id,
                registered=len(registered),
                removed=len(removed),
            )
            return summary

        except Exception as exc:
            log.error("scheduler.sync_all.error", tenant_id=tenant_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 4. List all currently scheduled pipeline IDs
    # ------------------------------------------------------------------

    def list_scheduled(self) -> dict:
        """
        Returns all pipeline IDs currently registered in Celery beat's schedule.

        Returns:
            { "scheduled_pipelines": [ { pipeline_id, entry_name, cron } ] }
        """
        entries = []
        for name, entry in celery_app.conf.beat_schedule.items():
            if name.startswith(SCHEDULE_PREFIX):
                pid = name[len(SCHEDULE_PREFIX):]
                sched = entry.get("schedule")
                entries.append({
                    "pipeline_id": pid,
                    "entry_name": name,
                    "schedule": str(sched),
                    "task": entry.get("task"),
                })
        return {
            "scheduled_pipelines": entries,
            "count": len(entries),
        }


# ------------------------------------------------------------------
# Cron parser helper
# ------------------------------------------------------------------

def _parse_cron(cron_str: str) -> dict:
    """
    Parses a standard 5-field cron string into a dict suitable for
    celery.schedules.crontab(**result).

    Supports: * / , - syntax.
    Fields: minute hour day_of_month month_of_year day_of_week

    Returns dict or {"error": "..."}
    """
    parts = cron_str.strip().split()
    if len(parts) != 5:
        return {
            "error": (
                f"Invalid cron expression '{cron_str}'. "
                "Expected 5 fields: minute hour day_of_month month_of_year day_of_week"
            )
        }
    minute, hour, dom, month, dow = parts
    return {
        "minute": minute,
        "hour": hour,
        "day_of_month": dom,
        "month_of_year": month,
        "day_of_week": dow,
    }