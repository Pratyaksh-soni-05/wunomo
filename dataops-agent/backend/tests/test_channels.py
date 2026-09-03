"""Wunomo Projects Phase 2: api/v1/channels.py (create/list/get, user and
agent membership) and @mention routing through the real /api/v1/chat/
endpoint. run_agent() itself is mocked (captures which agent_id it was
called with) -- these tests are about routing, not the LLM.
"""
import uuid
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

import api.v1.chat as chat_module
from database import AsyncSessionLocal
from models.all_models import ChatMessage, User


async def _register(client, prefix="chan"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Channel Test",
        "tenant_name": f"Channel Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _add_member(tenant_id: str, role: str = "owner"):
    from services.auth_service import hash_password, issue_token_for_user
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"member-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name="Second User", role=role,
            is_active=True, email_verified=True,
        )
        db.add(user)
        await db.commit()
        return issue_token_for_user(user, "password"), user.id


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _hire_agent(client, token, name="Nova", **overrides):
    body = {"name": name, **overrides}
    r = await client.post("/api/v1/agents/", headers=_auth(token), json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _fake_run_agent(captured, response_text="ok"):
    async def _run(*, user_message, tenant_id, user_id, session_id, caller_role,
                    personality_mode, operation_mode, history, context, agent_id):
        captured["agent_id"] = agent_id
        captured["user_message"] = user_message
        return {
            "response": response_text, "provider": None, "pending_approvals": [],
            "role_denied": [], "scope_denied": [],
            "messages": list(history or []) + [AIMessage(content=response_text)],
            "session_id": session_id, "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return _run


# ---------------------------------------------------------------------------
# api/v1/channels.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_channel_makes_creator_a_member(client):
    token, tenant_id, user_id = await _register(client, "chanA")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    assert r.status_code == 200
    channel_id = r.json()["id"]

    r = await client.get("/api/v1/channels/", headers=_auth(token))
    assert {c["id"] for c in r.json()["channels"]} == {channel_id}

    r = await client.get(f"/api/v1/channels/{channel_id}", headers=_auth(token))
    assert r.status_code == 200
    assert {u["id"] for u in r.json()["users"]} == {user_id}
    assert r.json()["agents"] == []


@pytest.mark.asyncio
async def test_add_and_remove_agent_member(client):
    token, tenant_id, _ = await _register(client, "chanB")
    agent_id = await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]

    r = await client.post(f"/api/v1/channels/{channel_id}/members/agents/{agent_id}", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["added"] is True

    r = await client.get(f"/api/v1/channels/{channel_id}", headers=_auth(token))
    assert {a["id"] for a in r.json()["agents"]} == {agent_id}

    r = await client.delete(f"/api/v1/channels/{channel_id}/members/agents/{agent_id}", headers=_auth(token))
    assert r.status_code == 200
    r = await client.get(f"/api/v1/channels/{channel_id}", headers=_auth(token))
    assert r.json()["agents"] == []


@pytest.mark.asyncio
async def test_add_user_member(client):
    token, tenant_id, _ = await _register(client, "chanC")
    token_b, user_b_id = await _add_member(tenant_id)
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]

    r = await client.post(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/channels/{channel_id}", headers=_auth(token_b))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_non_member_cannot_manage_or_view_a_channel(client):
    token, tenant_id, _ = await _register(client, "chanD")
    token_b, user_b_id = await _add_member(tenant_id)
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "Private"})
    channel_id = r.json()["id"]

    r = await client.get(f"/api/v1/channels/{channel_id}", headers=_auth(token_b))
    assert r.status_code == 403

    r = await client.post(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token_b))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_channel_management_rejects_cross_tenant_agent_and_user(client):
    token_a, tenant_a, _ = await _register(client, "chanE1")
    token_b, tenant_b, _ = await _register(client, "chanE2")
    agent_b = await _hire_agent(client, token_b, "Other")
    _, user_b_id = await _add_member(tenant_b)

    r = await client.post("/api/v1/channels/", headers=_auth(token_a), json={"name": "General"})
    channel_id = r.json()["id"]

    r = await client.post(f"/api/v1/channels/{channel_id}/members/agents/{agent_b}", headers=_auth(token_a))
    assert r.status_code == 404

    r = await client.post(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token_a))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# @mention routing through the real /api/v1/chat/ endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mention_routes_to_the_tagged_agent_and_nobody_else(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "mentionA")
    nova_id = await _hire_agent(client, token, "Nova")
    atlas_id = await _hire_agent(client, token, "Atlas")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{atlas_id}", headers=_auth(token))

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured, "Nova here."))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Nova sync the warehouse", "session_id": channel_id,
    })
    assert r.status_code == 200
    assert captured["agent_id"] == nova_id
    assert captured["user_message"] == "sync the warehouse"
    assert r.json()["response"] == "Nova here."

    async with AsyncSessionLocal() as db:
        r2 = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == channel_id, ChatMessage.role == "user",
        ))
        user_msg = r2.scalar_one()
        assert user_msg.mentioned_agent_id == nova_id

        r2 = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == channel_id, ChatMessage.role == "assistant",
        ))
        assistant_msg = r2.scalar_one()
        assert assistant_msg.agent_id == nova_id


@pytest.mark.asyncio
async def test_mentioning_an_agent_not_in_the_channel_is_refused(client, monkeypatch):
    """An agent not in channel_agents cannot be mentioned -- resolved
    against real membership, never a bare string match on the name."""
    token, tenant_id, _ = await _register(client, "mentionB")
    await _hire_agent(client, token, "Nova")  # exists, but never added to the channel
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Nova sync it", "session_id": channel_id,
    })
    assert r.status_code == 200
    assert "don't see anyone named 'Nova'" in r.json()["response"]
    assert captured == {}, "run_agent must never be called for an unresolved mention"


@pytest.mark.asyncio
async def test_no_mention_routes_automatically_with_exactly_one_agent_member(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "mentionC")
    nova_id = await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "sync the warehouse", "session_id": channel_id,
    })
    assert r.status_code == 200
    assert captured["agent_id"] == nova_id
    assert captured["user_message"] == "sync the warehouse"


@pytest.mark.asyncio
async def test_no_mention_with_multiple_agents_refuses_to_guess(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "mentionD")
    nova_id = await _hire_agent(client, token, "Nova")
    atlas_id = await _hire_agent(client, token, "Atlas")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{atlas_id}", headers=_auth(token))

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "sync the warehouse", "session_id": channel_id,
    })
    assert r.status_code == 200
    assert "please @mention" in r.json()["response"]
    assert captured == {}


@pytest.mark.asyncio
async def test_no_mention_with_zero_agents_refuses_to_guess(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "mentionE")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "sync the warehouse", "session_id": channel_id,
    })
    assert r.status_code == 200
    assert "No agents are" in r.json()["response"]
    assert captured == {}


@pytest.mark.asyncio
async def test_non_channel_member_cannot_post_into_a_channel(client, monkeypatch):
    token, tenant_id, _ = await _register(client, "mentionF")
    token_b, _ = await _add_member(tenant_id)
    nova_id = await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))

    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent({}))

    r = await client.post("/api/v1/chat/", headers=_auth(token_b), json={
        "message": "@Nova sync it", "session_id": channel_id,
    })
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_two_different_users_can_both_post_in_the_same_channel(client, monkeypatch):
    """The whole point of a channel, contrasted directly with the
    private-session ownership rule: multiple real users legitimately
    share one session_id here."""
    token_a, tenant_id, _ = await _register(client, "mentionG")
    token_b, user_b_id = await _add_member(tenant_id)
    nova_id = await _hire_agent(client, token_a, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token_a), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token_a))
    await client.post(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token_a))

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token_a), json={
        "message": "@Nova hi from A", "session_id": channel_id,
    })
    assert r.status_code == 200

    r = await client.post("/api/v1/chat/", headers=_auth(token_b), json={
        "message": "@Nova hi from B", "session_id": channel_id,
    })
    assert r.status_code == 200
