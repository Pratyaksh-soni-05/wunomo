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

RISK_ACTIONS = {
    "high":   ["delete_records", "drop_table", "modify_schema", "revoke_access"],
    "medium": ["rerun_pipeline", "modify_business_rule", "update_contract", "publish_output", "backfill_pipeline"],
    "low":    ["run_quality_check", "profile_schema", "generate_report", "list_sources", "get_lineage"],
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
