"""Wunomo Projects Phase 1: intersection permission enforcement.

Effective permission = has_permission(user.role, capability) AND resolved
entity within agent_sources for the calling agent. Both required, every
call; an agent can only narrow what its caller may do, never widen it.
See CLAUDE.md's "plan-time scope checking is a cost optimisation, not a
security boundary" note -- everything in this module is the REAL,
post-resolution enforcement half of that split (consulted by agent_node
and task_executor.py); task_planner.py's own use of this module's
resolution table is the cost-optimisation half, and must never be
mistaken for the boundary itself.

Fail-closed (confirmed decision, 2026-09-03): an agent with zero
agent_sources rows is scoped to nothing, not everything. Every agent
instance that existed when this was decided was backfilled with its
tenant's current sources in 480d5b8245f3_backfill_agent_sources_for_
existing_agents.py, specifically so this doesn't regress AXIOM's
existing behavior. A newly hired agent (Phase 1's hiring, not built yet)
starting with zero scope is correct, not a bug -- a just-created agent
should be able to touch nothing until explicitly assigned sources.

New sources are deliberately NOT auto-granted to any agent, including
AXIOM, going forward -- see GOTCHAS.md. Silent scope auto-expansion
defeats the point of a scope boundary as surely as no scope at all does.
The practical consequence: a source connected after an agent already
exists is invisible to that agent until someone assigns it (no such
"assign" surface exists yet -- Phase 1's hiring/scope-management UI is
what will add one). agent_scope_denial_reason()'s message is written to
make that state legible rather than read as a mysterious permission
error.
"""
from sqlalchemy import select

from models.all_models import AgentInstance, AgentSource, DataContract, DataSource, Incident, Pipeline

# Sentinel: this tool doesn't touch one specific, scopeable data source --
# either it's read-only/tenant-wide (list_data_sources, get_system_health),
# asset-name-based rather than source-id-based (get_lineage), or it
# CREATES a new thing rather than touching an existing one
# (register_data_source -- nothing exists yet to be out of scope).
NOT_SOURCE_SCOPED = "not_source_scoped"

# tool_name -> NOT_SOURCE_SCOPED, or a list of (arg_name, resolution_kind)
# candidates to check if present. Most tools have exactly one candidate;
# generate_sql_transform takes source_id OR pipeline_id (both optional) so
# it gets two -- whichever the caller actually supplied gets checked, not
# both required. An arg that's absent, empty, or a still-unresolved
# placeholder is simply skipped (nothing to check yet), not denied -- see
# agent_scope_denial_reason's own docstring for why that's correct here
# specifically (a real id always exists by the time this module's callers
# invoke it) and wrong in task_planner.py (where a placeholder is normal).
#
# resolution_kind:
#   "source"   -- the arg IS a source_id already.
#   "pipeline" -- resolve via Pipeline.source_id.
#   "incident" -- resolve via Incident.pipeline_id -> Pipeline.source_id
#                 (two hops; either can be NULL -- see _resolve_source_id).
#   "contract" -- resolve via DataContract.producer_source_id.
#
# Exhaustive by construction, fail-closed at import time -- every real
# tool must be explicitly classified, matching the existing
# TOOL_CAPABILITIES/TASK_SHAPE_ALLOWED_TOOLS assertion pattern in this
# codebase (agent/dataops_agent.py, modules/orchestration/task_planner.py).
TOOL_SCOPE_RESOLUTION: dict[str, list] = {
    # Ingestion
    "list_data_sources": NOT_SOURCE_SCOPED,
    "register_data_source": NOT_SOURCE_SCOPED,
    "profile_schema": [("source_id", "source")],
    "ingest_file": [("pipeline_id", "pipeline")],
    "sync_source": [("source_id", "source")],
    "preview_source_data": [("source_id", "source")],
    "detect_schema_drift": [("source_id", "source")],

    # Transformation
    "generate_sql_transform": [("source_id", "source"), ("pipeline_id", "pipeline")],
    "execute_sql_transform": [("source_id", "source")],
    "run_python_transform": [("source_id", "source")],
    "standardize_dataset": [("source_id", "source")],

    # Quality
    "run_quality_checks": [("pipeline_id", "pipeline")],
    "create_quality_rule": [("pipeline_id", "pipeline")],
    "get_quality_report": [("pipeline_id", "pipeline")],
    "validate_business_rule": [("pipeline_id", "pipeline")],
    "list_business_rules": [("pipeline_id", "pipeline")],

    # Orchestration
    "list_pipelines": NOT_SOURCE_SCOPED,
    "create_pipeline": [("source_id", "source")],
    "run_pipeline": [("pipeline_id", "pipeline")],
    "pause_pipeline": [("pipeline_id", "pipeline")],
    "get_pipeline_run_history": [("pipeline_id", "pipeline")],
    "backfill_pipeline": [("pipeline_id", "pipeline")],
    "set_pipeline_schedule": [("pipeline_id", "pipeline")],

    # Observability
    "check_freshness": [("source_id", "source")],
    "detect_anomalies": [("pipeline_id", "pipeline")],
    "list_open_incidents": NOT_SOURCE_SCOPED,
    "triage_incident": [("incident_id", "incident")],
    "resolve_incident": [("incident_id", "incident")],
    "get_system_health": NOT_SOURCE_SCOPED,

    # Governance
    "get_lineage": NOT_SOURCE_SCOPED,
    "get_audit_trail": NOT_SOURCE_SCOPED,
    "create_data_contract": [("producer_source_id", "source")],
    "validate_data_contract": [("contract_id", "contract")],
    "request_approval": NOT_SOURCE_SCOPED,

    # Reporting
    "generate_status_report": NOT_SOURCE_SCOPED,
    "generate_incident_report": [("incident_id", "incident")],
    "send_alert": NOT_SOURCE_SCOPED,
    "export_dataset": [("pipeline_id", "pipeline")],
    "get_kpi_summary": NOT_SOURCE_SCOPED,

    # CI/CD
    "get_cicd_status": NOT_SOURCE_SCOPED,
}


def _validate_tool_scope_map_at_import_time() -> None:
    """Fail-closed at boot, same pattern as dataops_agent.py's
    TOOL_CAPABILITIES assertion and task_planner.py's allowlist
    assertion -- a newly-added tool with no entry here must crash the
    process, not silently go unresolved (and therefore unscopeable) for
    every agent forever."""
    from agent.tools import ALL_TOOLS
    real_tool_names = {t.name for t in ALL_TOOLS}
    mapped = set(TOOL_SCOPE_RESOLUTION)
    unmapped = real_tool_names - mapped
    assert not unmapped, (
        f"Tool(s) missing a TOOL_SCOPE_RESOLUTION entry in services/agent_scope.py: "
        f"{sorted(unmapped)} -- every registered tool must be explicitly classified as "
        "NOT_SOURCE_SCOPED or given a real resolution path."
    )
    unknown = mapped - real_tool_names
    assert not unknown, f"TOOL_SCOPE_RESOLUTION references non-existent tool(s): {sorted(unknown)}"


_validate_tool_scope_map_at_import_time()


async def _resolve_source_id(db, kind: str, value: str) -> str | None:
    """Resolves any of this module's scopeable id kinds down to the real
    data_sources.id it ultimately touches. Returns None both when the
    referenced row doesn't exist and when it genuinely has no owning
    source (e.g. an incident with pipeline_id=NULL, or a pipeline with
    source_id=NULL -- both real, nullable columns) -- either way there is
    nothing to check scope against, which agent_scope_denial_reason
    treats as "allowed," not "denied." A nonexistent id is deliberately
    NOT a scope denial for any kind, "source" included: a bogus/already-
    deleted id is a domain error the tool itself will surface (e.g.
    "Source not found"), not something the scope gate should intercept
    and mislabel as a permission problem."""
    if kind == "source":
        source = await db.get(DataSource, value)
        return source.id if source else None
    if kind == "pipeline":
        pipeline = await db.get(Pipeline, value)
        return pipeline.source_id if pipeline else None
    if kind == "incident":
        incident = await db.get(Incident, value)
        if incident is None or incident.pipeline_id is None:
            return None
        pipeline = await db.get(Pipeline, incident.pipeline_id)
        return pipeline.source_id if pipeline else None
    if kind == "contract":
        contract = await db.get(DataContract, value)
        return contract.producer_source_id if contract else None
    return None


async def agent_touches_source(db, agent_id: str, source_id: str) -> bool:
    """Fresh, uncached per-call DB read -- an agent's scope can change
    mid-task the same way a user's role can (Phase 1's own rule, per
    CLAUDE.md), so this must never be memoized the way get_agent()'s
    built LLM object is."""
    r = await db.execute(
        select(AgentSource.id).where(AgentSource.agent_id == agent_id, AgentSource.source_id == source_id)
    )
    return r.first() is not None


async def agent_scope_denial_reason(db, agent_id: str | None, tool_name: str, args: dict) -> str | None:
    """Returns a legible, specific denial reason if `args` names a
    resolved source outside `agent_id`'s scope, else None (allowed).

    agent_id=None is a transitional no-op (skip, never deny): every real
    chat/task caller resolves the tenant's real agent_id before reaching
    here (see run_agent()/create_task()), but nothing in this function
    requires it -- an absent agent_id means there's no agent context to
    intersect against, so this check simply doesn't apply. Role
    enforcement (has_permission) is unaffected and keeps governing on
    its own, unchanged, exactly as it did before this module existed.

    Only ever checks a candidate arg that's present with a real value AND
    resolves to a real, existing source -- an absent/empty arg, an
    unresolved placeholder, or a genuinely sourceless entity has nothing
    to check and is treated as allowed here. That's correct at this
    module's real call sites (agent_node, task_executor immediately
    before _call_tool()), where a step's args are, by construction,
    already fully resolved to real values by the time this runs."""
    if agent_id is None:
        return None
    resolution = TOOL_SCOPE_RESOLUTION.get(tool_name)
    if resolution is None or resolution == NOT_SOURCE_SCOPED:
        return None

    for arg_name, kind in resolution:
        value = args.get(arg_name)
        if not value or not isinstance(value, str):
            continue
        source_id = await _resolve_source_id(db, kind, value)
        if source_id is None:
            continue
        if await agent_touches_source(db, agent_id, source_id):
            continue
        agent = await db.get(AgentInstance, agent_id)
        source = await db.get(DataSource, source_id)
        agent_name = agent.name if agent else agent_id
        source_name = source.name if source else source_id
        return (
            f"'{agent_name}' isn't scoped to access '{source_name}' — this source hasn't "
            f"been assigned to this agent, so '{tool_name}' can't run against it. An Owner "
            f"or Admin can grant it: POST /api/v1/agents/{agent_id}/sources/{source_id}."
        )
    return None
