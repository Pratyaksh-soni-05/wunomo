"""Regression test for the "approval outcomes never return to the chat
thread" gap: GET /chat/sessions/{id}/history used to return a blocked
tool call's status exactly as written at turn time, forever -- even after
the real ApprovalRequest was later approved/rejected/executed on the
Approvals screen. A reopened conversation showed a permanently frozen
"Needs approval" with no way to tell what actually happened.

Fixed by resolving each blocked call's current status against the real
ApprovalRequest at read time (see api/v1/chat.py's
_resolve_blocked_call_statuses).
"""
import uuid

import pytest

from database import AsyncSessionLocal
from models.all_models import ChatMessage
from models.approval_model import ApprovalRequest, ApprovalStatus


async def _register(client, prefix="chatapproval"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Chat Approval Test",
        "tenant_name": f"Chat Approval Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()


async def _seed_blocked_chat_message(tenant_id: str, user_id: str, session_id: str) -> None:
    """Simulates what POST /chat/ writes for a turn that blocked one tool
    call -- the exact shape _extract_tool_trace() produces."""
    async with AsyncSessionLocal() as db:
        db.add(ChatMessage(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            session_id=session_id, role="assistant",
            content="Approval Required for 1 action(s).",
            tool_calls=[{
                "tool": "pause_pipeline", "args": {"pipeline_id": "p1"},
                "result": None, "status": "blocked_pending_approval",
            }],
        ))
        await db.commit()


async def _seed_approval_request(tenant_id: str, user_id: str, session_id: str,
                                  status: ApprovalStatus, execution_result=None) -> str:
    async with AsyncSessionLocal() as db:
        approval = ApprovalRequest(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            session_id=session_id, action_name="pause_pipeline",
            action_args={"pipeline_id": "p1"}, risk_level="medium",
            status=status, execution_result=execution_result,
        )
        db.add(approval)
        await db.commit()
        return approval.id


@pytest.mark.asyncio
async def test_history_reflects_real_executed_status_not_frozen_pending(client):
    reg = await _register(client)
    tenant_id, user_id, token = reg["tenant_id"], reg["user_id"], reg["access_token"]
    session_id = str(uuid.uuid4())

    await _seed_blocked_chat_message(tenant_id, user_id, session_id)
    approval_id = await _seed_approval_request(
        tenant_id, user_id, session_id, ApprovalStatus.EXECUTED,
        execution_result={"status": "paused"},
    )

    r = await client.get(
        f"/api/v1/chat/sessions/{session_id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    call = r.json()["messages"][0]["tool_calls"][0]
    assert call["status"] == "approval_executed"
    assert call["approval_id"] == approval_id
    assert call["result"] == {"status": "paused"}


@pytest.mark.asyncio
async def test_history_reflects_real_rejected_status(client):
    reg = await _register(client)
    tenant_id, user_id, token = reg["tenant_id"], reg["user_id"], reg["access_token"]
    session_id = str(uuid.uuid4())

    await _seed_blocked_chat_message(tenant_id, user_id, session_id)
    await _seed_approval_request(tenant_id, user_id, session_id, ApprovalStatus.REJECTED)

    r = await client.get(
        f"/api/v1/chat/sessions/{session_id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    call = r.json()["messages"][0]["tool_calls"][0]
    assert call["status"] == "approval_rejected"


@pytest.mark.asyncio
async def test_history_still_shows_pending_when_genuinely_unresolved(client):
    """The fix must not invent an outcome that hasn't happened yet."""
    reg = await _register(client)
    tenant_id, user_id, token = reg["tenant_id"], reg["user_id"], reg["access_token"]
    session_id = str(uuid.uuid4())

    await _seed_blocked_chat_message(tenant_id, user_id, session_id)
    await _seed_approval_request(tenant_id, user_id, session_id, ApprovalStatus.PENDING)

    r = await client.get(
        f"/api/v1/chat/sessions/{session_id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    call = r.json()["messages"][0]["tool_calls"][0]
    assert call["status"] == "blocked_pending_approval"
