from __future__ import annotations
from typing import TypedDict, Annotated, Sequence
import operator, json
from datetime import datetime, timezone

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from agent.personality import build_system_prompt, requires_approval, get_risk_level
from agent.tools import ALL_TOOLS
from services.llm_service import get_llm_for_agent, log_llm_usage, content_as_text
from services.rbac import has_permission, TOOL_CAPABILITIES
from models.all_models import PersonalityMode, OperationMode
import structlog

log = structlog.get_logger()

# Fail-closed, checked at import time (not lazily on first call): every real
# tool AXIOM can call must have a TOOL_CAPABILITIES entry, or it's silently
# denied for every role forever — better to crash the process at boot than
# let a newly-added tool go unmapped and undiscovered. This is the mechanism
# that makes "gating was opt-in" (the root cause of the original bypass)
# structurally impossible to repeat.
_unmapped_tools = sorted(set(t.name for t in ALL_TOOLS) - set(TOOL_CAPABILITIES))
assert not _unmapped_tools, (
    f"Tool(s) missing a TOOL_CAPABILITIES entry in services/rbac.py: {_unmapped_tools} "
    "— every registered AXIOM tool must be mapped or it's unreachable for every role."
)


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
    iteration_count: int
    context: dict
    system_prompt: str


def build_agent(personality=PersonalityMode.ENGINEER, operation=OperationMode.ASSISTED, primary_model=None):
    # Only pass primary_model when actually set, preserving the exact
    # get_llm_for_agent(temperature=0.0) call shape every existing
    # monkeypatched test fixture (test_agent_graph.py) already expects -
    # avoids touching ~8 unrelated test fixtures for a kwarg they never use.
    llm = get_llm_for_agent(temperature=0.0, primary_model=primary_model) if primary_model else get_llm_for_agent(temperature=0.0)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

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
        )
        # Tell the LLM its real, server-derived tenant_id explicitly — tool schemas
        # require tenant_id as an argument the LLM itself must supply, and without
        # this it has no way to know the real value and will invent a placeholder
        # (e.g. "your_tenant_id"), silently querying the wrong/nonexistent tenant.
        identity = (
            f"\n\n[IDENTITY]\nYour authenticated tenant_id is: {state['tenant_id']}\n"
            "Always pass this exact tenant_id to every tool call that requires one. "
            "Never invent, guess, or substitute a different tenant_id."
        )
        ctx = f"\n\n[CONTEXT]\n{json.dumps(state['context'])}" if state.get("context") else ""
        return {"system_prompt": sys_prompt + identity + ctx}

    async def agent_node(state):
        if state.get("iteration_count", 0) > MAX_AGENT_ITERATIONS:
            return {"messages": [AIMessage(content="Max reasoning steps reached. Please clarify your request.")]}
        llm_input = [SystemMessage(content=state["system_prompt"])] + list(state["messages"])
        response = await llm_with_tools.ainvoke(llm_input)
        usage = response.additional_kwargs.pop("_llm_usage", None)
        if usage:
            response.additional_kwargs["llm_provider"] = usage["provider"]
            await log_llm_usage(
                tenant_id=state["tenant_id"], user_id=state["user_id"], session_id=state["session_id"],
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
        # injected. Also coerce any dict/list-typed arg that arrived
        # stringified — see _coerce_stringified_object_args' module-level comment.
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
            _coerce_stringified_object_args(call["name"], args)

        # Role-permission gate — evaluated before and independently of
        # approval_gate_node's operation_mode/risk-tier check below. A call
        # denied here never reaches approval_gate_node or ToolNode at all;
        # it cannot become approvable later the way a risk-blocked call can,
        # because the caller's role was never allowed to request it in the
        # first place. See role_denied_tool_calls' own docstring.
        denied = role_denied_tool_calls(state["caller_role"], response.tool_calls or [])

        return {
            "messages": [response],
            "iteration_count": state.get("iteration_count", 0) + 1,
            "role_denied": state.get("role_denied", []) + denied,
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
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.set_entry_point("inject_system")
    graph.add_edge("inject_system", "agent")
    graph.add_edge("agent", "approval_gate")
    graph.add_conditional_edges("approval_gate", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")
    return graph.compile()


_cache: dict = {}

def get_agent(personality="engineer", operation="assisted", tenant_id=None, primary_model=None):
    """Cache key MUST include tenant_id and the resolved primary_model, not
    just personality/operation - see CLAUDE.md's get_agent() Gotcha
    (Phase 0's approved pushback #2). The cached value is a fully-built
    agent with a specific LLM already bound in; two tenants with different
    model overrides sharing a cache key would leak one tenant's model
    choice into another tenant's requests. tenant_id is required (not
    defaulted) so this can never silently regress back to the old
    personality:operation-only key by a caller forgetting to pass it."""
    if tenant_id is None:
        raise ValueError("get_agent() requires tenant_id - see the cache re-keying Gotcha in CLAUDE.md")
    key = f"{tenant_id}:{personality}:{operation}:{primary_model or 'default'}"
    if key not in _cache:
        _cache[key] = build_agent(PersonalityMode(personality), OperationMode(operation), primary_model=primary_model)
    return _cache[key]


async def run_agent(user_message, tenant_id, user_id, session_id, caller_role,
                    personality_mode="engineer", operation_mode="assisted",
                    history=None, context=None) -> dict:
    from services.settings_service import get_ai_model_override
    primary_model = await get_ai_model_override(tenant_id)
    agent = get_agent(personality_mode, operation_mode, tenant_id=tenant_id, primary_model=primary_model)
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
    final = await agent.ainvoke({
        "messages": messages, "tenant_id": tenant_id, "user_id": user_id,
        "session_id": session_id, "caller_role": caller_role,
        "personality_mode": personality_mode,
        "operation_mode": operation_mode, "pending_approvals": [], "role_denied": [],
        "iteration_count": 0, "context": safe_context, "system_prompt": "",
    }, config={"recursion_limit": AGENT_RECURSION_LIMIT})
    last_ai = next((m for m in reversed(final["messages"]) if isinstance(m, AIMessage)), None)
    last_llm_call = next(
        (m for m in reversed(final["messages"])
         if isinstance(m, AIMessage) and m.additional_kwargs.get("llm_provider")),
        None,
    )
    role_denied = final.get("role_denied", [])
    response_text = content_as_text(last_ai.content) if last_ai else "No response."
    if role_denied and not response_text.strip():
        # The LLM's own text is typically blank/minimal when it was mainly
        # trying to call a now-stripped tool — make sure the user sees
        # *something* explaining why nothing happened, rather than a blank
        # reply that looks like a silent failure.
        response_text = "I don't have permission to do that with your current role: " + ", ".join(
            f"`{c['name']}`" for c in role_denied
        )
    return {
        "response": response_text,
        "provider": last_llm_call.additional_kwargs["llm_provider"] if last_llm_call else None,
        "pending_approvals": final.get("pending_approvals", []),
        "role_denied": role_denied,
        "messages": final["messages"],
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
