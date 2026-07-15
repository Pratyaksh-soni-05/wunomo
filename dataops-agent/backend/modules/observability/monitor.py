import structlog
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, desc, and_
from database import AsyncSessionLocal
from models.all_models import (
    DataSource,
    Pipeline,
    PipelineRun,
    QualityRule,
    RunStatus,
    PipelineStatus,
)

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Monitor:
    """
    Observability monitor for AXIOM.
    Handles freshness checks, system health aggregation,
    and per-pipeline performance stats.
    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Freshness Checks
    # ------------------------------------------------------------------

    async def check_freshness(self) -> list[dict]:
        """
        Returns a list of data sources that are stale (overdue for profiling).
        A source is considered stale if:
          - it has never been profiled, OR
          - it has a pipeline with a schedule_cron and its last_profiled_at
            exceeds the expected interval (we approximate: if the pipeline SLA
            in minutes has elapsed since last_profiled_at, it's overdue).
        Falls back to a 24-hour threshold for sources with no pipeline.

        Returns:
            list of dicts with keys:
              source_id, source_name, source_type, last_profiled_at,
              hours_overdue, pipeline_id (or None), expected_interval_hours
        """
        log.info("check_freshness.start", tenant_id=self.tenant_id)
        stale = []

        try:
            async with AsyncSessionLocal() as db:
                # Fetch all active sources for this tenant
                sources_result = await db.execute(
                    select(DataSource).where(
                        DataSource.tenant_id == self.tenant_id,
                        DataSource.is_active == True,
                    )
                )
                sources = sources_result.scalars().all()

                # Fetch all active pipelines for this tenant (keyed by source_id)
                pipelines_result = await db.execute(
                    select(Pipeline).where(
                        Pipeline.tenant_id == self.tenant_id,
                        Pipeline.status == PipelineStatus.ACTIVE,
                    )
                )
                pipelines = pipelines_result.scalars().all()

                # Build a map: source_id → [pipelines]
                pipeline_map: dict[str, list[Pipeline]] = {}
                for p in pipelines:
                    pipeline_map.setdefault(str(p.source_id), []).append(p)

                now = utcnow()
                DEFAULT_INTERVAL_HOURS = 24

                for source in sources:
                    sid = str(source.id)
                    associated_pipelines = pipeline_map.get(sid, [])

                    # Determine expected interval from the most aggressive SLA
                    expected_interval_hours = DEFAULT_INTERVAL_HOURS
                    best_pipeline_id = None

                    for p in associated_pipelines:
                        if p.sla_minutes:
                            interval_h = p.sla_minutes / 60.0
                            if interval_h < expected_interval_hours:
                                expected_interval_hours = interval_h
                                best_pipeline_id = str(p.id)

                    # Determine staleness
                    if source.last_profiled_at is None:
                        hours_overdue = expected_interval_hours  # effectively never profiled
                        stale.append(
                            {
                                "source_id": sid,
                                "source_name": source.name,
                                "source_type": source.source_type.value
                                if hasattr(source.source_type, "value")
                                else str(source.source_type),
                                "last_profiled_at": None,
                                "hours_overdue": round(hours_overdue, 2),
                                "pipeline_id": best_pipeline_id,
                                "expected_interval_hours": round(
                                    expected_interval_hours, 2
                                ),
                            }
                        )
                    else:
                        age_hours = (
                            now - source.last_profiled_at
                        ).total_seconds() / 3600.0
                        if age_hours > expected_interval_hours:
                            hours_overdue = age_hours - expected_interval_hours
                            stale.append(
                                {
                                    "source_id": sid,
                                    "source_name": source.name,
                                    "source_type": source.source_type.value
                                    if hasattr(source.source_type, "value")
                                    else str(source.source_type),
                                    "last_profiled_at": source.last_profiled_at.isoformat(),
                                    "hours_overdue": round(hours_overdue, 2),
                                    "pipeline_id": best_pipeline_id,
                                    "expected_interval_hours": round(
                                        expected_interval_hours, 2
                                    ),
                                }
                            )

            log.info(
                "check_freshness.done",
                tenant_id=self.tenant_id,
                stale_count=len(stale),
            )
            return stale

        except Exception as exc:
            log.error("check_freshness.error", tenant_id=self.tenant_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. System Health Aggregation
    # ------------------------------------------------------------------

    async def get_system_health(self) -> dict:
        """
        Returns a tenant-level health snapshot including:
          - pipeline_success_rate: % of completed runs (last 7 days) that succeeded
          - total_runs_7d: total pipeline runs in the last 7 days
          - failed_runs_7d: failed runs in the last 7 days
          - avg_quality_score: average quality score across all runs (last 7 days)
          - sla_compliance_rate: % of runs that completed within their pipeline SLA
          - active_pipelines: count of active pipelines
          - stale_sources: count of stale sources (calls check_freshness internally)
          - quality_trends: per-day pass/fail counts for the last 7 days
        """
        log.info("get_system_health.start", tenant_id=self.tenant_id)

        try:
            window_start = utcnow() - timedelta(days=7)

            async with AsyncSessionLocal() as db:
                # --- Run stats (last 7 days) ---
                runs_result = await db.execute(
                    select(PipelineRun).where(
                        PipelineRun.tenant_id == self.tenant_id,
                        PipelineRun.created_at >= window_start,
                        PipelineRun.status.in_(
                            [RunStatus.SUCCESS, RunStatus.FAILED]
                        ),
                    )
                )
                runs = runs_result.scalars().all()

                total_runs = len(runs)
                success_runs = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
                failed_runs = total_runs - success_runs
                pipeline_success_rate = (
                    round(success_runs / total_runs * 100, 2) if total_runs else 0.0
                )

                # Avg quality score (only runs that have a score)
                scored_runs = [r for r in runs if r.quality_score is not None]
                avg_quality_score = (
                    round(
                        sum(r.quality_score for r in scored_runs) / len(scored_runs),
                        2,
                    )
                    if scored_runs
                    else None
                )

                # --- SLA compliance ---
                # Fetch pipelines to get their SLA in minutes
                pipelines_result = await db.execute(
                    select(Pipeline).where(
                        Pipeline.tenant_id == self.tenant_id,
                    )
                )
                pipelines = pipelines_result.scalars().all()
                sla_map = {
                    str(p.id): p.sla_minutes for p in pipelines if p.sla_minutes
                }

                sla_eligible = [
                    r
                    for r in runs
                    if r.duration_seconds is not None
                    and str(r.pipeline_id) in sla_map
                ]
                sla_met = sum(
                    1
                    for r in sla_eligible
                    if r.duration_seconds <= sla_map[str(r.pipeline_id)] * 60
                )
                sla_compliance_rate = (
                    round(sla_met / len(sla_eligible) * 100, 2)
                    if sla_eligible
                    else None
                )

                # --- Active pipelines count ---
                active_count_result = await db.execute(
                    select(func.count(Pipeline.id)).where(
                        Pipeline.tenant_id == self.tenant_id,
                        Pipeline.status == PipelineStatus.ACTIVE,
                    )
                )
                active_pipelines = active_count_result.scalar() or 0

                # --- Quality trends: daily pass/fail run counts ---
                trends = {}
                for r in runs:
                    day = (r.created_at or utcnow()).date().isoformat()
                    if day not in trends:
                        trends[day] = {"date": day, "success": 0, "failed": 0}
                    if r.status == RunStatus.SUCCESS:
                        trends[day]["success"] += 1
                    else:
                        trends[day]["failed"] += 1
                quality_trends = sorted(trends.values(), key=lambda x: x["date"])

            # --- Stale source count ---
            freshness = await self.check_freshness()
            stale_sources = (
                len(freshness)
                if isinstance(freshness, list)
                else 0
            )

            health = {
                "tenant_id": self.tenant_id,
                "evaluated_at": utcnow().isoformat(),
                "window_days": 7,
                "pipeline_success_rate": pipeline_success_rate,
                "total_runs_7d": total_runs,
                "failed_runs_7d": failed_runs,
                "avg_quality_score": avg_quality_score,
                "sla_compliance_rate": sla_compliance_rate,
                "active_pipelines": active_pipelines,
                "stale_sources": stale_sources,
                "quality_trends": quality_trends,
            }

            log.info(
                "get_system_health.done",
                tenant_id=self.tenant_id,
                success_rate=pipeline_success_rate,
            )
            return health

        except Exception as exc:
            log.error(
                "get_system_health.error", tenant_id=self.tenant_id, error=str(exc)
            )
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Per-Pipeline Stats
    # ------------------------------------------------------------------

    async def get_pipeline_stats(self, pipeline_id: str) -> dict:
        """
        Returns detailed performance stats for a single pipeline:
          - pipeline_id, pipeline_name, status, schedule_cron, sla_minutes
          - last_run: most recent PipelineRun summary
          - total_runs: all-time run count
          - success_rate: % success across all runs
          - avg_duration_seconds: average duration of completed runs
          - avg_rows_processed: average rows processed per run
          - last_5_runs: ordered list of the 5 most recent runs (id, status, duration,
            rows_processed, quality_score, started_at, completed_at)
        """
        log.info(
            "get_pipeline_stats.start",
            tenant_id=self.tenant_id,
            pipeline_id=pipeline_id,
        )

        try:
            async with AsyncSessionLocal() as db:
                # Fetch pipeline — tenant-isolated
                pipeline_result = await db.execute(
                    select(Pipeline).where(
                        Pipeline.id == pipeline_id,
                        Pipeline.tenant_id == self.tenant_id,
                    )
                )
                pipeline = pipeline_result.scalar_one_or_none()

                if pipeline is None:
                    return {"error": f"Pipeline {pipeline_id} not found"}

                # Fetch all runs for this pipeline
                runs_result = await db.execute(
                    select(PipelineRun)
                    .where(
                        PipelineRun.pipeline_id == pipeline_id,
                        PipelineRun.tenant_id == self.tenant_id,
                    )
                    .order_by(desc(PipelineRun.created_at))
                )
                all_runs = runs_result.scalars().all()

                total_runs = len(all_runs)
                terminal_runs = [
                    r
                    for r in all_runs
                    if r.status in (RunStatus.SUCCESS, RunStatus.FAILED)
                ]
                success_count = sum(
                    1 for r in terminal_runs if r.status == RunStatus.SUCCESS
                )
                success_rate = (
                    round(success_count / len(terminal_runs) * 100, 2)
                    if terminal_runs
                    else 0.0
                )

                durations = [
                    r.duration_seconds
                    for r in all_runs
                    if r.duration_seconds is not None
                ]
                avg_duration_seconds = (
                    round(sum(durations) / len(durations), 2) if durations else None
                )

                rows = [
                    r.rows_processed
                    for r in all_runs
                    if r.rows_processed is not None
                ]
                avg_rows_processed = (
                    round(sum(rows) / len(rows), 2) if rows else None
                )

                last_5_runs = [
                    {
                        "run_id": str(r.id),
                        "status": r.status.value
                        if hasattr(r.status, "value")
                        else str(r.status),
                        "duration_seconds": r.duration_seconds,
                        "rows_processed": r.rows_processed,
                        "rows_failed": r.rows_failed,
                        "quality_score": r.quality_score,
                        "started_at": r.started_at.isoformat()
                        if r.started_at
                        else None,
                        "completed_at": r.completed_at.isoformat()
                        if r.completed_at
                        else None,
                        "error_message": r.error_message,
                    }
                    for r in all_runs[:5]
                ]

                last_run = last_5_runs[0] if last_5_runs else None

            stats = {
                "pipeline_id": str(pipeline.id),
                "pipeline_name": pipeline.name,
                "status": pipeline.status.value
                if hasattr(pipeline.status, "value")
                else str(pipeline.status),
                "schedule_cron": pipeline.schedule_cron,
                "sla_minutes": pipeline.sla_minutes,
                "total_runs": total_runs,
                "success_rate": success_rate,
                "avg_duration_seconds": avg_duration_seconds,
                "avg_rows_processed": avg_rows_processed,
                "last_run": last_run,
                "last_5_runs": last_5_runs,
            }

            log.info(
                "get_pipeline_stats.done",
                tenant_id=self.tenant_id,
                pipeline_id=pipeline_id,
                total_runs=total_runs,
            )
            return stats

        except Exception as exc:
            log.error(
                "get_pipeline_stats.error",
                tenant_id=self.tenant_id,
                pipeline_id=pipeline_id,
                error=str(exc),
            )
            return {"error": str(exc)}