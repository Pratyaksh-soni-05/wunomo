import json
import structlog
from datetime import datetime, timezone
from sqlalchemy import select, desc
from database import AsyncSessionLocal
from models.all_models import (
    Incident,
    IncidentStatus,
    IncidentSeverity,
    Pipeline,
    PipelineRun,
    DataSource,
)
from services.llm_service import LLMService

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Prompt template for AI triage
TRIAGE_PROMPT = """You are AXIOM, an expert DataOps engineer performing root-cause analysis on a data pipeline incident.

Analyze the following incident and provide:
1. A concise root cause (1-2 sentences, technical)
2. Up to 5 specific remediation actions (ordered by priority)
3. A severity assessment: low / medium / high / critical

Respond ONLY with valid JSON in this exact format:
{{
  "root_cause": "<concise technical root cause>",
  "remediation_actions": [
    "<action 1>",
    "<action 2>",
    "<action 3>"
  ],
  "suggested_severity": "<low|medium|high|critical>",
  "confidence": "<low|medium|high>",
  "summary": "<1-sentence executive summary>"
}}

--- INCIDENT DETAILS ---
Title: {title}
Description: {description}
Current Severity: {severity}
Pipeline: {pipeline_name} (ID: {pipeline_id})
Data Source: {source_name} (Type: {source_type})
Affected Assets: {affected_assets}

--- RECENT RUN CONTEXT ---
Last Run Status: {last_run_status}
Last Run Duration: {last_run_duration}s
Last Run Error: {last_run_error}
Rows Processed: {rows_processed}
Rows Failed: {rows_failed}
Quality Score: {quality_score}

--- PIPELINE CONFIGURATION ---
Schedule: {schedule_cron}
SLA (minutes): {sla_minutes}
Retry Policy: {retry_policy}
"""


class IncidentManager:
    """
    Manages incident lifecycle for AXIOM:
      - list_incidents: filtered listing from DB
      - triage_incident: LLM-powered root cause analysis
      - resolve_incident: mark incident resolved with notes
    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.llm = LLMService()

    # ------------------------------------------------------------------
    # 1. List Incidents
    # ------------------------------------------------------------------

    async def list_incidents(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Returns incidents for the tenant, with optional status/severity filters.

        Args:
            status:   one of open | investigating | resolved | suppressed (or None for all)
            severity: one of low | medium | high | critical (or None for all)
            limit:    max results (default 50)

        Returns:
            list of incident dicts ordered by detected_at desc
        """
        log.info(
            "list_incidents.start",
            tenant_id=self.tenant_id,
            status=status,
            severity=severity,
        )

        try:
            async with AsyncSessionLocal() as db:
                query = (
                    select(Incident)
                    .where(Incident.tenant_id == self.tenant_id)
                    .order_by(desc(Incident.detected_at))
                    .limit(limit)
                )

                if status:
                    try:
                        status_enum = IncidentStatus(status)
                        query = query.where(Incident.status == status_enum)
                    except ValueError:
                        return {"error": f"Invalid status '{status}'. Valid: open, investigating, resolved, suppressed"}

                if severity:
                    try:
                        severity_enum = IncidentSeverity(severity)
                        query = query.where(Incident.severity == severity_enum)
                    except ValueError:
                        return {"error": f"Invalid severity '{severity}'. Valid: low, medium, high, critical"}

                result = await db.execute(query)
                incidents = result.scalars().all()

            output = [self._serialize_incident(i) for i in incidents]
            log.info("list_incidents.done", tenant_id=self.tenant_id, count=len(output))
            return output

        except Exception as exc:
            log.error("list_incidents.error", tenant_id=self.tenant_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. Triage Incident (AI Root Cause Analysis)
    # ------------------------------------------------------------------

    async def triage_incident(self, incident_id: str, user_id: str | None = None, task_id: str | None = None) -> dict:
        """
        Performs AI-powered root cause analysis on a given incident.
        - Fetches the incident, its pipeline, source, and most recent run context
        - Builds a rich prompt and calls the LLM
        - Persists the root_cause, remediation_actions, and updates status → investigating
        - Returns the full triage result

        user_id/task_id are optional, call-time-only attribution for the
        underlying LLM call's usage row - this is the tool-internal LLM
        call that's invisible to task_executor's own cost accounting
        (task_id only reaches here when the triage_incident tool is called
        from within a task; chat calls always pass task_id=None, correctly,
        since a chat turn isn't part of any task).

        Returns:
            dict with: incident_id, root_cause, remediation_actions,
                       suggested_severity, confidence, summary, triage_model
        """
        log.info(
            "triage_incident.start",
            tenant_id=self.tenant_id,
            incident_id=incident_id,
        )

        try:
            async with AsyncSessionLocal() as db:
                # Fetch incident — tenant isolated
                inc_result = await db.execute(
                    select(Incident).where(
                        Incident.id == incident_id,
                        Incident.tenant_id == self.tenant_id,
                    )
                )
                incident = inc_result.scalar_one_or_none()
                if incident is None:
                    return {"error": f"Incident {incident_id} not found"}

                # Fetch pipeline context
                pipeline = None
                if incident.pipeline_id:
                    pip_result = await db.execute(
                        select(Pipeline).where(
                            Pipeline.id == incident.pipeline_id,
                            Pipeline.tenant_id == self.tenant_id,
                        )
                    )
                    pipeline = pip_result.scalar_one_or_none()

                # Fetch data source
                source = None
                if pipeline and pipeline.source_id:
                    src_result = await db.execute(
                        select(DataSource).where(
                            DataSource.id == pipeline.source_id,
                            DataSource.tenant_id == self.tenant_id,
                        )
                    )
                    source = src_result.scalar_one_or_none()

                # Fetch most recent run for this pipeline
                last_run = None
                if incident.run_id:
                    run_result = await db.execute(
                        select(PipelineRun).where(
                            PipelineRun.id == incident.run_id,
                            PipelineRun.tenant_id == self.tenant_id,
                        )
                    )
                    last_run = run_result.scalar_one_or_none()
                elif pipeline:
                    run_result = await db.execute(
                        select(PipelineRun)
                        .where(
                            PipelineRun.pipeline_id == incident.pipeline_id,
                            PipelineRun.tenant_id == self.tenant_id,
                        )
                        .order_by(desc(PipelineRun.created_at))
                        .limit(1)
                    )
                    last_run = run_result.scalar_one_or_none()

                # Build prompt context
                prompt = TRIAGE_PROMPT.format(
                    title=incident.title or "Untitled Incident",
                    description=incident.description or "No description provided",
                    severity=incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity),
                    pipeline_id=str(incident.pipeline_id) if incident.pipeline_id else "N/A",
                    pipeline_name=pipeline.name if pipeline else "Unknown",
                    source_name=source.name if source else "Unknown",
                    source_type=source.source_type.value if source and hasattr(source.source_type, "value") else "Unknown",
                    affected_assets=json.dumps(incident.affected_assets) if incident.affected_assets else "[]",
                    last_run_status=last_run.status.value if last_run and hasattr(last_run.status, "value") else "N/A",
                    last_run_duration=last_run.duration_seconds if last_run and last_run.duration_seconds else "N/A",
                    last_run_error=last_run.error_message if last_run and last_run.error_message else "None",
                    rows_processed=last_run.rows_processed if last_run and last_run.rows_processed is not None else "N/A",
                    rows_failed=last_run.rows_failed if last_run and last_run.rows_failed is not None else "N/A",
                    quality_score=last_run.quality_score if last_run and last_run.quality_score is not None else "N/A",
                    schedule_cron=pipeline.schedule_cron if pipeline and pipeline.schedule_cron else "Manual",
                    sla_minutes=pipeline.sla_minutes if pipeline and pipeline.sla_minutes else "Not set",
                    retry_policy=json.dumps(pipeline.retry_policy) if pipeline and pipeline.retry_policy else "{}",
                )

                # Call LLM
                log.info("triage_incident.llm_call", incident_id=incident_id)
                llm_response = await self.llm.complete(
                    prompt, tenant_id=self.tenant_id, user_id=user_id, task_id=task_id,
                    request_type="incident_triage",
                )

                # Parse JSON from LLM response
                triage_data = self._parse_llm_json(llm_response)
                if "error" in triage_data:
                    log.warning(
                        "triage_incident.llm_parse_failed",
                        incident_id=incident_id,
                        raw=llm_response[:300],
                    )
                    # Partial result: still persist what we have
                    triage_data = {
                        "root_cause": "AI analysis failed to parse — see raw response",
                        "remediation_actions": [],
                        "suggested_severity": incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity),
                        "confidence": "low",
                        "summary": llm_response[:200] if llm_response else "No response",
                    }

                # Persist root cause, remediation, and flip status → investigating
                incident.root_cause = triage_data.get("root_cause", "")
                incident.remediation_actions = triage_data.get("remediation_actions", [])
                if incident.status == IncidentStatus.OPEN:
                    incident.status = IncidentStatus.INVESTIGATING

                db.add(incident)
                await db.commit()

            result = {
                "incident_id": incident_id,
                "root_cause": triage_data.get("root_cause"),
                "remediation_actions": triage_data.get("remediation_actions", []),
                "suggested_severity": triage_data.get("suggested_severity"),
                "confidence": triage_data.get("confidence"),
                "summary": triage_data.get("summary"),
                "status_updated_to": "investigating",
                "triage_model": "gemini-3-flash-preview",
            }

            log.info(
                "triage_incident.done",
                tenant_id=self.tenant_id,
                incident_id=incident_id,
                confidence=triage_data.get("confidence"),
            )
            return result

        except Exception as exc:
            log.error(
                "triage_incident.error",
                tenant_id=self.tenant_id,
                incident_id=incident_id,
                error=str(exc),
            )
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Resolve Incident
    # ------------------------------------------------------------------

    async def resolve_incident(self, incident_id: str, notes: str) -> dict:
        """
        Marks an incident as resolved.
        - Sets status → resolved
        - Records resolved_at timestamp
        - Persists resolution_notes

        Args:
            incident_id: UUID of the incident
            notes:       Human-supplied resolution notes

        Returns:
            dict with: incident_id, status, resolved_at, resolution_notes
        """
        log.info(
            "resolve_incident.start",
            tenant_id=self.tenant_id,
            incident_id=incident_id,
        )

        try:
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

                if incident.status == IncidentStatus.RESOLVED:
                    return {
                        "error": f"Incident {incident_id} is already resolved",
                        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
                    }

                now = utcnow()
                incident.status = IncidentStatus.RESOLVED
                incident.resolved_at = now
                incident.resolution_notes = notes

                db.add(incident)
                await db.commit()

            result = {
                "incident_id": incident_id,
                "status": "resolved",
                "resolved_at": now.isoformat(),
                "resolution_notes": notes,
            }

            log.info(
                "resolve_incident.done",
                tenant_id=self.tenant_id,
                incident_id=incident_id,
            )
            return result

        except Exception as exc:
            log.error(
                "resolve_incident.error",
                tenant_id=self.tenant_id,
                incident_id=incident_id,
                error=str(exc),
            )
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _serialize_incident(self, incident: Incident) -> dict:
        return {
            "incident_id": str(incident.id),
            "title": incident.title,
            "description": incident.description,
            "severity": incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity),
            "status": incident.status.value if hasattr(incident.status, "value") else str(incident.status),
            "pipeline_id": str(incident.pipeline_id) if incident.pipeline_id else None,
            "run_id": str(incident.run_id) if incident.run_id else None,
            "root_cause": incident.root_cause,
            "remediation_actions": incident.remediation_actions or [],
            "affected_assets": incident.affected_assets or [],
            "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
            "resolution_notes": incident.resolution_notes,
            "created_at": incident.created_at.isoformat() if incident.created_at else None,
        }

    def _parse_llm_json(self, raw: str) -> dict:
        """
        Extracts and parses a JSON block from an LLM response.
        Handles markdown fences (```json ... ```) and bare JSON.
        Returns {"error": "..."} if parsing fails.
        """
        if not raw:
            return {"error": "Empty LLM response"}
        try:
            # Strip markdown fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                # Remove first and last fence lines
                inner_lines = [
                    l for l in lines if not l.strip().startswith("```")
                ]
                cleaned = "\n".join(inner_lines).strip()
            # Find the first { and last } to extract JSON
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start == -1 or end == 0:
                return {"error": "No JSON object found in LLM response"}
            json_str = cleaned[start:end]
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse error: {str(e)}"}