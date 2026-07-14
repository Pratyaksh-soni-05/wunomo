from langchain_core.tools import tool
from typing import List


@tool
async def generate_status_report(tenant_id: str, mode: str = "engineer", period: str = "daily") -> dict:
    """Generate role-based status report. mode: engineer|founder|analyst|auditor."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).status_report(mode, period)


@tool
async def generate_incident_report(tenant_id: str, incident_id: str, audience: str = "engineer") -> dict:
    """Generate incident post-mortem: root cause, impact, timeline, fix. audience: engineer|founder."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).incident_report(incident_id, audience)


@tool
async def send_alert(tenant_id: str, channel: str, recipient: str, subject: str, message: str) -> dict:
    """Send alert via email or Slack. channel: email|slack."""
    from modules.reporting.notification_service import NotificationService
    return await NotificationService(tenant_id).send(channel, recipient, subject, message)


@tool
async def export_dataset(tenant_id: str, pipeline_id: str, format: str = "csv", destination: str = "download") -> dict:
    """Export pipeline output to csv|json or push to google_sheets|s3."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).export(pipeline_id, format, destination)


@tool
async def get_kpi_summary(tenant_id: str, kpi_names: List[str]) -> dict:
    """Get current values and 7-day trend for named KPIs."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).kpi_summary(kpi_names)


reporting_tools = [generate_status_report, generate_incident_report,
                    send_alert, export_dataset, get_kpi_summary]