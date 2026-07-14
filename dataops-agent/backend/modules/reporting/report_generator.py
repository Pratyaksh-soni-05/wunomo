import structlog
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc, func
from database import AsyncSessionLocal
from models.all_models import (
    Pipeline, PipelineRun, DataSource, Incident, QualityRule,
    KpiValue, AuditLog, DataContract,
    PipelineStatus, RunStatus, IncidentStatus,
)
from modules.observability.monitor import Monitor
from modules.observability.incident_manager import IncidentManager

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ReportGenerator:
    """
    Assembles role-based reports for AXIOM.

    Personality modes shape what data is surfaced:
      engineer  → pipeline states, run logs, quality scores, schema changes
      founder   → business impact, data reliability %, incidents resolved, cost saved
      analyst   → dataset freshness, KPI accuracy, available datasets, stale tables
      auditor   → lineage paths, contract violations, approval history, policy tags

    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Status report (role-based)
    # ------------------------------------------------------------------

    async def generate_status_report(self, mode: str = "engineer") -> dict:
        """
        Generates a full status report tailored to the given personality mode.

        Args:
            mode: "engineer" | "founder" | "analyst" | "auditor"

        Returns:
            A dict report shaped for the mode. All modes share a common base
            plus mode-specific sections.
        """
        log.info("report.generate_status_report", tenant_id=self.tenant_id, mode=mode)

        try:
            window_start = utcnow() - timedelta(days=7)

            async with AsyncSessionLocal() as db:
                # Common: pipelines
                pips_result = await db.execute(
                    select(Pipeline).where(Pipeline.tenant_id == self.tenant_id)
                )
                pipelines = pips_result.scalars().all()

                # Common: recent runs (7d)
                runs_result = await db.execute(
                    select(PipelineRun).where(
                        PipelineRun.tenant_id == self.tenant_id,
                        PipelineRun.created_at >= window_start,
                    ).order_by(desc(PipelineRun.created_at))
                )
                runs = runs_result.scalars().all()

                # Common: incidents
                inc_result = await db.execute(
                    select(Incident).where(
                        Incident.tenant_id == self.tenant_id,
                    ).order_by(desc(Incident.created_at))
                )
                incidents = inc_result.scalars().all()

                # Common: sources
                src_result = await db.execute(
                    select(DataSource).where(
                        DataSource.tenant_id == self.tenant_id,
                        DataSource.is_active == True,
                    )
                )
                sources = src_result.scalars().all()

            # --- Common metrics ---
            total_runs = len([r for r in runs if r.status in (RunStatus.success, RunStatus.failed)])
            success_runs = len([r for r in runs if r.status == RunStatus.success])
            success_rate = round(success_runs / total_runs * 100, 2) if total_runs else 0.0

            scored = [r.quality_score for r in runs if r.quality_score is not None]
            avg_quality = round(sum(scored) / len(scored), 2) if scored else None

            open_incidents = [i for i in incidents if i.status in (IncidentStatus.open, IncidentStatus.investigating)]
            resolved_this_week = [
                i for i in incidents
                if i.status == IncidentStatus.resolved
                and i.resolved_at and i.resolved_at >= window_start
            ]

            # --- Freshness ---
            monitor = Monitor(self.tenant_id)
            freshness = await monitor.check_freshness()
            stale_sources = freshness if isinstance(freshness, list) else []

            base = {
                "report_mode": mode,
                "tenant_id": self.tenant_id,
                "generated_at": utcnow().isoformat(),
                "window_days": 7,
                "summary": {
                    "total_pipelines": len(pipelines),
                    "active_pipelines": sum(1 for p in pipelines if p.status == PipelineStatus.active),
                    "total_runs_7d": total_runs,
                    "success_rate_pct": success_rate,
                    "avg_quality_score": avg_quality,
                    "open_incidents": len(open_incidents),
                    "stale_sources": len(stale_sources),
                },
            }

            # --- Mode-specific sections ---
            if mode == "engineer":
                base["pipeline_details"] = [
                    {
                        "pipeline_id": str(p.id),
                        "name": p.name,
                        "status": p.status.value,
                        "schedule_cron": p.schedule_cron,
                        "sla_minutes": p.sla_minutes,
                        "version": p.version,
                    }
                    for p in pipelines
                ]
                base["recent_failures"] = [
                    {
                        "run_id": str(r.id),
                        "pipeline_id": str(r.pipeline_id),
                        "error_message": r.error_message,
                        "rows_failed": r.rows_failed,
                        "quality_score": r.quality_score,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                    }
                    for r in runs
                    if r.status == RunStatus.failed
                ][:10]
                base["stale_sources"] = stale_sources
                base["open_incidents"] = [
                    {
                        "incident_id": str(i.id),
                        "title": i.title,
                        "severity": i.severity.value if hasattr(i.severity, "value") else str(i.severity),
                        "root_cause": i.root_cause,
                        "detected_at": i.detected_at.isoformat() if i.detected_at else None,
                    }
                    for i in open_incidents
                ]

            elif mode == "founder":
                reliability_pct = success_rate
                base["executive_summary"] = [
                    f"Data reliability: {reliability_pct}% pipeline success rate (last 7 days)",
                    f"{len(resolved_this_week)} incident(s) resolved this week",
                    f"{len(open_incidents)} incident(s) currently open",
                    f"{len(stale_sources)} data source(s) are stale and need attention",
                    f"Average data quality score: {avg_quality}/100" if avg_quality else "Quality score not yet available",
                ]
                base["business_impact"] = {
                    "data_reliability_pct": reliability_pct,
                    "incidents_resolved_this_week": len(resolved_this_week),
                    "active_data_sources": len(sources),
                    "pipelines_running": sum(1 for p in pipelines if p.status == PipelineStatus.active),
                }

            elif mode == "analyst":
                base["dataset_freshness"] = stale_sources
                base["available_datasets"] = [
                    {
                        "source_id": str(s.id),
                        "name": s.name,
                        "type": s.source_type.value if hasattr(s.source_type, "value") else str(s.source_type),
                        "last_profiled_at": s.last_profiled_at.isoformat() if s.last_profiled_at else None,
                        "tags": s.tags or [],
                    }
                    for s in sources
                ]
                # KPI summary
                async with AsyncSessionLocal() as db:
                    kpis_result = await db.execute(
                        select(KpiValue)
                        .where(
                            KpiValue.tenant_id == self.tenant_id,
                            KpiValue.recorded_at >= window_start,
                        )
                        .order_by(desc(KpiValue.recorded_at))
                    )
                    kpis = kpis_result.scalars().all()
                seen = set()
                kpi_summary = []
                for k in kpis:
                    if k.kpi_name not in seen:
                        seen.add(k.kpi_name)
                        kpi_summary.append({
                            "kpi_name": k.kpi_name,
                            "latest_value": k.value,
                            "unit": k.unit,
                            "recorded_at": k.recorded_at.isoformat() if k.recorded_at else None,
                        })
                base["kpi_summary"] = kpi_summary

            elif mode == "auditor":
                # Contracts
                async with AsyncSessionLocal() as db:
                    contracts_result = await db.execute(
                        select(DataContract).where(DataContract.tenant_id == self.tenant_id)
                    )
                    contracts = contracts_result.scalars().all()

                    audit_result = await db.execute(
                        select(AuditLog)
                        .where(
                            AuditLog.tenant_id == self.tenant_id,
                            AuditLog.created_at >= window_start,
                        )
                        .order_by(desc(AuditLog.created_at))
                        .limit(50)
                    )
                    audit_entries = audit_result.scalars().all()

                violated = [c for c in contracts if c.validation_status == "violated"]
                base["contract_summary"] = {
                    "total_contracts": len(contracts),
                    "violated": len(violated),
                    "valid": sum(1 for c in contracts if c.validation_status == "valid"),
                    "pending_validation": sum(1 for c in contracts if c.validation_status == "pending"),
                }
                base["contract_violations"] = [
                    {"contract_id": str(c.id), "name": c.name, "last_validated_at": c.last_validated_at.isoformat() if c.last_validated_at else None}
                    for c in violated
                ]
                base["recent_audit_trail"] = [
                    {
                        "actor": e.actor,
                        "action": e.action,
                        "resource_type": e.resource_type,
                        "resource_id": e.resource_id,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in audit_entries
                ]

            log.info("report.generate_status_report.done", mode=mode)
            return base

        except Exception as exc:
            log.error("report.generate_status_report.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. Incident post-mortem report
    # ------------------------------------------------------------------

    async def generate_incident_report(self, incident_id: str) -> dict:
        """
        Generates a structured post-mortem for a given incident.

        Sections:
          - title, severity, timeline
          - root_cause (from triage or manual)
          - affected_assets
          - remediation_actions
          - resolution (notes + timestamp)
          - lessons_learned (LLM-generated if root_cause is present)

        Returns: post-mortem dict
        """
        log.info("report.generate_incident_report", incident_id=incident_id)
        try:
            from models.all_models import Incident, Pipeline, PipelineRun
            async with AsyncSessionLocal() as db:
                inc_result = await db.execute(
                    select(Incident).where(
                        Incident.id == incident_id,
                        Incident.tenant_id == self.tenant_id,
                    )
                )
                incident = inc_result.scalar_one_or_none()
                if incident is None:
                    return {"error": f"Incident {incident_id} not found"}

                pipeline = None
                if incident.pipeline_id:
                    pip_result = await db.execute(
                        select(Pipeline).where(
                            Pipeline.id == incident.pipeline_id,
                            Pipeline.tenant_id == self.tenant_id,
                        )
                    )
                    pipeline = pip_result.scalar_one_or_none()

            # Build timeline
            timeline = [
                {"event": "Incident detected", "timestamp": incident.detected_at.isoformat() if incident.detected_at else None},
            ]
            if incident.status == IncidentStatus.investigating or incident.status == IncidentStatus.resolved:
                timeline.append({"event": "Triage / investigation started", "timestamp": incident.created_at.isoformat() if incident.created_at else None})
            if incident.resolved_at:
                timeline.append({"event": "Incident resolved", "timestamp": incident.resolved_at.isoformat()})

            # Time to resolve
            ttd = None
            if incident.detected_at and incident.resolved_at:
                delta = incident.resolved_at - incident.detected_at
                ttd_minutes = delta.total_seconds() / 60
                ttd = f"{ttd_minutes:.0f} minutes"

            # Lessons learned — derive from root cause and remediation
            lessons_learned = []
            if incident.root_cause:
                lessons_learned.append(f"Root cause identified: {incident.root_cause}")
            if incident.remediation_actions:
                for action in (incident.remediation_actions or [])[:3]:
                    lessons_learned.append(f"Action taken: {action}")
            if not lessons_learned:
                lessons_learned = ["No root cause analysis was performed on this incident."]

            report = {
                "report_type": "incident_post_mortem",
                "generated_at": utcnow().isoformat(),
                "incident_id": incident_id,
                "title": incident.title,
                "severity": incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity),
                "status": incident.status.value if hasattr(incident.status, "value") else str(incident.status),
                "pipeline": {
                    "pipeline_id": str(incident.pipeline_id) if incident.pipeline_id else None,
                    "name": pipeline.name if pipeline else "Unknown",
                    "schedule": pipeline.schedule_cron if pipeline else None,
                } if incident.pipeline_id else None,
                "timeline": timeline,
                "time_to_resolve": ttd,
                "root_cause": incident.root_cause or "Not analyzed",
                "affected_assets": incident.affected_assets or [],
                "remediation_actions": incident.remediation_actions or [],
                "resolution_notes": incident.resolution_notes or "No resolution notes provided",
                "lessons_learned": lessons_learned,
            }

            log.info("report.generate_incident_report.done", incident_id=incident_id)
            return report

        except Exception as exc:
            log.error("report.generate_incident_report.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. KPI summary
    # ------------------------------------------------------------------

    async def get_kpi_summary(
        self,
        kpi_names: list[str] | None = None,
    ) -> dict:
        """
        Returns current values and 7-day trends for the given KPI names.
        If kpi_names is None, returns all KPIs for the tenant.

        Returns:
          { "kpis": [ { kpi_name, latest_value, unit, trend_7d: [...] } ] }
        """
        log.info("report.get_kpi_summary", tenant_id=self.tenant_id)
        try:
            window_start = utcnow() - timedelta(days=7)
            async with AsyncSessionLocal() as db:
                query = select(KpiValue).where(
                    KpiValue.tenant_id == self.tenant_id,
                    KpiValue.recorded_at >= window_start,
                ).order_by(desc(KpiValue.recorded_at))
                if kpi_names:
                    query = query.where(KpiValue.kpi_name.in_(kpi_names))
                result = await db.execute(query)
                kpis = result.scalars().all()

            grouped: dict[str, list] = {}
            for k in kpis:
                grouped.setdefault(k.kpi_name, []).append(k)

            output = []
            for name, values in grouped.items():
                latest = values[0]
                output.append({
                    "kpi_name": name,
                    "latest_value": latest.value,
                    "unit": latest.unit,
                    "last_recorded_at": latest.recorded_at.isoformat() if latest.recorded_at else None,
                    "trend_7d": [
                        {"value": v.value, "recorded_at": v.recorded_at.isoformat() if v.recorded_at else None}
                        for v in values
                    ],
                })

            return {"kpis": output, "count": len(output)}

        except Exception as exc:
            log.error("report.get_kpi_summary.error", error=str(exc))
            return {"error": str(exc)}