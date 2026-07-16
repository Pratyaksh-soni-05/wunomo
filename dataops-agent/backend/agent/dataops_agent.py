from __future__ import annotations
from typing import TypedDict, Annotated, Sequence
import operator, json
from datetime import datetime, timezone

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from agent.personality import build_system_prompt, requires_approval
from agent.tools import ALL_TOOLS
from services.llm_service import get_llm_for_agent, log_llm_usage
from models.all_models import PersonalityMode, OperationMode
import structlog

log = structlog.get_logger()

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
    personality_mode: str
    operation_mode: str
    pending_approvals: list
    iteration_count: int
    context: dict
    system_prompt: str


def build_agent(personality=PersonalityMode.ENGINEER, operation=OperationMode.ASSISTED):
    llm = get_llm_for_agent(temperature=0.0)
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
        for call in (response.tool_calls or []):
            if "tenant_id" in call.get("args", {}):
                call["args"]["tenant_id"] = state["tenant_id"]
        return {"messages": [response], "iteration_count": state.get("iteration_count", 0) + 1}

    def approval_gate_node(state):
        last_msg = state["messages"][-1]
        if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
            return {}
        op_mode = OperationMode(state["operation_mode"])
        blocked = [c for c in last_msg.tool_calls if requires_approval(c["name"], op_mode)]
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

def get_agent(personality="engineer", operation="assisted"):
    key = f"{personality}:{operation}"
    if key not in _cache:
        _cache[key] = build_agent(PersonalityMode(personality), OperationMode(operation))
    return _cache[key]


async def run_agent(user_message, tenant_id, user_id, session_id,
                    personality_mode="engineer", operation_mode="assisted",
                    history=None, context=None) -> dict:
    agent = get_agent(personality_mode, operation_mode)
    messages = list(history or []) + [HumanMessage(content=user_message)]
    # tenant_id/user_id/session_id are trusted values the caller derives from the
    # authenticated JWT (see api/v1/auth.py get_current_user, via api/v1/chat.py).
    # Any client-supplied `context` must never be able to override them — force
    # (not merge) so a malicious or mistaken client-supplied context can't smuggle
    # in a different identity for the LLM to be told about.
    safe_context = dict(context or {})
    safe_context.update({"tenant_id": tenant_id, "user_id": user_id, "session_id": session_id})
    final = await agent.ainvoke({
        "messages": messages, "tenant_id": tenant_id, "user_id": user_id,
        "session_id": session_id, "personality_mode": personality_mode,
        "operation_mode": operation_mode, "pending_approvals": [],
        "iteration_count": 0, "context": safe_context, "system_prompt": "",
    }, config={"recursion_limit": AGENT_RECURSION_LIMIT})
    last_ai = next((m for m in reversed(final["messages"]) if isinstance(m, AIMessage)), None)
    last_llm_call = next(
        (m for m in reversed(final["messages"])
         if isinstance(m, AIMessage) and m.additional_kwargs.get("llm_provider")),
        None,
    )
    return {
        "response": last_ai.content if last_ai else "No response.",
        "provider": last_llm_call.additional_kwargs["llm_provider"] if last_llm_call else None,
        "pending_approvals": final.get("pending_approvals", []),
        "messages": final["messages"],
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
