from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from .auth import get_current_user, enforce_quota
from agent.dataops_agent import run_agent
from database import AsyncSessionLocal
from models.all_models import ChatMessage
from sqlalchemy import select, func
from datetime import datetime
import uuid
from models.approval_model import ApprovalRequest
from schemas.chat_schema import ChatRequest
from datetime import datetime
from langchain_core.messages import AIMessage as LCAIMessage, ToolMessage as LCToolMessage

router = APIRouter()


def _extract_tool_trace(new_messages, blocked_tool_calls) -> list[dict]:
    """Build a tool-call trace for this turn from the graph's own new messages:
    every AIMessage.tool_calls paired with its ToolMessage result (matched by
    tool_call_id), plus any tool calls approval_gate_node blocked before they
    ever reached ToolNode. Tool outputs are already capped by cap_tool_result()
    before they enter this list (see agent/tools/_utils.py) — no re-truncation
    needed here."""
    results_by_id = {
        m.tool_call_id: m.content for m in new_messages if isinstance(m, LCToolMessage)
    }
    blocked_ids = {c["id"] for c in blocked_tool_calls}
    trace = []
    for m in new_messages:
        if isinstance(m, LCAIMessage) and m.tool_calls:
            for call in m.tool_calls:
                if call["id"] in blocked_ids:
                    status = "blocked_pending_approval"
                    result = None
                elif call["id"] in results_by_id:
                    status = "completed"
                    result = results_by_id[call["id"]]
                else:
                    continue
                trace.append({
                    "tool": call["name"], "args": call["args"],
                    "result": result, "status": status,
                })
    return trace

@router.post("/")
async def chat(req: ChatRequest, user=Depends(enforce_quota("ai_credits"))):
    session_id = req.session_id or str(uuid.uuid4())
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.tenant_id == tenant_id,
        ).order_by(ChatMessage.created_at.asc()).limit(20))
        history_msgs = r.scalars().all()

    from langchain_core.messages import HumanMessage, AIMessage
    history = []
    for m in history_msgs:
        if m.role == "user":
            history.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            history.append(AIMessage(content=m.content))

    result = await run_agent(
        user_message=req.message, tenant_id=tenant_id, user_id=user["sub"],
        session_id=session_id, personality_mode=req.personality_mode,
        operation_mode=req.operation_mode, history=history, context=req.context,
    )

    async with AsyncSessionLocal() as db:
        if result.get("pending_approvals"):
            for pa in result["pending_approvals"]:
                approval = ApprovalRequest(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    user_id=user["sub"],
                    session_id=session_id,
                    action_name=pa["name"],
                    action_args=pa.get("args", {}),
                    risk_level=pa.get("risk_level", "high"),
                    reason=pa.get("reason", ""),
                )
                db.add(approval)

        # result["messages"] is the full accumulated state (incoming history +
        # this turn's new messages, per AgentState.messages' operator.add
        # reducer) — slice off the history prefix chat.py itself passed in to
        # isolate just this turn's new AI/tool messages for the trace.
        new_messages = result["messages"][len(history):]
        tool_trace = _extract_tool_trace(new_messages, result["pending_approvals"])

        for role, content, calls in [
            ("user", req.message, []),
            ("assistant", result["response"], tool_trace),
        ]:
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                session_id=session_id, role=role, content=content,
                personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                tool_calls=calls, created_at=datetime.utcnow(),
            ))
        await db.commit()

    return {
        "session_id": session_id,
        "response": result["response"],
        "provider": result.get("provider"),
        "pending_approvals": result["pending_approvals"],
        "tool_calls": tool_trace,
        "timestamp": result["timestamp"],
    }


@router.get("/sessions")
async def list_sessions(user=Depends(get_current_user)):
    """Tenant-scoped AND user-scoped: sessions are private per-user (like the
    rest of this chat interface), not visible to other members of the same
    tenant — see CLAUDE.md Phase 8 for the reasoning."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(
                ChatMessage.session_id,
                func.min(ChatMessage.created_at).label("started_at"),
                func.max(ChatMessage.created_at).label("last_activity"),
                func.count().label("message_count"),
            )
            .where(ChatMessage.tenant_id == user["tenant_id"], ChatMessage.user_id == user["sub"])
            .group_by(ChatMessage.session_id)
            .order_by(func.max(ChatMessage.created_at).desc())
        )
        rows = r.all()

        titles = {}
        if rows:
            tr = await db.execute(
                select(ChatMessage.session_id, ChatMessage.content)
                .where(
                    ChatMessage.tenant_id == user["tenant_id"], ChatMessage.user_id == user["sub"],
                    ChatMessage.role == "user", ChatMessage.session_id.in_([row.session_id for row in rows]),
                )
                .order_by(ChatMessage.created_at.asc())
            )
            for sid, content in tr.all():
                titles.setdefault(sid, content[:60])

    return {"sessions": [
        {
            "session_id": row.session_id,
            "title": titles.get(row.session_id, ""),
            "started_at": str(row.started_at),
            "last_activity": str(row.last_activity),
            "message_count": row.message_count,
        }
        for row in rows
    ]}


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.tenant_id == user["tenant_id"],
            ChatMessage.user_id == user["sub"],
        ).order_by(ChatMessage.created_at.asc()))
        msgs = r.scalars().all()
        return {"session_id": session_id, "messages": [
            {
                "role": m.role, "content": m.content, "tool_calls": m.tool_calls or [],
                "timestamp": str(m.created_at),
            }
            for m in msgs
        ]}