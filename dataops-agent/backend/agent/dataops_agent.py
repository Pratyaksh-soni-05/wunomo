from __future__ import annotations
from typing import TypedDict, Annotated, Sequence
import operator, json
from datetime import datetime, timezone

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from agent.personality import build_system_prompt, requires_approval, get_risk_level
from agent.tools import ALL_TOOLS
from services.llm_service import get_llm_for_agent, invoke_llm, log_llm_usage, content_as_text
from services.rbac import has_permission, TOOL_CAPABILITIES
from services import prompt_guard
from models.all_models import PersonalityMode, OperationMode, AgentEmployeeType
import structlog

log = structlog.get_logger()

# Fail-closed, checked at import time (not lazily on first call): every real
# tool AXIOM can call must have a TOOL_CAPABILITIES entry, or it's silently
# denied for every role forever — better to crash the process at boot than
# let a newly-added tool go unmapped and undiscovered. This is the mechanism
# that makes "gating was opt-in" (the root cause of the original bypass)
# structurally impossible to repeat. This checks the UNION (every tool that
# exists anywhere is mapped) and stays exactly this shape under Wunomo
# Projects Phase 0 — it was never a "one agent" assumption to begin with.
_unmapped_tools = sorted(set(t.name for t in ALL_TOOLS) - set(TOOL_CAPABILITIES))
assert not _unmapped_tools, (
    f"Tool(s) missing a TOOL_CAPABILITIES entry in services/rbac.py: {_unmapped_tools} "
    "— every registered AXIOM tool must be mapped or it's unreachable for every role."
)

# Per-instance tool SUBSETS (Wunomo Projects Phase 0, commit 5) are keyed by
# employee_type, not stored per agent row. This is deliberately a
# static, code-level mapping (mirroring task_planner.py's
# TASK_SHAPE_ALLOWED_TOOLS) rather than new per-instance schema — no
# agent_sources-equivalent "which tools" table was approved this pass.
# Extend _employee_type_tools(), not build_agent()'s own logic, the day a
# further employee type ships with a genuinely different toolset.
#
# ANALYST's subset ("Add Analyst as a second employee type"): every tool
# whose services/rbac.py TOOL_CAPABILITIES entry grants access to _ALL
# roles, including Viewer -- the same, already-reviewed line RBAC itself
# draws between "safe for anyone to call" and "needs an operational
# role." Two capabilities clear that bar with real tool consumers: "view"
# (17 tools) and "transforms.generate" (generate_sql_transform alone --
# its own RBAC comment already calls it "sandboxed, non-persisting", a
# preview/explain, never a real write). Nothing gated behind
# sources.create/profile, pipelines.*, quality.manage, transforms.execute,
# incidents.resolve, or contracts.* is in this set: the Analyst reads and
# explains, it doesn't connect a source, persist a transform, or touch a
# pipeline. Deliberately excludes diagnostic-sounding but elevated tools
# too (check_freshness, detect_anomalies) -- RBAC's own comment already
# treats under-granting those as the safer error, a judgment this
# inherits rather than re-litigates. request_approval is included for
# consistency with "every _ALL-tier tool" even though the Analyst has no
# risky action of its own to request approval for -- harmless, and
# unlikely to ever actually fire.
_ANALYST_TOOL_NAMES = frozenset({
    "list_data_sources", "preview_source_data", "detect_schema_drift",
    "generate_sql_transform",
    "get_quality_report", "list_business_rules",
    "list_pipelines", "get_pipeline_run_history",
    "list_open_incidents", "get_system_health",
    "get_lineage", "get_audit_trail", "request_approval",
    "generate_status_report", "generate_incident_report", "export_dataset", "get_kpi_summary",
    "get_cicd_status",
})


# A FUNCTION, not a plain module-level dict — deliberately re-evaluated on
# every call rather than built once at import time. A bare
# `{AgentEmployeeType.DATAOPS: ALL_TOOLS}` dict literal captures whatever
# object ALL_TOOLS pointed to at import time by reference; every test in
# this suite that does `monkeypatch.setattr(dataops_agent, "ALL_TOOLS",
# [fake_tool])` — the established pattern for testing tool-dispatch
# without a real LLM/tool registry — would then silently have NO effect
# once agent_id flows through run_agent(), because the captured reference
# never changes. This bug existed from the moment commit 5 shipped but
# was invisible until Phase 1 made api/v1/chat.py actually resolve and
# pass a real agent_id on every request — no real caller exercised the
# `agent_id is not None` branch before that, so nothing ever hit it. See
# GOTCHAS.md. Same reasoning is why ANALYST's list is filtered from
# ALL_TOOLS by name on every call rather than imported/listed as its own
# fixed module-level list of tool objects.
def _employee_type_tools() -> dict[AgentEmployeeType, list]:
    return {
        AgentEmployeeType.DATAOPS: ALL_TOOLS,
        AgentEmployeeType.ANALYST: [t for t in ALL_TOOLS if t.name in _ANALYST_TOOL_NAMES],
    }


def _validate_employee_type_tools_at_import_time() -> None:
    """Same fail-closed-at-boot shape as the union assertion above and as
    task_planner.py's _validate_allowlist_at_import_time() — every tool
    named in any employee type's subset must be a real, registered tool
    with a real TOOL_CAPABILITIES entry. Close to tautological for
    DATAOPS today (its subset literally *is* ALL_TOOLS), but this is the
    check that keeps mattering once a second employee type gets a
    hand-curated, non-full subset."""
    real_tool_names = {t.name for t in ALL_TOOLS}
    for employee_type, tools in _employee_type_tools().items():
        names = {t.name for t in tools}
        unknown = names - real_tool_names
        assert not unknown, f"EMPLOYEE_TYPE_TOOLS['{employee_type.value}'] references non-existent tool(s): {unknown}"
        unmapped = names - set(TOOL_CAPABILITIES)
        assert not unmapped, (
            f"EMPLOYEE_TYPE_TOOLS['{employee_type.value}'] references tool(s) with no "
            f"TOOL_CAPABILITIES entry: {unmapped}"
        )


_validate_employee_type_tools_at_import_time()


def role_denied_tool_calls(caller_role: str, tool_calls: list[dict]) -> list[dict]:
    """The agent-side half of the unified permission gate — mirrors
    require_permission() on the REST side, reading the exact same
    services/rbac.py map so REST and chat can never silently drift onto two
    different rulebooks. Mutates `tool_calls` in place to remove any call
    the caller's role isn't permitted to make (so they never reach ToolNode
    and never execute), and returns the removed calls, each tagged with a
    human-readable reason, for the caller to surface back to the user.
    Fail-closed: a tool with no TOOL_CAPABILITIES entry is denied for every
    role (though the startup assertion above should make that state
    unreachable in practice). Deliberately a standalone function, not
    embedded in agent_node's closure, so it can be unit-tested directly with
    a synthetic role and a plain list of tool-call dicts — no LLM, no graph,
    no real AXIOM conversation required."""
    denied = []
    kept = []
    for call in tool_calls:
        capability = TOOL_CAPABILITIES.get(call["name"])
        if capability is None or not has_permission(caller_role, capability):
            denied.append({
                **call,
                "reason": f"Your role does not have permission to use '{call['name']}'.",
            })
        else:
            kept.append(call)
    tool_calls[:] = kept
    return denied


async def agent_scope_denied_tool_calls(agent_id: str | None, tool_calls: list[dict]) -> list[dict]:
    """The scope half of the unified permission gate (Wunomo Projects
    Phase 1) — runs ALONGSIDE role_denied_tool_calls(), never instead of
    it: effective permission = has_permission(role, capability) AND
    resolved entity in agent_sources, both required (see CLAUDE.md's
    intersection-permission rule). Same mutate-in-place-and-return-
    denied-list shape as role_denied_tool_calls(), extended to be async
    because a real scope check needs a DB read (agent_sources, plus
    resolving a pipeline/incident/contract id back to the source it
    ultimately touches — see services/agent_scope.py) that a pure
    in-memory role lookup never did.

    agent_id=None is a transitional no-op: every real chat caller
    resolves the tenant's real agent_id before reaching here (see
    run_agent()), but nothing here requires it — an absent agent_id
    means there's no agent context to intersect against, so this gate
    simply doesn't apply and role alone keeps governing, unchanged.
    Deliberately a standalone function, not embedded in agent_node's
    closure, matching role_denied_tool_calls' own reasoning — directly
    unit-testable with a synthetic agent_id and a plain list of
    tool-call dicts."""
    from database import AsyncSessionLocal
    from services.agent_scope import agent_scope_denial_reason

    if agent_id is None:
        return []

    denied = []
    kept = []
    async with AsyncSessionLocal() as db:
        for call in tool_calls:
            reason = await agent_scope_denial_reason(db, agent_id, call["name"], call.get("args", {}))
            if reason is not None:
                # "reason" stays a bare string for the existing response_text
                # fallback below (unchanged); "scope_denial" carries the full
                # structured dict for chat.py's trace builder to turn into a
                # real, pre-scoped "grant access" UI action.
                denied.append({**call, "reason": reason["message"], "scope_denial": reason})
            else:
                kept.append(call)
    tool_calls[:] = kept
    return denied

# langchain-google-genai 3.2.0 (see CLAUDE.md Gotchas) consistently returns
# dict/list-typed tool arguments as JSON-encoded strings rather than native
# Python objects, even though: (a) the tool's own schema correctly declares
# them as "object"/"array" (confirmed via register_data_source.args), and
# (b) the raw Gemini API itself returns a real nested object for the same
# call (confirmed via a direct httpx call bypassing langchain entirely) —
# the stringification happens somewhere in langchain_google_genai's own
# function-call parsing pipeline, not in our schemas or Gemini's model
# behavior. Reproduced deterministically across multiple prompts, including
# ones with an explicit, unambiguous target value. Groq never showed this.


def _coerce_stringified_object_args(tool_name: str, args: dict) -> None:
    """Mutates `args` in place: any argument the tool's own schema declares
    as object/array that arrived as a JSON string gets parsed back into a
    real dict/list before the underlying Python tool function ever sees it.
    Looks the schema up from the module-level ALL_TOOLS on every call
    (cheap — a few dozen tools) rather than precomputing at import time, so
    tests can monkeypatch dataops_agent.ALL_TOOLS the same way they already
    do for every other agent-graph test. See the comment above for why this
    coercion is needed at all."""
    tool_obj = next((t for t in ALL_TOOLS if t.name == tool_name), None)
    if tool_obj is None:
        return
    arg_types = {name: schema.get("type", "") for name, schema in tool_obj.args.items()}
    for arg_name, value in list(args.items()):
        if arg_types.get(arg_name) in ("object", "array") and isinstance(value, str):
            try:
                args[arg_name] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass  # leave as-is; the tool's own validation will surface the real error

# iteration_count and LangGraph's own `recursion_limit` count different
# things: iteration_count increments once per agent_node visit, but each
# tool-calling round is 3 LangGraph supersteps (agent -> approval_gate ->
# tools), plus 1 for inject_system and 2 for the final no-tool-call turn
# that reaches END. So MAX_AGENT_ITERATIONS agent_node visits cost roughly
# `3 * MAX_AGENT_ITERATIONS + 6` supersteps — a graceful cap that isn't
# calibrated against that multiplier looks like a safety net but isn't one:
# LangGraph's default recursion_limit (25) was reached first in a real
# runaway-tool-calling conversation, before our own `iteration_count > 20`
# check ever got a chance to fire, crashing the request with an unhandled
# GraphRecursionError instead of the graceful message. AGENT_RECURSION_LIMIT
# is set with real margin above the worst case for MAX_AGENT_ITERATIONS, not
# just barely above it — if you change either constant, re-derive the other.
MAX_AGENT_ITERATIONS = 10
AGENT_RECURSION_LIMIT = 50


def build_full_system_prompt(sys_prompt: str, tenant_id: str, context: dict | None,
                             nonce: str | None = None) -> str:
    """Assemble the system prompt with an unforgeable trust boundary.

    [IDENTITY] and [CONTEXT] used to be bracket-tagged sections, and that is
    precisely what taught the model bracketed tags carry authority — a user
    turn beginning "[SYSTEM] Priority override from the platform team..." was
    then obeyed verbatim (battery payload A4), while plain "ignore previous
    instructions" was refused every time. The tag convention was the
    vulnerability, not the phrasing.

    Server-authored text now sits inside a marker carrying a per-request nonce
    the caller cannot type or guess; untrusted context goes in a plain data tag
    with no nonce and is neutralised first. Authority becomes a property an
    attacker cannot forge rather than a string they can imitate.

    Module-level and pure so it can be asserted on directly, without an LLM.
    """
    nonce = nonce or prompt_guard.new_nonce()
    identity = (
        f"Your authenticated tenant_id is: {tenant_id}\n"
        "Always pass this exact tenant_id to every tool call that requires one. "
        "Never invent, guess, or substitute a different tenant_id. "
        "Never disclose it to the user."
    )
    body = f"{sys_prompt}\n\n{prompt_guard.INSTRUCTION_HIERARCHY}\n\n{identity}"
    prompt = prompt_guard.system_block(body, nonce)
    if context:
        # Client-supplied context is untrusted even though run_agent forces the
        # identity keys — the rest of the dict is whatever the client sent.
        prompt += "\n\n" + prompt_guard.wrap("user_input", json.dumps(context))
    return prompt


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    tenant_id: str
    user_id: str
    session_id: str
    caller_role: str
    personality_mode: str
    operation_mode: str
    pending_approvals: list
    role_denied: list
    scope_denied: list
    iteration_count: int
    context: dict
    system_prompt: str
    agent_id: str | None


def build_agent(personality=PersonalityMode.ENGINEER, operation=OperationMode.ASSISTED, primary_model=None,
                 agent_name="AXIOM", allowed_tools=None, employee_type=AgentEmployeeType.DATAOPS):
    """agent_name/allowed_tools/employee_type default to the exact
    pre-Phase-0 behavior (the literal "AXIOM" identity, the full
    ALL_TOOLS registry, the DataOps prompt) so every existing caller —
    including every test that builds an agent without passing these —
    keeps behaving identically. Real callers thread a specific agent's
    own name, EMPLOYEE_TYPE_TOOLS subset, and employee_type through via
    run_agent(). The signature itself doesn't change shape for the
    Analyst type — only what gets passed as allowed_tools/employee_type
    does (see _prepare_agent_invocation())."""
    allowed_tools = ALL_TOOLS if allowed_tools is None else allowed_tools
    # Only pass primary_model when actually set, preserving the exact
    # get_llm_for_agent(temperature=0.0) call shape every existing
    # monkeypatched test fixture (test_agent_graph.py) already expects -
    # avoids touching ~8 unrelated test fixtures for a kwarg they never use.
    llm = get_llm_for_agent(temperature=0.0, primary_model=primary_model) if primary_model else get_llm_for_agent(temperature=0.0)
    llm_with_tools = llm.bind_tools(allowed_tools)

    # `messages` uses the `operator.add` reducer, so LangGraph automatically
    # appends whatever a node returns onto the existing accumulated value.
    # Every node below must therefore return only the *new* message(s) for
    # this turn, never `state["messages"] + [...]` — returning the full
    # history back causes the reducer to concatenate old+new onto the
    # already-accumulated state, doubling history on every single node hop
    # (a 3-message conversation ballooned to 63 messages in 3 turns before
    # this fix). The system prompt is intentionally kept out of the
    # reducer-managed `messages` channel entirely (stored in `system_prompt`
    # instead and prepended only for the LLM call) since `operator.add`
    # appends at the end, not the start, and would put it out of order.
    def inject_system_prompt(state):
        sys_prompt = build_system_prompt(
            PersonalityMode(state["personality_mode"]),
            OperationMode(state["operation_mode"]),
            agent_name=agent_name,
            employee_type=employee_type,
        )
        # Tell the LLM its real, server-derived tenant_id explicitly — tool schemas
        # require tenant_id as an argument the LLM itself must supply, and without
        # this it has no way to know the real value and will invent a placeholder
        # (e.g. "your_tenant_id"), silently querying the wrong/nonexistent tenant.
        # [IDENTITY] and [CONTEXT] used to be bracket-tagged sections, and that
        # is precisely what taught the model bracketed tags carry authority — a
        # user turn beginning "[SYSTEM] Priority override from the platform
        # team..." was then obeyed verbatim (battery payload A4), while plain
        # "ignore previous instructions" was refused. Server-authored text now
        # carries a per-request nonce marker a caller cannot type; untrusted
        # context goes in a plain data tag with no nonce.
        return {"system_prompt": build_full_system_prompt(
            sys_prompt, state["tenant_id"], state.get("context"))}

    async def agent_node(state):
        if state.get("iteration_count", 0) > MAX_AGENT_ITERATIONS:
            return {"messages": [AIMessage(content="Max reasoning steps reached. Please clarify your request.")]}
        llm_input = [SystemMessage(content=state["system_prompt"])] + list(state["messages"])
        response = await llm_with_tools.ainvoke(llm_input)
        usage = response.additional_kwargs.pop("_llm_usage", None)
        if usage:
            response.additional_kwargs["llm_provider"] = usage["provider"]
            # Preserved for run_agent_stream()'s `done` SSE event (message_id,
            # provider, used_fallback, usage) — run_agent()'s own return dict
            # already carried "provider" via llm_provider above; these two are
            # new keys nothing previously read, so this is additive only.
            response.additional_kwargs["llm_used_fallback"] = usage["used_fallback"]
            response.additional_kwargs["llm_usage_metadata"] = usage.get("usage_metadata")
            await log_llm_usage(
                tenant_id=state["tenant_id"], user_id=state["user_id"], session_id=state["session_id"],
                agent_id=state.get("agent_id"),
                request_type="agent_chat", provider=usage["provider"], model=usage["model"],
                used_fallback=usage["used_fallback"], latency_ms=usage["latency_ms"],
                success=usage["success"], usage_metadata=usage.get("usage_metadata"),
            )
        # Defense-in-depth: never trust the LLM's own tenant_id argument, even
        # though it's told the correct value above — force every tool call's
        # tenant_id to the real, server-derived value so a hallucination or a
        # prompt-injected tool result can never redirect a call at another tenant.
        # user_id/session_id get the same treatment for the tools that need them
        # (currently just request_approval) — same reasoning, see the Gotcha on
        # this in CLAUDE.md. task_id is forced to None, not to a real value —
        # AgentState carries no task_id (a chat turn is never part of a task),
        # so a tool like triage_incident that declares task_id must always log
        # task_id=None here rather than whatever the LLM might invent for it;
        # task_executor._call_tool() is the only place a real task_id is ever
        # injected. agent_id (Wunomo Projects Phase 2, item 5) gets the same
        # override for the source-lock-aware tools -- it's the real calling
        # agent's identity, used only to label a lock's holder in a denial
        # message, but an LLM-supplied value here could otherwise let one
        # agent's tool call misattribute a lock to a different agent. Also
        # coerce any dict/list-typed arg that arrived stringified — see
        # _coerce_stringified_object_args' module-level comment.
        for call in (response.tool_calls or []):
            args = call.get("args", {})
            if "tenant_id" in args:
                args["tenant_id"] = state["tenant_id"]
            if "user_id" in args:
                args["user_id"] = state["user_id"]
            if "session_id" in args:
                args["session_id"] = state["session_id"]
            if "task_id" in args:
                args["task_id"] = None
            if "agent_id" in args:
                args["agent_id"] = state.get("agent_id")
            _coerce_stringified_object_args(call["name"], args)

        # Role-permission gate — evaluated before and independently of
        # approval_gate_node's operation_mode/risk-tier check below. A call
        # denied here never reaches approval_gate_node or ToolNode at all;
        # it cannot become approvable later the way a risk-blocked call can,
        # because the caller's role was never allowed to request it in the
        # first place. See role_denied_tool_calls' own docstring.
        denied = role_denied_tool_calls(state["caller_role"], response.tool_calls or [])
        # Scope gate (Wunomo Projects Phase 1) — runs alongside the role
        # gate above, on whatever survives it, not instead of it: both
        # must pass (see agent_scope_denied_tool_calls' own docstring).
        # Mutates the same already-filtered response.tool_calls list.
        scope_denied = await agent_scope_denied_tool_calls(state.get("agent_id"), response.tool_calls or [])

        return {
            "messages": [response],
            "iteration_count": state.get("iteration_count", 0) + 1,
            "role_denied": state.get("role_denied", []) + denied,
            "scope_denied": state.get("scope_denied", []) + scope_denied,
        }

    def approval_gate_node(state):
        last_msg = state["messages"][-1]
        if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
            return {}
        op_mode = OperationMode(state["operation_mode"])
        blocked = [
            {**c, "risk_level": get_risk_level(c["name"]),
             "reason": f"Operation mode '{op_mode.value}' requires approval for this action."}
            for c in last_msg.tool_calls if requires_approval(c["name"], op_mode)
        ]
        if blocked:
            msg = (f"**Approval Required** for {len(blocked)} action(s):\n"
                   + "\n".join(f"- `{c['name']}`" for c in blocked)
                   + "\n\nApprove or reject in the approval center.")
            return {"pending_approvals": state.get("pending_approvals", []) + blocked,
                    "messages": [AIMessage(content=msg)]}
        return {}

    def should_continue(state):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "end" if state.get("pending_approvals") else "tools"
        return "end"

    graph = StateGraph(AgentState)
    graph.add_node("inject_system", inject_system_prompt)
    graph.add_node("agent", agent_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("tools", ToolNode(allowed_tools))
    graph.set_entry_point("inject_system")
    graph.add_edge("inject_system", "agent")
    graph.add_edge("agent", "approval_gate")
    graph.add_conditional_edges("approval_gate", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")
    return graph.compile()


_cache: dict = {}

def get_agent(personality="engineer", operation="assisted", tenant_id=None, primary_model=None,
              agent_id=None, agent_name="AXIOM", allowed_tools=None, config_version=None,
              employee_type=AgentEmployeeType.DATAOPS):
    """Cache key MUST include tenant_id and the resolved primary_model, not
    just personality/operation - see CLAUDE.md's get_agent() Gotcha
    (Phase 0's approved pushback #2). The cached value is a fully-built
    agent with a specific LLM already bound in; two tenants with different
    model overrides sharing a cache key would leak one tenant's model
    choice into another tenant's requests. tenant_id is required (not
    defaulted) so this can never silently regress back to the old
    personality:operation-only key by a caller forgetting to pass it.

    Wunomo Projects Phase 0 (commit 5) folds agent_id and config_version
    into the key too. config_version is a real agent row's updated_at
    (isoformat), not a separately-maintained counter - editing any field
    on that row bumps updated_at automatically (see AgentInstance's own
    docstring), which changes this key, which means a stale cached agent
    object can never be served after an edit. Invalidation by
    construction, not by a call site remembering to bust the cache.
    Every existing caller that doesn't pass these four new kwargs gets the
    exact pre-Phase-0 key shape and behavior, unchanged.

    employee_type isn't folded into the key separately: it's immutable in
    practice for a given agent_id (fixed at hire time), and any edit that
    ever did change it would bump config_version anyway, which is already
    in the key — the same invalidation-by-construction argument as
    config_version's own paragraph above."""
    if tenant_id is None:
        raise ValueError("get_agent() requires tenant_id - see the cache re-keying Gotcha in CLAUDE.md")
    key = f"{tenant_id}:{agent_id or 'default'}:{personality}:{operation}:{primary_model or 'default'}:{config_version or ''}"
    if key not in _cache:
        _cache[key] = build_agent(
            PersonalityMode(personality), OperationMode(operation), primary_model=primary_model,
            agent_name=agent_name, allowed_tools=allowed_tools, employee_type=employee_type,
        )
    return _cache[key]


async def _prepare_agent_invocation(user_message, tenant_id, user_id, session_id, caller_role,
                                    personality_mode, operation_mode, history, context, agent_id):
    """Shared setup for run_agent() and run_agent_stream() — resolves the
    real agent config (row-level overrides win over request body/tenant
    override, see run_agent()'s own docstring below), fetches/builds the
    compiled graph via get_agent() (same cache, unchanged), and builds the
    exact AgentState input dict both .ainvoke() and .astream_events()
    consume identically. Extracted verbatim from run_agent() — no
    behavior change, just a named seam so the streaming sibling doesn't
    duplicate it."""
    from services.settings_service import get_ai_model_override

    agent_name = "AXIOM"
    allowed_tools = None
    config_version = None
    employee_type = AgentEmployeeType.DATAOPS
    if agent_id is not None:
        from sqlalchemy import select
        from database import AsyncSessionLocal
        from models.all_models import AgentInstance

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(AgentInstance).where(
                AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id,
            ))
            instance = r.scalar_one_or_none()
        if instance is None:
            raise ValueError(f"Agent {agent_id} not found for tenant {tenant_id}")
        personality_mode = instance.personality.value
        operation_mode = instance.operation_mode.value
        primary_model = instance.model
        agent_name = instance.name
        employee_type = instance.employee_type
        allowed_tools = _employee_type_tools()[employee_type]
        config_version = instance.updated_at.isoformat()
    else:
        primary_model = await get_ai_model_override(tenant_id)

    agent = get_agent(
        personality_mode, operation_mode, tenant_id=tenant_id, primary_model=primary_model,
        agent_id=agent_id, agent_name=agent_name, allowed_tools=allowed_tools, config_version=config_version,
        employee_type=employee_type,
    )
    messages = list(history or []) + [HumanMessage(content=user_message)]
    # tenant_id/user_id/session_id are trusted values the caller derives from the
    # authenticated JWT (see api/v1/auth.py get_current_user, via api/v1/chat.py).
    # Any client-supplied `context` must never be able to override them — force
    # (not merge) so a malicious or mistaken client-supplied context can't smuggle
    # in a different identity for the LLM to be told about. caller_role is the
    # same freshly-re-read role get_current_user() now provides (never the
    # client-supplied JWT claim alone) — see role_denied_tool_calls().
    safe_context = dict(context or {})
    safe_context.update({"tenant_id": tenant_id, "user_id": user_id, "session_id": session_id})
    inputs = {
        "messages": messages, "tenant_id": tenant_id, "user_id": user_id,
        "session_id": session_id, "caller_role": caller_role,
        "personality_mode": personality_mode,
        "operation_mode": operation_mode, "pending_approvals": [], "role_denied": [],
        "scope_denied": [],
        "iteration_count": 0, "context": safe_context, "system_prompt": "",
        "agent_id": agent_id,
    }
    return agent, inputs


def _finalize_agent_result(final: dict, session_id: str) -> dict:
    """Shared tail for run_agent() and run_agent_stream() — turns a
    compiled graph's final AgentState (whatever .ainvoke() returns, or
    whatever the astream_events() root on_chain_end event's data.output
    carries — same shape either way) into the response dict every
    persistence caller (api/v1/chat.py, both the buffered and streaming
    routes) already expects. Extracted verbatim from run_agent()'s old
    tail — no behavior change for run_agent() itself."""
    last_ai = next((m for m in reversed(final["messages"]) if isinstance(m, AIMessage)), None)
    last_llm_call = next(
        (m for m in reversed(final["messages"])
         if isinstance(m, AIMessage) and m.additional_kwargs.get("llm_provider")),
        None,
    )
    role_denied = final.get("role_denied", [])
    scope_denied = final.get("scope_denied", [])
    response_text = content_as_text(last_ai.content) if last_ai else "No response."
    # Deterministic, because the prompt instruction alone demonstrably is not
    # enough: with "never disclose it" in the system prompt the model still
    # formatted the tenant_id into a reply heading unprompted. Refusing a direct
    # request and avoiding incidental disclosure are different behaviours.
    response_text = prompt_guard.redact_identifiers(
        response_text, (tenant_id, user_id, session_id))
    if role_denied and not response_text.strip():
        # The LLM's own text is typically blank/minimal when it was mainly
        # trying to call a now-stripped tool — make sure the user sees
        # *something* explaining why nothing happened, rather than a blank
        # reply that looks like a silent failure.
        response_text = "I don't have permission to do that with your current role: " + ", ".join(
            f"`{c['name']}`" for c in role_denied
        )
    elif scope_denied and not response_text.strip():
        # Same reasoning as the role_denied fallback above, but scope
        # denials already carry their own specific, legible reason (see
        # agent_scope_denial_reason) — surface those verbatim rather than
        # a generic "not scoped" line, per the explicit requirement that
        # a fail-closed scope denial must never read like an unexplained
        # permission error.
        response_text = " ".join(c["reason"] for c in scope_denied)
    return {
        "response": response_text,
        "provider": last_llm_call.additional_kwargs["llm_provider"] if last_llm_call else None,
        "used_fallback": last_llm_call.additional_kwargs.get("llm_used_fallback") if last_llm_call else None,
        "usage": last_llm_call.additional_kwargs.get("llm_usage_metadata") if last_llm_call else None,
        "pending_approvals": final.get("pending_approvals", []),
        "role_denied": role_denied,
        "scope_denied": scope_denied,
        "messages": final["messages"],
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def run_agent(user_message, tenant_id, user_id, session_id, caller_role,
                    personality_mode="engineer", operation_mode="assisted",
                    history=None, context=None, agent_id=None) -> dict:
    """agent_id is optional (Wunomo Projects Phase 0, commit 5) - omitted,
    every existing caller (api/v1/chat.py doesn't know about agent_id yet)
    gets the exact pre-Phase-0 behavior: request-body personality/
    operation_mode, the tenant's model override, "AXIOM" identity, the
    full ALL_TOOLS registry. Passed, the agent row is authoritative over
    all of that - the confirmed decision that agent config wins over both
    the request body and the tenant-level override once a real agent is
    named."""
    agent, inputs = await _prepare_agent_invocation(
        user_message, tenant_id, user_id, session_id, caller_role,
        personality_mode, operation_mode, history, context, agent_id,
    )
    final = await agent.ainvoke(inputs, config={"recursion_limit": AGENT_RECURSION_LIMIT})
    return _finalize_agent_result(final, session_id)


# --- Streaming (POST /api/v1/chat/stream only — POST /api/v1/chat/ is
# untouched and keeps calling run_agent() above) ---

# A live tool_start/tool_end SSE frame is a status line, not conversation
# history — cap_tool_result()'s MAX_TOOL_RESULT_CHARS (4000) exists to
# keep the *persisted* trace bounded; this is a much smaller, separate cap
# for the transient live preview shown while the tool is still running.
_STREAM_SUMMARY_MAX_CHARS = 180


def _summarize_for_stream(value) -> str:
    """Short, single-line preview for a tool_start/tool_end SSE event's
    args_summary/result_summary. The full args/result still flow through
    the normal persisted tool_calls trace (_extract_tool_trace in
    api/v1/chat.py) exactly as today — this is only ever shown live, then
    discarded."""
    if value is None or value == "":
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    if len(text) <= _STREAM_SUMMARY_MAX_CHARS:
        return text
    return text[:_STREAM_SUMMARY_MAX_CHARS].rstrip() + "…"


def _tool_end_payload(output) -> object:
    """Same content a persisted ToolMessage's `content` becomes in
    _extract_tool_trace — parsed back to a dict/list when it's JSON, left
    as-is otherwise."""
    content = output.content if isinstance(output, ToolMessage) else output
    try:
        return json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        return content


def _tool_end_ok(output) -> bool:
    """Same two failure shapes _extract_tool_trace already recognizes for
    the persisted trace (a source-lock conflict, ToolNode's own
    status="error" on an exception) — mirrored here so the live tool_end
    badge and the persisted trace never disagree about whether a call
    succeeded."""
    if isinstance(output, ToolMessage) and getattr(output, "status", None) == "error":
        return False
    payload = _tool_end_payload(output)
    if isinstance(payload, dict) and (payload.get("error") or payload.get("lock_conflict")):
        return False
    return True


async def run_agent_stream(user_message, tenant_id, user_id, session_id, caller_role,
                           personality_mode="engineer", operation_mode="assisted",
                           history=None, context=None, agent_id=None):
    """Streaming sibling of run_agent() — identical setup
    (_prepare_agent_invocation), identical compiled graph and cache
    (get_agent()), identical tools/approval gate/role gate/scope gate
    (nothing here changes agent_node, approval_gate_node, or ToolNode).
    The only difference is consuming the graph via
    `.astream_events(version="v2")` instead of a single `.ainvoke()`, so a
    caller can relay live progress instead of waiting for the whole turn.

    Only ever called from POST /api/v1/chat/stream (api/v1/chat.py) —
    POST /api/v1/chat/ keeps calling run_agent() above, unchanged.

    Yields plain dicts (not SSE-formatted strings — that's the HTTP
    layer's job):
      {"type": "token", "delta": str}
      {"type": "tool_start", "name": str, "args_summary": str}
      {"type": "tool_end", "name": str, "result_summary": str, "ok": bool}
      {"type": "final_state", "state": dict}
        — the graph's raw final AgentState, byte-for-byte what run_agent()
        gets back from .ainvoke() (confirmed via the astream_events root
        on_chain_end event, the one with no parent_ids — LangGraph's own
        top-level chain run). The caller finalizes it with
        _finalize_agent_result(), identical to the buffered path, so
        persistence never diverges between the two routes.

    Deliberately emits no "approval_required"/"done"/"error" events of its
    own — those depend on facts only the HTTP layer has (a real, committed
    ApprovalRequest id; whether persistence itself failed), so building
    them here would just be guessed at and rebuilt anyway. See
    api/v1/chat.py's chat_stream() / _run_agent_and_persist_stream().
    """
    agent, inputs = await _prepare_agent_invocation(
        user_message, tenant_id, user_id, session_id, caller_role,
        personality_mode, operation_mode, history, context, agent_id,
    )
    final_output = None
    async for ev in agent.astream_events(inputs, version="v2", config={"recursion_limit": AGENT_RECURSION_LIMIT}):
        et = ev["event"]
        if et == "on_chat_model_stream":
            # Auto-streaming: agent_node calls llm_with_tools.ainvoke() (a
            # single non-streaming call), but LangChain's ambient
            # RunnableConfig propagation means the real underlying
            # ChatGoogleGenerativeAI/ChatGroq client still streams
            # token-by-token under the hood whenever the outer graph is
            # driven via astream_events() — confirmed live against the
            # real compiled graph (17 on_chat_model_stream events for one
            # two-LLM-call turn) before writing this. content_as_text()
            # is the same normalizer llm_service.py already uses for a
            # full AIMessage's content — chunk.content is the same
            # list-of-blocks shape, just partial.
            delta = content_as_text(ev["data"]["chunk"].content)
            if delta:
                yield {"type": "token", "delta": delta}
        elif et == "on_tool_start":
            yield {
                "type": "tool_start",
                "name": ev.get("name") or "tool",
                "args_summary": _summarize_for_stream(ev.get("data", {}).get("input")),
            }
        elif et == "on_tool_end":
            output = ev.get("data", {}).get("output")
            yield {
                "type": "tool_end",
                "name": ev.get("name") or "tool",
                "result_summary": _summarize_for_stream(_tool_end_payload(output)),
                "ok": _tool_end_ok(output),
            }
        elif et == "on_chain_end":
            # Every on_chain_end updates this, not just a "root" one --
            # `not ev.get("parent_ids")` (the original check here) assumed
            # the graph's own top-level run always carries an empty
            # parent_ids list. Confirmed FALSE when run_agent_stream() is
            # driven directly (no surrounding ASGI request context) rather
            # than only ever through a live HTTP request: parent_ids never
            # reaches [] at all in that case (langgraph/langchain-core's
            # astream_events wraps the whole run one level deeper than
            # that check assumed) -- discovered live wiring the supervisor
            # path onto this same function, where run_agent_stream() is
            # called directly from a plain async function, not a request
            # handler, and every call silently produced zero "final_state"
            # events. What IS always true regardless of that ambient
            # context, confirmed against real astream_events() output:
            # the OUTERMOST chain's on_chain_end is structurally always
            # the LAST such event in the entire stream (a parent chain run
            # cannot complete before its own children do) -- so tracking
            # the most recent one and yielding it once, after the loop
            # ends, is correct regardless of what its absolute parent_ids
            # depth happens to be in a given calling context.
            final_output = ev["data"]["output"]
    if final_output is not None:
        yield {"type": "final_state", "state": final_output}


# Context windowing (Wunomo Projects Phase 0, commit 6). The open finding
# from 14 July (agent history ballooning 3 -> 15 -> 63 messages across
# three turns) was the reducer-doubling bug, already fixed — see
# AgentState's own comment above. What's still real and unaddressed
# without this: every tool call adds at least two messages to a session's
# history, nothing trims it, and every turn resends the ENTIRE prior
# history as input. Cost per turn grows with conversation length, not
# just with that turn's own content — at the measured ~4,480 tokens/turn
# average, an unbounded T-turn conversation costs roughly
# 4,480 * T*(T+1)/2 cumulative tokens (each turn repaying all the history
# before it), not 4,480 * T. A project channel multiplying that by
# participants and by project lifetime is exactly what turns this into
# real money (see WUNOMO_PROJECTS_PROPOSAL_v2.md's own framing).
#
# Sliding window (last CONTEXT_WINDOW_SIZE raw messages, verbatim) plus an
# incrementally-updated rolling summary of everything older, capped in
# length. The summary is persisted by the caller (api/v1/chat.py) as a
# real ChatMessage row with role="summary" — an ordinary value in an
# already-unconstrained String column, not new schema — and is only ever
# recomputed when the window has genuinely moved past what a prior
# summary already covers, not on every turn: new_summary_text below is
# None in the cheap, common case specifically so the caller knows exactly
# when a new row actually needs persisting.
CONTEXT_WINDOW_SIZE = 12
_SUMMARY_REQUEST_TYPE = "chat_history_summary"
_SUMMARY_WORD_CAP = 150


async def window_and_summarize(
    history: list[BaseMessage], *, tenant_id: str, session_id: str,
    prior_summary: str | None = None,
) -> tuple[list[BaseMessage], str | None]:
    """Returns (history_to_use_for_this_turn, new_summary_text_or_None).

    prior_summary is the caller's already-persisted summary text for
    everything strictly older than what's in `history` — this function
    trusts that `history` contains ONLY messages newer than what
    prior_summary already covers (api/v1/chat.py's own loading query is
    what guarantees this; this function doesn't re-derive it from message
    content or timestamps)."""
    if len(history) <= CONTEXT_WINDOW_SIZE:
        if prior_summary:
            return [SystemMessage(content=prior_summary)] + history, None
        return history, None

    windowed = history[-CONTEXT_WINDOW_SIZE:]
    newly_evicted = history[:-CONTEXT_WINDOW_SIZE]

    prompt = (
        f"Update the running summary of this conversation to also cover the "
        f"new messages below. Keep it under {_SUMMARY_WORD_CAP} words. Preserve "
        "any specific IDs, names, sources, or numbers mentioned - a future turn "
        "needs to still know what happened, not just the gist.\n\n"
    )
    if prior_summary:
        prompt += f"Existing summary so far:\n{prior_summary}\n\nNew messages to fold in:\n"
    else:
        prompt += "Messages to summarize:\n"
    prompt += "\n".join(f"{m.__class__.__name__}: {content_as_text(m.content)}" for m in newly_evicted)

    new_summary = await invoke_llm(
        [SystemMessage(content=prompt)],
        tenant_id=tenant_id, session_id=session_id, request_type=_SUMMARY_REQUEST_TYPE,
    )
    return [SystemMessage(content=new_summary)] + windowed, new_summary
