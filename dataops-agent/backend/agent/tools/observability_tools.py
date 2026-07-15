from langchain_core.tools import tool
from typing import Optional
from agent.tools._utils import cap_tool_result

@tool
async def check_freshness(tenant_id: str, source_id: Optional[str] = None) -> dict:
    """Check dataset freshness against SLA. Returns stale datasets with hours_overdue."""
    from modules.observability.monitor import ObservabilityMonitor
    return cap_tool_result(await ObservabilityMonitor(tenant_id).check_freshness(source_id))

@tool
async def detect_anomalies(tenant_id: str, pipeline_id: str) -> dict:
    """Detect anomalies: row count spikes, null rate changes, value distribution shifts."""
    from modules.observability.anomaly_detector import AnomalyDetector
    return cap_tool_result(await AnomalyDetector(tenant_id).detect(pipeline_id))

@tool
async def list_open_incidents(tenant_id: str) -> dict:
    """List all open data incidents with severity, status, and affected assets."""
    from modules.observability.incident_manager import IncidentManager
    return cap_tool_result(await IncidentManager(tenant_id).list_incidents(status="open"))

@tool
async def triage_incident(tenant_id: str, incident_id: str) -> dict:
    """AI-assisted root cause analysis for an incident."""
    from modules.observability.incident_manager import IncidentManager
    return await IncidentManager(tenant_id).triage_incident(incident_id)

@tool
async def resolve_incident(tenant_id: str, incident_id: str, resolution_notes: str) -> dict:
    """Mark an incident as resolved with notes."""
    from modules.observability.incident_manager import IncidentManager
    return await IncidentManager(tenant_id).resolve_incident(incident_id, resolution_notes)

@tool
async def get_system_health(tenant_id: str) -> dict:
    """Overall data stack health: pipeline success rates, quality trends, SLA compliance."""
    from modules.observability.monitor import ObservabilityMonitor
    return cap_tool_result(await ObservabilityMonitor(tenant_id).system_health())

observability_tools = [check_freshness, detect_anomalies, list_open_incidents,
                        triage_incident, resolve_incident, get_system_health]
