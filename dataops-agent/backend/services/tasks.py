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
        # notify_pipeline_failure() itself never raises (see
        # NotificationService's own docstring), but this is wrapped
        # defensively anyway -- a notification-code bug must never swallow
        # the `raise` below, which is what drives this task's real Celery
        # retry behavior. Was previously dead code: this is a real, one-shot
        # trigger per failed run (no spam risk, unlike the freshness
        # checker's known duplicate-incident gap -- see CLAUDE.md).
        try:
            from modules.reporting.notification_service import NotificationService
            await NotificationService(tenant_id).notify_pipeline_failure(
                pipeline_name=pipeline.name if pipeline else "unknown",
                run_id=run_id, error_message=str(e),
            )
        except Exception as notify_exc:
            log.warning("pipeline_failure_notification_error", run_id=run_id, error=str(notify_exc))
        raise


async def _create_scheduled_run(pipeline_id: str, tenant_id: str):
    """Pre-creates a PipelineRun row for a scheduled firing - unlike the
    manual/API trigger path (DAGManager.trigger_run(), which pre-creates the
    run inside the request/response cycle before dispatching), a scheduled
    firing has no such window: each firing needs its own fresh run_id, and
    nothing calls this ahead of time. Returns the new run_id, or None if the
    pipeline was deleted/paused/deactivated since this firing was decided
    (skip silently rather than run a pipeline that's no longer supposed to
    be scheduled)."""
    import uuid
    from sqlalchemy import select
    from database import AsyncSessionLocal
    from models.all_models import Pipeline, PipelineRun, PipelineStatus, RunStatus

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Pipeline).where(
            Pipeline.id == pipeline_id, Pipeline.tenant_id == tenant_id,
        ))
        pipeline = r.scalars().first()
        if pipeline is None or pipeline.status != PipelineStatus.ACTIVE:
            return None

        run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline_id,
            tenant_id=tenant_id,
            status=RunStatus.PENDING,
            triggered_by="scheduled",
            run_logs=[],
            output_summary={},
            created_at=utcnow(),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def execute_scheduled_pipeline_run(self, pipeline_id: str, tenant_id: str):
    """Entry point for a single scheduled firing (2 args - no run_id, since
    beat/the caller can't pre-create one). Creates its own PipelineRun row,
    then delegates to the same _execute_run() core execute_pipeline_run()
    uses for manual/API-triggered runs."""
    import asyncio
    from database import engine

    async def _run():
        await engine.dispose()
        run_id = await _create_scheduled_run(pipeline_id, tenant_id)
        if run_id is None:
            log.info("scheduled_run_skipped", pipeline_id=pipeline_id, reason="not found or not active")
            return
        await _execute_run(run_id, pipeline_id, tenant_id)

    try:
        asyncio.run(_run())
    except Exception as exc:
        log.error("scheduled_pipeline_run_failed", pipeline_id=pipeline_id, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def check_scheduled_pipelines(self):
    """The real, live scheduling mechanism (static beat entry, every 60s -
    see services/celery_app.py). Polls every active pipeline with a
    schedule_cron directly from the DB and fires any whose cron matches the
    current UTC minute, via the same execute_scheduled_pipeline_run() path.
    Deliberately NOT the dynamic per-pipeline beat_schedule injection design
    in modules/orchestration/scheduler.py (Scheduler.register()/sync_all())
    - that design mutates celery_app.conf.beat_schedule in whichever process
    calls it, which never reaches the actual separate celery_beat process's
    own in-memory schedule. This polling design sidesteps that entirely: one
    static entry, always running in the same process as everything else on
    the beat schedule, reading real DB state on every tick - the exact same
    proven pattern as check_all_freshness() (also a static, always-on entry
    that iterates all tenants directly, no per-tenant dynamic registration).
    """
    import asyncio
    from database import engine

    async def _run():
        await engine.dispose()
        await _check_scheduled_pipelines()

    try:
        asyncio.run(_run())
    except Exception as exc:
        log.error("scheduled_pipeline_check_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _check_scheduled_pipelines():
    from sqlalchemy import select
    from database import AsyncSessionLocal
    from models.all_models import Pipeline, PipelineStatus
    from croniter import croniter

    now = utcnow().replace(second=0, microsecond=0)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Pipeline).where(
            Pipeline.status == PipelineStatus.ACTIVE,
            Pipeline.schedule_cron.isnot(None),
        ))
        pipelines = r.scalars().all()

    fired = 0
    for p in pipelines:
        cron = (p.schedule_cron or "").strip()
        if not cron:
            continue
        try:
            is_due = croniter.match(cron, now)
        except (ValueError, KeyError):
            log.warning("scheduled_pipeline_invalid_cron", pipeline_id=p.id, cron=cron)
            continue
        if not is_due:
            continue
        execute_scheduled_pipeline_run.delay(p.id, p.tenant_id)
        fired += 1
        log.info("scheduled_pipeline_fired", pipeline_id=p.id, tenant_id=p.tenant_id, cron=cron)

    log.info("scheduled_pipeline_check_complete", checked=len(pipelines), fired=fired)


# Found live while building this: this dev DB alone has 788 RUNNING +
# 353 QUEUED + 102 PAUSED_QUOTA_EXCEEDED tasks (WALKTHROUGH_FINDINGS_
# 2026-08.md item 74) -- doing each one's real execute_next_step() work
# inline, sequentially, inside the beat tick itself hung past two
# minutes against real data, not a hypothetical. At 4 worker processes
# (docker-compose's celery_worker --concurrency=4) and a conservative
# worst case of ~10s per task (this module's own MAX_ATTEMPTS_PER_STEP=3
# / TRANSIENT_RETRY_BACKOFF_SECONDS=2 already bound one call's internal
# retry sleeps to a few seconds, plus real tool/LLM latency), 25 tasks
# split across 4 workers is ~6-7 per worker -- comfortably inside the
# 60s tick window even at that pessimistic estimate, with real headroom
# for the common case. A backlog beyond 25 simply drains across
# multiple ticks, oldest-first (see the index/order-by below) -- fine,
# per instruction; a queue that never empties would not be.
ADVANCE_BATCH_SIZE = 25


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def advance_active_tasks(self):
    """The auto-advance loop's beat tick (Wunomo Projects Phase 3, item
    71 / slice 10): "give it a task and walk away" has always actually
    meant a human had to keep clicking /advance -- this is the second
    half of that already-shipped feature, not new scope.

    Deliberately does NOT do any task's real advancing work itself --
    only selects up to ADVANCE_BATCH_SIZE runnable task_ids (oldest-
    updated-first) and dispatches one advance_one_task.delay(task_id)
    per id, the same way check_scheduled_pipelines above dispatches
    execute_scheduled_pipeline_run.delay(...) rather than running a
    pipeline inline. This is a correction, not the original design: an
    earlier version of this function called execute_next_step() inline
    in a loop here, and hung for over two minutes against this dev DB's
    own real backlog (item 74) -- the fix is dispatching to the worker
    pool's own concurrency, not doing the work in the scheduler.

    If the same task_id is still sitting on the queue from a previous
    tick when this one dispatches it again (the worker pool falling
    behind ADVANCE_BATCH_SIZE/tick), the duplicate is harmless -- the
    per-task advisory lock (services/task_lock.py, item 73) means
    whichever copy runs second just gets {"outcome": "task_busy"} and
    exits immediately. Accepted as a wasted-cycle cost, not fixed with
    dispatch de-duplication, given ADVANCE_BATCH_SIZE's own headroom."""
    import asyncio
    from database import engine

    async def _run():
        await engine.dispose()
        return await _select_tasks_to_advance()

    try:
        task_ids, total_runnable = asyncio.run(_run())
    except Exception as exc:
        log.error("advance_active_tasks_failed", error=str(exc))
        raise self.retry(exc=exc)

    for task_id in task_ids:
        advance_one_task.delay(task_id)
    # Backlog visibility (added after the fact, per instruction): a
    # 25/tick cap against a real backlog otherwise has no way to show
    # whether it's draining or growing between observations -- comparing
    # total_runnable across consecutive tick logs is what answers that.
    # Also exposed on demand via GET /health/tasks (main.py), which uses
    # the identical RUNNABLE_TASK_STATUSES this query does.
    log.info(
        "advance_active_tasks_dispatched",
        dispatched=len(task_ids), total_runnable=total_runnable, batch_size=ADVANCE_BATCH_SIZE,
    )


async def _select_tasks_to_advance() -> tuple[list[str], int]:
    """Returns (task_ids to dispatch this tick, total runnable count).
    Selects up to ADVANCE_BATCH_SIZE runnable task_ids, oldest-updated-
    first -- ix_tasks_status_updated_at (status, updated_at) keeps this
    an index scan, not a full scan, as the tasks table keeps growing
    (item 74). The total count is a second, cheap COUNT(*) against the
    same index, purely for backlog visibility (see advance_active_tasks'
    own log line and GET /health/tasks) -- it does no task-advancing
    work itself; the actual execute_next_step() call happens in
    advance_one_task below, on whichever worker eventually dequeues it."""
    from sqlalchemy import func, select
    from database import AsyncSessionLocal
    from models.all_models import RUNNABLE_TASK_STATUSES, Task

    async with AsyncSessionLocal() as db:
        total_runnable = await db.scalar(
            select(func.count()).select_from(Task).where(Task.status.in_(RUNNABLE_TASK_STATUSES))
        )
        r = await db.execute(
            select(Task.id)
            .where(Task.status.in_(RUNNABLE_TASK_STATUSES))
            .order_by(Task.updated_at.asc())
            .limit(ADVANCE_BATCH_SIZE)
        )
        return [row[0] for row in r.all()], total_runnable


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def advance_one_task(self, task_id: str):
    """The real per-task work, dispatched by advance_active_tasks above
    -- never called inline in the beat/scheduling process. Spreads the
    actual execute_next_step() work (tool calls, possible LLM-adapt
    calls) across the worker pool's own concurrency instead of
    serializing every runnable task inside one beat tick.

    not_runnable and task_busy are expected, silent outcomes -- a
    tenant with 20 tasks paused for approval would otherwise produce 20
    log lines a minute, forever, for nothing having happened. Every
    other outcome (a real step succeeding, failing, completing the
    task, pausing for quota/a source lock/approval) is logged, matching
    check_scheduled_pipelines' own aggregate-logging convention."""
    import asyncio
    from database import engine
    from modules.orchestration.task_executor import execute_next_step

    async def _run():
        await engine.dispose()
        return await execute_next_step(task_id)

    try:
        outcome = asyncio.run(_run())
    except Exception as exc:
        log.error("advance_one_task_failed", task_id=task_id, error=str(exc))
        raise self.retry(exc=exc)

    if outcome.get("outcome") not in ("not_runnable", "task_busy"):
        log.info("advance_one_task_outcome", task_id=task_id, outcome=outcome.get("outcome"))

    log.info("advance_active_tasks_complete", checked=len(task_ids), advanced=advanced)


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
    from models.all_models import Tenant, DataSource, Incident, IncidentSeverity, IncidentStatus
    import uuid

    async with AsyncSessionLocal() as db:
        tenants = await db.execute(select(Tenant).where(Tenant.is_active == True))
        for tenant in tenants.scalars().all():
            # Existing open staleness incidents for this tenant, keyed by the
            # source they're about - item 53 fix. Previously this set only
            # gated the notification below; Incident creation itself was
            # unconditional, so every 15-minute tick a source stayed stale
            # added another near-duplicate row. Now a source with an
            # already-open "Stale data:" incident gets that incident
            # refreshed in place (title/description/severity re-derived from
            # the current hours_since) instead of a brand-new row.
            existing_by_source_id: dict[str, Incident] = {}
            existing_open = await db.execute(
                select(Incident).where(
                    Incident.tenant_id == tenant.id,
                    Incident.status == IncidentStatus.OPEN,
                    Incident.title.like("Stale data:%"),
                )
            )
            for existing in existing_open.scalars().all():
                for asset_id in (existing.affected_assets or []):
                    existing_by_source_id[asset_id] = existing

            newly_stale = []
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
                    severity = (IncidentSeverity.HIGH if hours_since > sla_hours * 2
                                else IncidentSeverity.MEDIUM)
                    existing = existing_by_source_id.get(src.id)
                    if existing is not None:
                        existing.title = f"Stale data: {src.name} ({round(hours_since,1)}h overdue)"
                        existing.description = f"Source '{src.name}' has not been synced in {round(hours_since,1)} hours. SLA: {sla_hours}h."
                        existing.severity = severity
                        db.add(existing)
                    else:
                        incident = Incident(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant.id,
                            title=f"Stale data: {src.name} ({round(hours_since,1)}h overdue)",
                            description=f"Source '{src.name}' has not been synced in {round(hours_since,1)} hours. SLA: {sla_hours}h.",
                            severity=severity,
                            affected_assets=[src.id],
                            detected_at=utcnow()
                        )
                        db.add(incident)
                        newly_stale.append({
                            "source_id": src.id, "source_name": src.name,
                            "hours_overdue": round(hours_since, 1),
                        })

            if newly_stale:
                try:
                    from modules.reporting.notification_service import NotificationService
                    await NotificationService(tenant.id).notify_stale_sources(newly_stale)
                except Exception as notify_exc:
                    log.warning("stale_source_notification_error", tenant_id=tenant.id, error=str(notify_exc))
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