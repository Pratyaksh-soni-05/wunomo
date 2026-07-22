"""Locked role set (Phase 15).

Roles are plain lowercase strings stored on `User.role` (String(50), no DB
enum) — matches this codebase's existing convention for role/severity-style
fields (see `QualityRule.severity`). The only value ever written before this
phase was "owner" (every account is created as its tenant's owner via
`create_new_tenant_and_user()`), so introducing the other four here is a new
capability, not a migration of existing data — every existing row is already
a valid value under this set.
"""
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DATA_ENGINEER = "data_engineer"
    DATA_ANALYST = "data_analyst"
    VIEWER = "viewer"


ALL_ROLES = tuple(r.value for r in Role)


# ---------------------------------------------------------------------------
# Unified capability map (Phase 19) — the single source of truth for "who
# can do what," consulted by BOTH the REST layer (require_permission(), see
# api/v1/auth.py) and the AXIOM agent tool-dispatch gate (agent_node, see
# agent/dataops_agent.py). Before this, each REST endpoint hand-picked its
# own require_role(...) tuple ad hoc (most picked none at all), and the
# agent tool-calling path had no role enforcement whatsoever — only
# operation_mode + a hardcoded risk tier gated it, completely independent of
# who was actually asking. This map is what closes both gaps with one
# definition instead of two rulebooks that can silently drift apart.
#
# Keys are "<resource>.<action>" strings. A capability with no entry here is
# denied for every role (fail-closed) — see TOOL_CAPABILITIES's own
# enumeration test and the startup assertion in agent/dataops_agent.py for
# the mechanism that makes "no entry = something forgot to be mapped" loud
# instead of silent.
_ALL = frozenset(Role)
_MANAGERS = frozenset({Role.OWNER, Role.ADMIN})
_BUILDERS = frozenset({Role.OWNER, Role.ADMIN, Role.DATA_ENGINEER})
_OPERATORS = frozenset({Role.OWNER, Role.ADMIN, Role.DATA_ENGINEER, Role.DATA_ANALYST})

PERMISSIONS: dict[str, frozenset[Role]] = {
    # Read-only — every role, including Viewer. Used by the agent tool gate
    # for the read-only AXIOM tools; REST reads are already open to any
    # authenticated tenant member and don't need a separate check.
    "view": _ALL,

    "sources.create": _BUILDERS,
    "sources.profile": _OPERATORS,  # sync/profile; Catalog's Sync Metadata fans out to this
    "sources.delete": _BUILDERS,

    "pipelines.create": _BUILDERS,
    "pipelines.operate": _OPERATORS,  # trigger/pause/activate
    "pipelines.delete": _BUILDERS,

    "quality.manage": _OPERATORS,  # create/edit/run
    "quality.delete": _BUILDERS,

    "transforms.generate": _ALL,  # generate/dry-run/preview/explain — sandboxed, non-persisting
    "transforms.execute": _OPERATORS,  # real run/sql, run/pandas — confirmed read-constrained

    "incidents.log": _ALL,
    "incidents.resolve": _OPERATORS,

    "contracts.create": _OPERATORS,
    "contracts.validate": _OPERATORS,

    "approvals.manage": _MANAGERS,  # approve/reject general agent-action requests
    "cicd.approve": _MANAGERS,  # approve/reject CI/CD deployment commits
    "cicd.incidents.resolve": _MANAGERS,

    "team.manage": _MANAGERS,  # invite/role-change/remove
    "settings.manage": _MANAGERS,
    "api_keys.manage": _MANAGERS,
    "billing.manage": _MANAGERS,
}


def has_permission(role: str, capability: str) -> bool:
    """Pure in-memory lookup, no I/O — safe to call once per capability
    check without re-fetching anything. An unmapped capability is denied
    for every role (fail-closed)."""
    try:
        role_enum = Role(role)
    except ValueError:
        return False
    return role_enum in PERMISSIONS.get(capability, frozenset())


# ---------------------------------------------------------------------------
# Maps every real AXIOM tool (agent/tools/*.py, agent.tools.ALL_TOOLS) to the
# PERMISSIONS capability it exercises — read by agent_node's tool-dispatch
# gate (agent/dataops_agent.py) before a tool call is allowed through to
# ToolNode, evaluated before and independently of the operation_mode/risk-
# tier approval gate. Fail-closed: a tool with no entry here is denied for
# every role (see the startup assertion + enumeration test in
# agent/dataops_agent.py, which checks this dict covers every tool in
# ALL_TOOLS — the old approach of tools simply never being checked at all is
# what let AXIOM's tool-calling bypass role enforcement entirely; leaving a
# newly-added tool unmapped now fails loudly at boot instead of silently
# defaulting to "no check").
#
# The 12 read-only tools below map to "view" (granted to every role,
# including Viewer, so Viewer chat stays useful rather than refusing
# everything) per the explicit, exhaustive list this was designed against.
# Tools not on that list but which are also read-only/diagnostic in nature
# (check_freshness, detect_anomalies) were deliberately mapped to a real
# operational tier instead of assumed onto "view" — conservative by design,
# since under-granting a diagnostic tool is a smaller error than silently
# widening the explicit view list. request_approval is mapped to "view"
# specifically (not a new capability) because requesting approval for an
# action is itself safe regardless of role — it only ever creates a pending
# record for a human to review, never executes anything, and denying it to
# low-privilege roles would leave them with no path to get anything done via
# chat beyond pure reading.
TOOL_CAPABILITIES: dict[str, str] = {
    # Ingestion
    "list_data_sources": "view",
    "register_data_source": "sources.create",
    "profile_schema": "sources.profile",
    "ingest_file": "sources.profile",
    "sync_source": "sources.profile",
    "preview_source_data": "view",
    "detect_schema_drift": "view",

    # Transformation
    "generate_sql_transform": "transforms.generate",
    "execute_sql_transform": "transforms.execute",
    "run_python_transform": "transforms.execute",
    "standardize_dataset": "transforms.execute",

    # Quality
    "run_quality_checks": "quality.manage",
    "create_quality_rule": "quality.manage",
    "get_quality_report": "view",
    "validate_business_rule": "quality.manage",
    "list_business_rules": "view",

    # Orchestration
    "create_pipeline": "pipelines.create",
    "run_pipeline": "pipelines.operate",
    "pause_pipeline": "pipelines.operate",
    "get_pipeline_run_history": "view",
    "backfill_pipeline": "pipelines.operate",
    "set_pipeline_schedule": "pipelines.create",

    # Observability
    "check_freshness": "sources.profile",
    "detect_anomalies": "pipelines.operate",
    "list_open_incidents": "view",
    "triage_incident": "incidents.resolve",
    "resolve_incident": "incidents.resolve",
    "get_system_health": "view",

    # Governance
    "get_lineage": "view",
    "get_audit_trail": "view",
    "create_data_contract": "contracts.create",
    "validate_data_contract": "contracts.validate",
    "request_approval": "view",

    # Reporting
    "generate_status_report": "view",
    "generate_incident_report": "view",
    "send_alert": "incidents.resolve",
    "export_dataset": "view",  # always returns a "not implemented" error — harmless either way
    "get_kpi_summary": "view",

    # CI/CD
    "get_cicd_status": "view",
}
