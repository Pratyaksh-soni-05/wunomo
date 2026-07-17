from langchain_core.tools import tool
from typing import List


@tool
async def generate_status_report(tenant_id: str, mode: str = "engineer") -> dict:
    """Generate role-based status report. mode: engineer|founder|analyst|auditor."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).generate_status_report(mode)


@tool
async def generate_incident_report(tenant_id: str, incident_id: str) -> dict:
    """Generate incident post-mortem: root cause, impact, timeline, fix."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).generate_incident_report(incident_id)


@tool
async def send_alert(tenant_id: str, channel: str, title: str, message: str, severity: str = "medium") -> dict:
    """Send an alert via email, Slack, or both. channel: email|slack|both.
    severity: low|medium|high|critical."""
    from modules.reporting.notification_service import NotificationService
    return await NotificationService(tenant_id).send_alert(
        channel=channel, message=message, severity=severity, title=title)


@tool
async def export_dataset(tenant_id: str, pipeline_id: str, format: str = "csv", destination: str = "download") -> dict:
    """Export pipeline output to csv/json or push to google_sheets/s3."""
    return {
        "error": "Dataset export is not implemented yet — there is no real export "
                 "path in this system for any format or destination. Do not tell "
                 "the user this succeeded."
    }


@tool
async def get_kpi_summary(tenant_id: str, kpi_names: List[str]) -> dict:
    """Get current values and 7-day trend for named KPIs."""
    from modules.reporting.report_generator import ReportGenerator
    return await ReportGenerator(tenant_id).get_kpi_summary(kpi_names)


reporting_tools = [generate_status_report, generate_incident_report,
                    send_alert, export_dataset, get_kpi_summary]
