from __future__ import annotations
from typing import TypedDict, Annotated, Sequence
import operator, json
from datetime import datetime, timezone 

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from agent.personality import build_system_prompt, requires_approval
from agent.tools import ALL_TOOLS
from services.llm_service import get_llm_for_agent
from models.all_models import PersonalityMode, OperationMode
import structlog

log = structlog.get_logger()


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


def build_agent(personality=PersonalityMode.ENGINEER, operation=OperationMode.ASSISTED):
    llm = get_llm_for_agent(temperature=0.0)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def inject_system_prompt(state):
        sys_prompt = build_system_prompt(
            PersonalityMode(state["personality_mode"]),
            OperationMode(state["operation_mode"]),
        )
        ctx = f"\n\n[CONTEXT]\n{json.dumps(state['context'])}" if state.get("context") else ""
        existing = [m for m in state["messages"] if isinstance(m, SystemMessage)]
        if not existing:
            return {**state, "messages": [SystemMessage(content=sys_prompt + ctx)] + list(state["messages"])}
        return state

    async def agent_node(state):
        if state.get("iteration_count", 0) > 20:
            return {**state, "messages": state["messages"] + [
                AIMessage(content="Max reasoning steps reached. Please clarify your request.")
            ]}
        response = await llm_with_tools.ainvoke(state["messages"])
        return {**state, "messages": state["messages"] + [response],
                "iteration_count": state.get("iteration_count", 0) + 1}

    def approval_gate_node(state):
        last_msg = state["messages"][-1]
        if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
            return state
        op_mode = OperationMode(state["operation_mode"])
        blocked = [c for c in last_msg.tool_calls if requires_approval(c["name"], op_mode)]
        if blocked:
            msg = (f"**Approval Required** for {len(blocked)} action(s):\n"
                   + "\n".join(f"- `{c['name']}`" for c in blocked)
                   + "\n\nApprove or reject in the approval center.")
            return {**state, "pending_approvals": state.get("pending_approvals", []) + blocked,
                    "messages": state["messages"] + [AIMessage(content=msg)]}
        return state

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
    final = await agent.ainvoke({
        "messages": messages, "tenant_id": tenant_id, "user_id": user_id,
        "session_id": session_id, "personality_mode": personality_mode,
        "operation_mode": operation_mode, "pending_approvals": [],
        "iteration_count": 0, "context": context or {},
    })
    last_ai = next((m for m in reversed(final["messages"]) if isinstance(m, AIMessage)), None)
    return {
        "response": last_ai.content if last_ai else "No response.",
        "pending_approvals": final.get("pending_approvals", []),
        "messages": final["messages"],
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
