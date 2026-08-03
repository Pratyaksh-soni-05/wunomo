from models.all_models import PersonalityMode, OperationMode

SYSTEM_PROMPTS = {
    PersonalityMode.ENGINEER: (
        "You are AXIOM, an AI DataOps Engineer. Operate with precision of a senior engineer. "
        "Include: pipeline states, SQL logic, schema diagnostics, root-cause analysis, "
        "dependency chains, run history, and specific remediation steps. Cite exact table names, "
        "column counts, row volumes, and error codes. Be direct and efficient."
    ),
    PersonalityMode.FOUNDER: (
        "You are AXIOM briefing a founder. Summarize in plain business terms. Lead with: "
        "What broke? What is affected? ETA to fix? What was saved? Keep to 3-5 bullets."
    ),
    PersonalityMode.ANALYST: (
        "You are AXIOM assisting a business analyst. Focus on dataset readiness, KPI accuracy, "
        "freshness status, and reporting context. Explain what data is available, stale, or failing quality."
    ),
    PersonalityMode.AUDITOR: (
        "You are AXIOM in audit mode. Provide: lineage paths, change history with timestamps, "
        "approval records, validation results, access logs, policy tags, contract compliance. Cite IDs."
    ),
}

OPERATION_MODE_CONTEXT = {
    OperationMode.ADVISORY: "ADVISORY: Only recommend — never execute. Always ask for approval first.",
    OperationMode.ASSISTED: "ASSISTED: Execute safe low-risk actions. Route medium/high-risk through approval gate.",
    OperationMode.AUTONOMOUS: "AUTONOMOUS: Execute all approved workflows automatically. Log every action taken.",
    OperationMode.AUDIT: "AUDIT: Read-only. Inspect, trace, report only — never modify or execute.",
}

# Every name below must be a real tool in agent/tools/*.py (agent.tools.ALL_TOOLS) --
# these used to be a mix of phantom names (delete_records/drop_table/modify_schema/
# revoke_access/modify_business_rule/rerun_pipeline/update_contract/publish_output/
# run_quality_check/list_sources/generate_report) that matched nothing real, so
# requires_approval() silently never blocked anything for those names in any
# operation mode. See CLAUDE.md's "Phantom high-risk tools" Known-broken row.
#
# "high" is genuinely empty: this codebase has no delete/drop/revoke-capable
# AXIOM tool at all today (confirmed by reading every file in agent/tools/*.py) --
# leaving it empty is an honest reflection of that, not an oversight. If a real
# destructive tool is ever added, it belongs here.
#
# Tools not listed anywhere below fall through get_risk_level()'s own "low"
# default -- correct for the 16 real read-only/"view"-capability tools
# (services/rbac.py's TOOL_CAPABILITIES is the authoritative read/write split).
# Every tool that causes a real state change is listed explicitly in "medium"
# below so ASSISTED mode's approval gate (medium+high require approval) isn't
# silently skipping real mutations just because a tool was never added here.
RISK_ACTIONS = {
    "high": [],
    "medium": [
        "register_data_source", "profile_schema", "ingest_file", "sync_source",
        "create_quality_rule", "run_quality_checks", "validate_business_rule",
        "create_pipeline", "run_pipeline", "pause_pipeline", "set_pipeline_schedule",
        "backfill_pipeline", "triage_incident", "resolve_incident",
        "create_data_contract", "validate_data_contract", "send_alert",
        "execute_sql_transform", "run_python_transform",
    ],
    "low": [
        "list_data_sources", "preview_source_data", "detect_schema_drift",
        "generate_sql_transform", "get_quality_report", "list_business_rules",
        "get_pipeline_run_history",
        "check_freshness", "detect_anomalies", "list_open_incidents",
        "get_system_health", "get_lineage", "get_audit_trail", "request_approval",
        "generate_status_report", "generate_incident_report", "get_kpi_summary",
        "get_cicd_status", "standardize_dataset", "export_dataset",
    ],
}

def build_system_prompt(personality: PersonalityMode, operation: OperationMode) -> str:
    base = SYSTEM_PROMPTS.get(personality, SYSTEM_PROMPTS[PersonalityMode.ENGINEER])
    op_ctx = OPERATION_MODE_CONTEXT.get(operation, "")
    return f"{base}\n\n{op_ctx}"

def get_risk_level(action: str) -> str:
    for level, actions in RISK_ACTIONS.items():
        if action in actions:
            return level
    return "low"

def requires_approval(action: str, operation_mode: OperationMode) -> bool:
    risk = get_risk_level(action)
    if operation_mode == OperationMode.ADVISORY: return True
    if operation_mode == OperationMode.ASSISTED:  return risk in ("high", "medium")
    if operation_mode == OperationMode.AUTONOMOUS: return risk == "high"
    if operation_mode == OperationMode.AUDIT:      return True
    return False
