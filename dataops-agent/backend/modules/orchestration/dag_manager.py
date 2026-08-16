import uuid
from datetime import datetime, timezone
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
import structlog

from database import AsyncSessionLocal
from models.all_models import (
    Pipeline, PipelineRun, PipelineStatus, RunStatus,
    QualityRule, Incident, IncidentSeverity, IncidentStatus,
    DataSource,
)

log = structlog.get_logger()

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


def _run_summary(run) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id, "status": run.status,
        "triggered_by": run.triggered_by,
        "created_at": str(run.created_at),
        "completed_at": str(run.completed_at) if run.completed_at else None,
    }


def _next_run_at(pipeline) -> str | None:
    """Computed, not stored - purely derived from schedule_cron each time
    this list is read, so it's always accurate even if the cron or status
    just changed. None for unscheduled or non-active pipelines, since
    services.tasks.check_scheduled_pipelines() only ever fires ACTIVE
    pipelines with a schedule_cron - showing a next-run time for anything
    else would be showing a time that will never actually fire."""
    if not pipeline.schedule_cron or pipeline.status != PipelineStatus.ACTIVE:
        return None
    try:
        from croniter import croniter
        it = croniter(pipeline.schedule_cron.strip(), utcnow())
        return it.get_next(datetime).isoformat()
    except (ValueError, KeyError):
        return None


class DAGManager:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ── CREATE ────────────────────────────────────────────────────────────────
    async def create_pipeline(
        self, name: str, source_id: str = None,
        description: str = None, schedule_cron: str = None,
        pipeline_config: dict = None, sla_minutes: int = None,
        retry_policy: dict = None, tags: list = None
    ) -> dict:
        async with AsyncSessionLocal() as db:
            pipeline = Pipeline(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                source_id=source_id,
                name=name,
                description=description,
                status=PipelineStatus.DRAFT,
                schedule_cron=schedule_cron,
                pipeline_config=pipeline_config or {},
                sla_minutes=sla_minutes,
                retry_policy=retry_policy or {"max_retries": 3, "backoff_seconds": 60},
                tags=tags or [],
                version=1,
                created_at=utcnow(),
                updated_at=utcnow()
            )
            db.add(pipeline)
            await db.commit()
            await db.refresh(pipeline)
            log.info("pipeline_created", pipeline_id=pipeline.id, name=name)

            try:
                from modules.governance.lineage_tracker import LineageTracker
                tracker = LineageTracker(self.tenant_id)
                source_name = None
                if source_id:
                    src_result = await db.execute(select(DataSource).where(DataSource.id == source_id))
                    source = src_result.scalars().first()
                    source_name = source.name if source else None
                if source_name:
                    await tracker.auto_register_pipeline_lineage(pipeline.id, pipeline.name, source_name)
                else:
                    await tracker.add_node("pipeline", pipeline.name, {"pipeline_id": pipeline.id, "auto": True})
            except Exception as exc:
                log.warning("pipeline_lineage_registration_failed", pipeline_id=pipeline.id, error=str(exc))

            return {
                "id": pipeline.id, "name": pipeline.name,
                "status": pipeline.status, "source_id": pipeline.source_id,
                "schedule_cron": pipeline.schedule_cron,
                "created_at": pipeline.created_at.isoformat()
            }

    # ── LIST ──────────────────────────────────────────────────────────────────
    async def list_pipelines(self) -> dict:
        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(Pipeline)
                .where(Pipeline.tenant_id == self.tenant_id)
                .order_by(desc(Pipeline.created_at))
            )
            pipelines = r.scalars().all()

            # Most recent run per pipeline, one query for the whole tenant
            # rather than N+1 - runs are ordered newest-first, so the first
            # occurrence of each pipeline_id in this list is its latest run.
            pipeline_ids = [p.id for p in pipelines]
            last_run_by_pipeline = {}
            if pipeline_ids:
                rr = await db.execute(
                    select(PipelineRun)
                    .where(PipelineRun.pipeline_id.in_(pipeline_ids))
                    .order_by(desc(PipelineRun.created_at))
                )
                for run in rr.scalars().all():
                    if run.pipeline_id not in last_run_by_pipeline:
                        last_run_by_pipeline[run.pipeline_id] = run

            return {
                "pipelines": [
                    {
                        "id": p.id, "name": p.name,
                        "status": p.status, "source_id": p.source_id,
                        "schedule_cron": p.schedule_cron,
                        "tags": p.tags or [], "version": p.version,
                        "sla_minutes": p.sla_minutes,
                        "created_at": str(p.created_at),
                        "updated_at": str(p.updated_at),
                        "last_run": _run_summary(last_run_by_pipeline.get(p.id)),
                        "next_run_at": _next_run_at(p),
                    }
                    for p in pipelines
                ],
                "count": len(pipelines)
            }

    # ── GET ───────────────────────────────────────────────────────────────────
    async def get_pipeline(self, pipeline_id: str) -> dict:
        async with AsyncSessionLocal() as db:
            p = await self._fetch(db, pipeline_id)
            if not p:
                return {"error": "Pipeline not found"}
            return {
                "id": p.id, "name": p.name, "description": p.description,
                "status": p.status, "source_id": p.source_id,
                "schedule_cron": p.schedule_cron,
                "pipeline_config": p.pipeline_config,
                "sla_minutes": p.sla_minutes,
                "retry_policy": p.retry_policy,
                "tags": p.tags or [], "version": p.version,
                "created_at": str(p.created_at),
                "updated_at": str(p.updated_at)
            }

    # ── LIST ──────────────────────────────────────────────────────────────────
    async def list_pipelines(self) -> dict:
        """Tenant-scoped pipeline listing - the discovery step that was
        missing for the AXIOM task-planner's DIAGNOSE_PIPELINE_FAILURE and
        INVESTIGATE_INCIDENT shapes: neither had any way to turn a
        human-named pipeline into the real ID get_pipeline_run_history
        requires, matching list_data_sources's existing role for sources
        (see docs/context/SESSION_LOG.md's 2026-08 argument-resolution
        writeup)."""
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Pipeline).where(Pipeline.tenant_id == self.tenant_id))
            pipelines = r.scalars().all()
            return {
                "pipelines": [
                    {
                        "id": p.id, "name": p.name, "status": p.status,
                        "source_id": p.source_id, "schedule_cron": p.schedule_cron,
                        "created_at": str(p.created_at),
                    }
                    for p in pipelines
                ],
                "count": len(pipelines),
            }

    # ── UPDATE ────────────────────────────────────────────────────────────────
    async def update_pipeline(self, pipeline_id: str, **kwargs) -> dict:
        async with AsyncSessionLocal() as db:
            p = await self._fetch(db, pipeline_id)
            if not p:
                return {"error": "Pipeline not found"}
            allowed = {"name", "description", "schedule_cron", "pipeline_config",
                       "sla_minutes", "retry_policy", "tags", "status"}
            for k, v in kwargs.items():
                if k in allowed and v is not None:
                    setattr(p, k, v)
            p.updated_at = utcnow()
            await db.commit()
            return {"message": "Pipeline updated", "id": pipeline_id}

    # ── STATUS TRANSITIONS ────────────────────────────────────────────────────
    async def activate_pipeline(self, pipeline_id: str) -> dict:
        return await self.update_pipeline(pipeline_id, status=PipelineStatus.ACTIVE)

    async def pause_pipeline(self, pipeline_id: str) -> dict:
        result = await self.update_pipeline(pipeline_id, status=PipelineStatus.PAUSED)
        log.info("pipeline_paused", pipeline_id=pipeline_id)
        return result

    async def set_schedule(self, pipeline_id: str, cron: str) -> dict:
        result = await self.update_pipeline(
            pipeline_id, schedule_cron=cron, status=PipelineStatus.ACTIVE
        )
        return {"message": "Schedule updated", "cron": cron, **result}

    # ── RUN ───────────────────────────────────────────────────────────────────
    async def trigger_run(
        self, pipeline_id: str, triggered_by: str = "manual"
    ) -> dict:
        async with AsyncSessionLocal() as db:
            p = await self._fetch(db, pipeline_id)
            if not p:
                return {"error": "Pipeline not found"}
            if p.status == PipelineStatus.PAUSED:
                return {"error": "Pipeline is paused. Activate it before running."}

            run = PipelineRun(
                id=str(uuid.uuid4()),
                pipeline_id=pipeline_id,
                tenant_id=self.tenant_id,
                status=RunStatus.PENDING,
                triggered_by=triggered_by,
                run_logs=[],
                output_summary={},
                created_at=utcnow()
            )
            db.add(run)

            # Mark pipeline active if it was draft
            if p.status == PipelineStatus.DRAFT:
                p.status = PipelineStatus.ACTIVE
                p.updated_at = utcnow()

            await db.commit()
            await db.refresh(run)
            log.info("pipeline_run_triggered",
                     run_id=run.id, pipeline_id=pipeline_id, by=triggered_by)

            # Dispatch to Celery
            try:
                from services.tasks import execute_pipeline_run
                execute_pipeline_run.delay(run.id, pipeline_id, self.tenant_id)
                dispatch = "queued"
            except Exception as e:
                log.warning("celery_dispatch_failed", error=str(e))
                dispatch = "celery_unavailable_run_created"

            return {
                "run_id": run.id, "pipeline_id": pipeline_id,
                "status": RunStatus.PENDING, "triggered_by": triggered_by,
                "dispatch": dispatch, "created_at": run.created_at.isoformat()
            }

    # ── RUN HISTORY ───────────────────────────────────────────────────────────
    async def get_run_history(
        self, pipeline_id: str, limit: int = 20
    ) -> dict:
        async with AsyncSessionLocal() as db:
            p = await self._fetch(db, pipeline_id)
            if not p:
                return {"error": "Pipeline not found"}
            r = await db.execute(
                select(PipelineRun)
                .where(PipelineRun.pipeline_id == pipeline_id)
                .order_by(desc(PipelineRun.created_at))
                .limit(limit)
            )
            runs = r.scalars().all()
            return {
                "pipeline_id": pipeline_id,
                "pipeline_name": p.name,
                "runs": [
                    {
                        "id": run.id,
                        "status": run.status,
                        "triggered_by": run.triggered_by,
                        "started_at": str(run.started_at) if run.started_at else None,
                        "completed_at": str(run.completed_at) if run.completed_at else None,
                        "duration_seconds": run.duration_seconds,
                        "rows_processed": run.rows_processed,
                        "rows_failed": run.rows_failed,
                        "quality_score": run.quality_score,
                        "error_message": run.error_message,
                        "output_summary": run.output_summary
                    }
                    for run in runs
                ],
                "count": len(runs)
            }

    # ── BACKFILL ──────────────────────────────────────────────────────────────
    async def backfill(
        self, pipeline_id: str, start_date: str, end_date: str
    ) -> dict:
        async with AsyncSessionLocal() as db:
            p = await self._fetch(db, pipeline_id)
            if not p:
                return {"error": "Pipeline not found"}
            run = PipelineRun(
                id=str(uuid.uuid4()),
                pipeline_id=pipeline_id,
                tenant_id=self.tenant_id,
                status=RunStatus.PENDING,
                triggered_by="backfill",
                run_logs=[{"event": "backfill_requested",
                           "start_date": start_date,
                           "end_date": end_date,
                           "ts": utcnow().isoformat()}],
                output_summary={"backfill": True,
                                "start_date": start_date,
                                "end_date": end_date},
                created_at=utcnow()
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            log.info("backfill_triggered", run_id=run.id,
                     pipeline_id=pipeline_id,
                     start=start_date, end=end_date)
            return {
                "run_id": run.id, "pipeline_id": pipeline_id,
                "type": "backfill", "start_date": start_date,
                "end_date": end_date, "status": RunStatus.PENDING
            }

    # ── RUN TRACKER (used by Celery task) ─────────────────────────────────────
    async def update_run_status(
        self, run_id: str, status: RunStatus,
        rows_processed: int = None, rows_failed: int = None,
        quality_score: float = None, error_message: str = None,
        output_summary: dict = None, log_entry: dict = None
    ) -> dict:
        async with AsyncSessionLocal() as db:
            run = await db.get(PipelineRun, run_id)
            if not run:
                return {"error": "Run not found"}
            run.status = status
            if status == RunStatus.RUNNING and not run.started_at:
                run.started_at = utcnow()
            if status in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED):
                run.completed_at = utcnow()
                if run.started_at:
                    delta = (run.completed_at - run.started_at).total_seconds()
                    run.duration_seconds = round(delta, 2)
            if rows_processed is not None: run.rows_processed = rows_processed
            if rows_failed is not None:    run.rows_failed = rows_failed
            if quality_score is not None:  run.quality_score = quality_score
            if error_message is not None:  run.error_message = error_message
            if output_summary is not None: run.output_summary = output_summary
            if log_entry:
                logs = list(run.run_logs or [])
                logs.append({**log_entry, "ts": utcnow().isoformat()})
                run.run_logs = logs
            await db.commit()
            return {"run_id": run_id, "status": status}

    # ── HELPER ────────────────────────────────────────────────────────────────
    async def _fetch(self, db, pipeline_id: str) -> Pipeline | None:
        r = await db.execute(select(Pipeline).where(
            Pipeline.id == pipeline_id,
            Pipeline.tenant_id == self.tenant_id
        ))
        return r.scalars().first()