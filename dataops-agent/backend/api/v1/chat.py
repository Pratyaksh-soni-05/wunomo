from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from .auth import get_current_user
from agent.dataops_agent import run_agent
from database import AsyncSessionLocal
from models.all_models import ChatMessage
from sqlalchemy import select
from datetime import datetime
import uuid
from models.approval_model import ApprovalRequest
from schemas.chat_schema import ChatRequest
from datetime import datetime

router = APIRouter()

@router.post("/")
async def chat(req: ChatRequest, user=Depends(get_current_user)):
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

        for role, content in [("user", req.message), ("assistant", result["response"])]:
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                session_id=session_id, role=role, content=content,
                personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                created_at=datetime.utcnow(),
            ))
        await db.commit()

    return {
        "session_id": session_id,
        "response": result["response"],
        "pending_approvals": result["pending_approvals"],
        "timestamp": result["timestamp"],
    }


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.tenant_id == user["tenant_id"],
        ).order_by(ChatMessage.created_at.asc()))
        msgs = r.scalars().all()
        return {"session_id": session_id, "messages": [
            {"role": m.role, "content": m.content, "timestamp": str(m.created_at)} for m in msgs
        ]}