"""Wunomo Projects Phase 4 frontend, slice 11: originating_session_id
read-side wiring. The write path (TaskCreateModal -> create_task) was
already correct before this slice -- this covers what was missing: the
field showing up in API responses, and a task started from a
conversation surviving a reload of that conversation as a real task
card, derived at read time from the persisted Task row rather than a
second, driftable copy.
"""
import uuid
from datetime import datetime, timedelta

import pytest

from database import AsyncSessionLocal
from models.all_models import ChatMessage, Task, TaskShape, TaskStatus


async def _register(client, prefix="taskcard"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Card Test",
        "tenant_name": f"Task Card Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _seed_task(tenant_id, user_id, goal, originating_session_id, created_at):
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, goal=goal,
            task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE, status=TaskStatus.DRAFT_PLAN,
            step_budget_max=20, paused_seconds=0,
            originating_session_id=originating_session_id, created_at=created_at,
        )
        db.add(task)
        await db.commit()
        return task.id


async def _seed_message(tenant_id, user_id, session_id, role, content, created_at):
    async with AsyncSessionLocal() as db:
        db.add(ChatMessage(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            role=role, content=content, tool_calls=[], created_at=created_at,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_task_serialization_includes_originating_session_id(client):
    token, tenant_id, user_id = await _register(client, "cardA")
    session_id = str(uuid.uuid4())
    task_id = await _seed_task(tenant_id, user_id, "Fix the pipeline", session_id, datetime.utcnow())

    resp = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))
    assert resp.json()["originating_session_id"] == session_id


@pytest.mark.asyncio
async def test_task_with_no_originating_session_serializes_null(client):
    token, tenant_id, user_id = await _register(client, "cardB")
    task_id = await _seed_task(tenant_id, user_id, "Bare task", None, datetime.utcnow())

    resp = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))
    assert resp.json()["originating_session_id"] is None


@pytest.mark.asyncio
async def test_task_started_from_a_conversation_survives_reload_as_a_card(client):
    """The exact gap this slice closes: a task card was purely client-side
    state before this change and vanished on reload. Now derived fresh
    from the real Task row on every GET .../history call."""
    token, tenant_id, user_id = await _register(client, "cardC")
    session_id = str(uuid.uuid4())
    base = datetime.utcnow()
    await _seed_message(tenant_id, user_id, session_id, "user", "please fix the pipeline", base)
    task_id = await _seed_task(tenant_id, user_id, "Fix the pipeline", session_id, base + timedelta(seconds=5))

    resp = await client.get(f"/api/v1/chat/sessions/{session_id}/history", headers=_auth(token))
    messages = resp.json()["messages"]
    task_cards = [m for m in messages if m.get("taskCard")]
    assert len(task_cards) == 1
    assert task_cards[0]["taskCard"] == {"id": task_id, "goal": "Fix the pipeline"}


@pytest.mark.asyncio
async def test_task_card_appears_in_correct_chronological_position(client):
    """A task started mid-conversation must slot in between the messages
    that came before and after it, not always at the start or end."""
    token, tenant_id, user_id = await _register(client, "cardD")
    session_id = str(uuid.uuid4())
    base = datetime.utcnow()
    await _seed_message(tenant_id, user_id, session_id, "user", "first message", base)
    task_id = await _seed_task(tenant_id, user_id, "Mid-conversation task", session_id, base + timedelta(seconds=10))
    await _seed_message(tenant_id, user_id, session_id, "user", "last message", base + timedelta(seconds=20))

    resp = await client.get(f"/api/v1/chat/sessions/{session_id}/history", headers=_auth(token))
    messages = resp.json()["messages"]
    assert len(messages) == 3
    assert messages[0]["content"] == "first message"
    assert messages[1].get("taskCard") == {"id": task_id, "goal": "Mid-conversation task"}
    assert messages[2]["content"] == "last message"


@pytest.mark.asyncio
async def test_task_with_no_originating_session_never_appears_in_any_history(client):
    token, tenant_id, user_id = await _register(client, "cardE")
    session_id = str(uuid.uuid4())
    await _seed_message(tenant_id, user_id, session_id, "user", "hello", datetime.utcnow())
    await _seed_task(tenant_id, user_id, "Unrelated bare task", None, datetime.utcnow())

    resp = await client.get(f"/api/v1/chat/sessions/{session_id}/history", headers=_auth(token))
    messages = resp.json()["messages"]
    assert len(messages) == 1
    assert not messages[0].get("taskCard")


@pytest.mark.asyncio
async def test_task_card_is_tenant_and_user_scoped(client):
    """A task originating from a DIFFERENT tenant's session_id (however
    unlikely a collision) must never leak into this user's history."""
    token_a, tenant_a, user_a = await _register(client, "cardF1")
    token_b, tenant_b, user_b = await _register(client, "cardF2")
    shared_session_id = str(uuid.uuid4())  # simulated id collision across tenants
    await _seed_message(tenant_a, user_a, shared_session_id, "user", "tenant A's message", datetime.utcnow())
    await _seed_task(tenant_b, user_b, "Tenant B's task", shared_session_id, datetime.utcnow())

    resp = await client.get(f"/api/v1/chat/sessions/{shared_session_id}/history", headers=_auth(token_a))
    messages = resp.json()["messages"]
    assert all(not m.get("taskCard") for m in messages)
