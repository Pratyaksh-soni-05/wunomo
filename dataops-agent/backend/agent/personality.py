from models.all_models import AgentEmployeeType, PersonalityMode, OperationMode

# Which employee TYPE the agent is (§ "Add Analyst as a second employee
# type") -- orthogonal to PersonalityMode below (a tone/communication-style
# dial every employee type shares) and to OperationMode (an autonomy dial).
# A dict, not a template system: one complete identity statement per type,
# composed in front of the personality tone text in build_system_prompt(),
# never cross-multiplied against it.
#
# DATAOPS's entry exists so an Analyst-type agent using ENGINEER
# personality can't end up contradicting itself (SYSTEM_PROMPTS[ENGINEER]
# used to open with "an AI DataOps Engineer" unconditionally, baked in
# from when DATAOPS was the only employee type that could ever exist --
# harmless then, a real self-contradiction the moment a second type could
# select ENGINEER tone too). That claim moved here instead; ENGINEER's own
# entry below no longer makes an employee-type claim of its own.
EMPLOYEE_TYPE_IDENTITY: dict[AgentEmployeeType, str] = {
    AgentEmployeeType.DATAOPS: (
        "You are {agent_name}, an AI DataOps Engineer. You automate data pipelines, monitor "
        "data quality, diagnose pipeline failures, and manage the tenant's data infrastructure "
        "-- connecting sources, building and running pipelines, and making real changes to the "
        "data stack when asked."
    ),
    AgentEmployeeType.ANALYST: (
        "You are {agent_name}, an AI Business Analyst. You answer business questions using the "
        "tenant's existing data and explain your reasoning clearly. You read and analyse data "
        "quality, pipeline health, incidents, and reports -- you do not connect new sources, "
        "write transformations, or build or modify pipelines. If a question needs one of those, "
        "say so plainly and name who can do it, rather than attempting it yourself."
    ),
}

# {agent_name} is substituted by build_system_prompt() - was a hardcoded
# literal "AXIOM" in all four variants until Wunomo Projects Phase 0
# (commit 4). Every named agent instance shares these same four
# personality templates; only the introduced name differs. AXIOM itself
# is not special-cased - it's just the name every existing tenant's
# backfilled agent happens to have (see the backfill migration).
SYSTEM_PROMPTS = {
    PersonalityMode.ENGINEER: (
        "Operate with the precision of a senior engineer. Include: pipeline states, SQL logic, "
        "schema diagnostics, root-cause analysis, dependency chains, run history, and specific "
        "remediation steps. Cite exact table names, column counts, row volumes, and error codes. "
        "Be direct and efficient."
    ),
    PersonalityMode.FOUNDER: (
        "You are {agent_name} briefing a founder. Summarize in plain business terms. Lead with: "
        "What broke? What is affected? ETA to fix? What was saved? Keep to 3-5 bullets."
    ),
    PersonalityMode.ANALYST: (
        "You are {agent_name} assisting a business analyst. Focus on dataset readiness, KPI accuracy, "
        "freshness status, and reporting context. Explain what data is available, stale, or failing quality."
    ),
    PersonalityMode.AUDITOR: (
        "You are {agent_name} in audit mode. Provide: lineage paths, change history with timestamps, "
        "approval records, validation results, access logs, policy tags, contract compliance. Cite IDs."
    ),
}

# Item 3, blueprint chrome follow-up: found live -- a completed tool's raw
# result (a Python dict repr) was appearing verbatim in the model's own
# final answer ("Result: {'run_id': '82a90154-...', 'pipeline_id': ...}"),
# which then rendered as unreadable text inside §7.3.D's output card. The
# card is supposed to hold a summary; the raw structure belongs exclusively
# behind "Show work" (already real -- ToolCallBlock renders it there).
# Applies to every employee type and every personality tone equally (this
# is a formatting rule, not a communication style), so it's appended once
# in build_system_prompt() below rather than duplicated into all eight
# EMPLOYEE_TYPE_IDENTITY x SYSTEM_PROMPTS combinations.
RESULT_FORMATTING_RULE = (
    "When you report a tool's result, never paste its raw output structure (a Python dict, JSON, "
    "or similar) into your answer. State the relevant facts in plain language instead -- exact IDs, "
    "counts, and names are still welcome, just written as prose, not as a data structure. The tool's "
    "raw output is already shown to the user separately, under \"Show work\"."
)

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
        # detect_schema_drift sat in "low" until Item #7, on the strength of its
        # name. Measured: when drift exists it rewrites schema_snapshot AND
        # advances last_profiled_at, then commits — the same two columns
        # profile_schema/sync_source write, and last_profiled_at is what the
        # freshness sweep reads. A "detect" that resets staleness tracking is
        # a write, and belongs with the tools that do the same write.
        "register_data_source", "profile_schema", "ingest_file", "sync_source",
        "detect_schema_drift",
        "create_quality_rule", "run_quality_checks", "validate_business_rule",
        "create_pipeline", "run_pipeline", "pause_pipeline", "set_pipeline_schedule",
        "backfill_pipeline", "triage_incident", "resolve_incident",
        "create_data_contract", "validate_data_contract", "send_alert",
        "execute_sql_transform", "run_python_transform",
    ],
    "low": [
        "list_data_sources", "list_pipelines", "preview_source_data",
        "generate_sql_transform", "get_quality_report", "list_business_rules",
        "get_pipeline_run_history",
        "check_freshness", "detect_anomalies", "list_open_incidents",
        "get_system_health", "get_lineage", "get_audit_trail", "request_approval",
        "generate_status_report", "generate_incident_report", "get_kpi_summary",
        "get_cicd_status", "standardize_dataset", "export_dataset",
    ],
}

def build_system_prompt(
    personality: PersonalityMode, operation: OperationMode, agent_name: str = "AXIOM",
    employee_type: AgentEmployeeType = AgentEmployeeType.DATAOPS,
) -> str:
    """agent_name defaults to "AXIOM" so every existing caller keeps
    working unchanged until Wunomo Projects Phase 0's commit 5 threads a
    real agent's own name through from build_agent(). employee_type
    defaults to DATAOPS for the exact same reason -- every caller that
    predates a second employee type existing gets the identical resolved
    prompt it always has.

    Composed as identity (who this employee type IS) -> tone (how
    personality_mode wants it communicated) -> operation_mode context --
    three independent dials, not one matrix keyed by their combination."""
    identity = EMPLOYEE_TYPE_IDENTITY.get(
        employee_type, EMPLOYEE_TYPE_IDENTITY[AgentEmployeeType.DATAOPS],
    ).format(agent_name=agent_name)
    tone = SYSTEM_PROMPTS.get(personality, SYSTEM_PROMPTS[PersonalityMode.ENGINEER]).format(agent_name=agent_name)
    op_ctx = OPERATION_MODE_CONTEXT.get(operation, "")
    return f"{identity}\n\n{tone}\n\n{op_ctx}\n\n{RESULT_FORMATTING_RULE}"

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
