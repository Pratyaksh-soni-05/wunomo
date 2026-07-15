import structlog
from datetime import datetime, timezone
from sqlalchemy import select, desc
from database import AsyncSessionLocal
from models.all_models import Pipeline, PipelineRun, PipelineStatus, RunStatus

log = structlog.get_logger()

# Thresholds
ROW_COUNT_SPIKE_MULTIPLIER = 3.0      # last run rows > 3x avg → spike
ROW_COUNT_DROP_RATIO = 0.3            # last run rows < 30% of avg → drop
DURATION_SPIKE_MULTIPLIER = 2.0       # last run duration > 2x avg → slow
NULL_RATE_SPIKE_DELTA = 0.20          # null rate increased by >20 ppts → anomaly
QUALITY_SCORE_DROP_DELTA = 15.0       # quality score dropped >15 pts → anomaly
MIN_BASELINE_RUNS = 3                 # need at least this many prior runs to detect


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_div(a, b, default=0.0):
    return a / b if b else default


class AnomalyDetector:
    """
    Detects statistical anomalies in pipeline run data.
    Compares the most recent run against a rolling baseline
    of the previous N runs.
    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Detect anomalies for a single pipeline
    # ------------------------------------------------------------------

    async def detect_anomalies(self, pipeline_id: str) -> dict:
        """
        Compares the latest completed run against the baseline of the
        prior runs (up to last 10) for the given pipeline.

        Checks performed:
          - row_count_spike: rows_processed >> avg baseline
          - row_count_drop:  rows_processed << avg baseline
          - duration_spike:  duration_seconds >> avg baseline
          - quality_drop:    quality_score dropped significantly
          - null_rate_spike: rows_failed/rows_processed ratio spiked

        Returns:
            {
              "pipeline_id": ...,
              "pipeline_name": ...,
              "latest_run_id": ...,
              "anomalies": [ { type, severity, value, baseline, message } ],
              "baseline_run_count": ...,
              "evaluated_at": ...
            }
        """
        log.info("detect_anomalies.start", tenant_id=self.tenant_id, pipeline_id=pipeline_id)

        try:
            async with AsyncSessionLocal() as db:
                # Verify pipeline belongs to tenant
                pip_result = await db.execute(
                    select(Pipeline).where(
                        Pipeline.id == pipeline_id,
                        Pipeline.tenant_id == self.tenant_id,
                    )
                )
                pipeline = pip_result.scalar_one_or_none()
                if pipeline is None:
                    return {"error": f"Pipeline {pipeline_id} not found"}

                # Fetch last 11 terminal runs (success or failed), newest first
                runs_result = await db.execute(
                    select(PipelineRun)
                    .where(
                        PipelineRun.pipeline_id == pipeline_id,
                        PipelineRun.tenant_id == self.tenant_id,
                        PipelineRun.status.in_([RunStatus.SUCCESS, RunStatus.FAILED]),
                    )
                    .order_by(desc(PipelineRun.created_at))
                    .limit(11)
                )
                runs = runs_result.scalars().all()

            if len(runs) < 2:
                return {
                    "pipeline_id": pipeline_id,
                    "pipeline_name": pipeline.name,
                    "latest_run_id": str(runs[0].id) if runs else None,
                    "anomalies": [],
                    "baseline_run_count": len(runs),
                    "evaluated_at": utcnow().isoformat(),
                    "message": "Not enough run history to detect anomalies (need at least 2 runs)",
                }

            latest = runs[0]
            baseline_runs = runs[1:]  # up to 10 prior runs

            if len(baseline_runs) < MIN_BASELINE_RUNS:
                log.info(
                    "detect_anomalies.low_baseline",
                    pipeline_id=pipeline_id,
                    baseline_count=len(baseline_runs),
                )

            anomalies = []

            # --- Row count checks ---
            baseline_rows = [r.rows_processed for r in baseline_runs if r.rows_processed is not None]
            if baseline_rows and latest.rows_processed is not None:
                avg_rows = sum(baseline_rows) / len(baseline_rows)
                latest_rows = latest.rows_processed

                if avg_rows > 0 and latest_rows > avg_rows * ROW_COUNT_SPIKE_MULTIPLIER:
                    anomalies.append({
                        "type": "row_count_spike",
                        "severity": "high",
                        "value": latest_rows,
                        "baseline": round(avg_rows, 2),
                        "message": (
                            f"Row count {latest_rows:,} is {latest_rows/avg_rows:.1f}x the "
                            f"baseline average of {avg_rows:,.0f} rows."
                        ),
                    })
                elif avg_rows > 0 and latest_rows < avg_rows * ROW_COUNT_DROP_RATIO:
                    anomalies.append({
                        "type": "row_count_drop",
                        "severity": "high",
                        "value": latest_rows,
                        "baseline": round(avg_rows, 2),
                        "message": (
                            f"Row count {latest_rows:,} is only "
                            f"{latest_rows/avg_rows*100:.1f}% of the baseline "
                            f"average of {avg_rows:,.0f} rows. Possible data source issue."
                        ),
                    })

            # --- Duration spike ---
            baseline_durations = [r.duration_seconds for r in baseline_runs if r.duration_seconds is not None]
            if baseline_durations and latest.duration_seconds is not None:
                avg_duration = sum(baseline_durations) / len(baseline_durations)
                if avg_duration > 0 and latest.duration_seconds > avg_duration * DURATION_SPIKE_MULTIPLIER:
                    anomalies.append({
                        "type": "duration_spike",
                        "severity": "medium",
                        "value": latest.duration_seconds,
                        "baseline": round(avg_duration, 2),
                        "message": (
                            f"Run duration {latest.duration_seconds}s is "
                            f"{latest.duration_seconds/avg_duration:.1f}x the baseline "
                            f"average of {avg_duration:.0f}s."
                        ),
                    })

            # --- Quality score drop ---
            baseline_scores = [r.quality_score for r in baseline_runs if r.quality_score is not None]
            if baseline_scores and latest.quality_score is not None:
                avg_score = sum(baseline_scores) / len(baseline_scores)
                drop = avg_score - latest.quality_score
                if drop >= QUALITY_SCORE_DROP_DELTA:
                    anomalies.append({
                        "type": "quality_drop",
                        "severity": "high" if drop >= 30 else "medium",
                        "value": latest.quality_score,
                        "baseline": round(avg_score, 2),
                        "message": (
                            f"Quality score dropped to {latest.quality_score:.1f} "
                            f"from baseline average of {avg_score:.1f} "
                            f"(Δ -{drop:.1f} pts)."
                        ),
                    })

            # --- Null / failure rate spike ---
            # Proxy: rows_failed / rows_processed
            def null_rate(run):
                if run.rows_processed and run.rows_processed > 0 and run.rows_failed is not None:
                    return run.rows_failed / run.rows_processed
                return None

            baseline_null_rates = [nr for r in baseline_runs if (nr := null_rate(r)) is not None]
            latest_null = null_rate(latest)
            if baseline_null_rates and latest_null is not None:
                avg_null = sum(baseline_null_rates) / len(baseline_null_rates)
                delta = latest_null - avg_null
                if delta >= NULL_RATE_SPIKE_DELTA:
                    anomalies.append({
                        "type": "null_rate_spike",
                        "severity": "high" if delta >= 0.4 else "medium",
                        "value": round(latest_null * 100, 2),
                        "baseline": round(avg_null * 100, 2),
                        "message": (
                            f"Failure/null rate spiked to {latest_null*100:.1f}% "
                            f"from baseline {avg_null*100:.1f}% "
                            f"(+{delta*100:.1f} ppts)."
                        ),
                    })

            result = {
                "pipeline_id": pipeline_id,
                "pipeline_name": pipeline.name,
                "latest_run_id": str(latest.id),
                "anomalies": anomalies,
                "anomaly_count": len(anomalies),
                "baseline_run_count": len(baseline_runs),
                "evaluated_at": utcnow().isoformat(),
            }

            log.info(
                "detect_anomalies.done",
                tenant_id=self.tenant_id,
                pipeline_id=pipeline_id,
                anomaly_count=len(anomalies),
            )
            return result

        except Exception as exc:
            log.error("detect_anomalies.error", tenant_id=self.tenant_id, pipeline_id=pipeline_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. Detect anomalies across ALL active pipelines for a tenant
    # ------------------------------------------------------------------

    async def detect_all_anomalies(self) -> dict:
        """
        Runs detect_anomalies() across every active pipeline for this tenant.
        Skips pipelines with errors or insufficient history.

        Returns:
            {
              "tenant_id": ...,
              "evaluated_at": ...,
              "pipelines_checked": N,
              "pipelines_with_anomalies": N,
              "total_anomalies": N,
              "results": [ { pipeline_id, pipeline_name, anomaly_count, anomalies } ]
            }
        """
        log.info("detect_all_anomalies.start", tenant_id=self.tenant_id)

        try:
            async with AsyncSessionLocal() as db:
                pips_result = await db.execute(
                    select(Pipeline).where(
                        Pipeline.tenant_id == self.tenant_id,
                        Pipeline.status == PipelineStatus.ACTIVE,
                    )
                )
                pipelines = pips_result.scalars().all()

            results = []
            total_anomalies = 0

            for pipeline in pipelines:
                detection = await self.detect_anomalies(str(pipeline.id))
                if "error" in detection:
                    continue
                if detection.get("anomaly_count", 0) > 0:
                    results.append({
                        "pipeline_id": str(pipeline.id),
                        "pipeline_name": pipeline.name,
                        "anomaly_count": detection["anomaly_count"],
                        "anomalies": detection["anomalies"],
                        "latest_run_id": detection.get("latest_run_id"),
                    })
                    total_anomalies += detection["anomaly_count"]

            summary = {
                "tenant_id": self.tenant_id,
                "evaluated_at": utcnow().isoformat(),
                "pipelines_checked": len(pipelines),
                "pipelines_with_anomalies": len(results),
                "total_anomalies": total_anomalies,
                "results": results,
            }

            log.info(
                "detect_all_anomalies.done",
                tenant_id=self.tenant_id,
                pipelines_checked=len(pipelines),
                total_anomalies=total_anomalies,
            )
            return summary

        except Exception as exc:
            log.error("detect_all_anomalies.error", tenant_id=self.tenant_id, error=str(exc))
            return {"error": str(exc)}