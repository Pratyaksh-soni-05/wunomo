"""Wunomo Projects Phase 2: api/v1/channels.py (create/list/get, user and
agent membership) and @mention routing through the real /api/v1/chat/
endpoint. run_agent() itself is mocked (captures which agent_id it was
called with) -- these tests are about routing, not the LLM.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

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
async def test_list_channels_reports_agent_count(client):
    """Slice 6: agent_count on GET /api/v1/channels/ lets the sidebar flag
    a channel that can't be talked to yet, without opening it first."""
    token, tenant_id, _ = await _register(client, "chanF")
    nova_id = await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "Empty"})
    empty_channel_id = r.json()["id"]
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "Staffed"})
    staffed_channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{staffed_channel_id}/members/agents/{nova_id}", headers=_auth(token))

    r = await client.get("/api/v1/channels/", headers=_auth(token))
    by_id = {c["id"]: c["agent_count"] for c in r.json()["channels"]}
    assert by_id[empty_channel_id] == 0
    assert by_id[staffed_channel_id] == 1


@pytest.mark.asyncio
async def test_offboarding_a_channels_only_agent_drops_its_agent_count_to_zero(client):
    """The exact scenario slice 6 was built to handle without leaving the
    channel silently unusable: offboarding is never blocked by channel
    membership (explicit design decision), but the resulting state must be
    visible via agent_count, not just discovered by hitting a dead message."""
    token, tenant_id, _ = await _register(client, "chanG")
    nova_id = await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))

    r = await client.get("/api/v1/channels/", headers=_auth(token))
    assert r.json()["channels"][0]["agent_count"] == 1

    offboard = await client.post(f"/api/v1/agents/{nova_id}/offboard", headers=_auth(token))
    assert offboard.status_code == 200, "offboarding must not be blocked by sole channel membership"

    r = await client.get("/api/v1/channels/", headers=_auth(token))
    assert r.json()["channels"][0]["agent_count"] == 0


@pytest.mark.asyncio
async def test_removing_the_only_human_member_is_blocked_with_a_real_way_out(client):
    """Slice 7 explicit user decision: block, don't allow silently, since
    _require_membership gates every management action (including adding a
    new member) -- a channel with zero human members has nobody left in
    the tenant who could ever add themselves back in. There is no
    delete-channel or leave endpoint in this codebase; the 409 must name
    a real, actually-available way out (add someone else first), not a
    fictional one."""
    token, tenant_id, user_id = await _register(client, "chanH")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "Solo"})
    channel_id = r.json()["id"]

    r = await client.delete(f"/api/v1/channels/{channel_id}/members/users/{user_id}", headers=_auth(token))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "only person in this channel" in detail
    assert "add someone else" in detail.lower()
    assert "delete" not in detail.lower(), "no delete-channel endpoint exists -- must not imply one does"

    # Confirmed real way out: add a second person, then leaving succeeds.
    token_b, user_b_id = await _add_member(tenant_id)
    await client.post(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token))
    r = await client.delete(f"/api/v1/channels/{channel_id}/members/users/{user_id}", headers=_auth(token))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_removing_a_member_when_others_remain_is_not_blocked(client):
    token, tenant_id, user_id = await _register(client, "chanI")
    token_b, user_b_id = await _add_member(tenant_id)
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "Duo"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token))

    r = await client.delete(f"/api/v1/channels/{channel_id}/members/users/{user_b_id}", headers=_auth(token))
    assert r.status_code == 200


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
async def test_mentioning_a_real_agent_not_in_the_channel_names_the_membership_gap(client, monkeypatch):
    """An agent not in channel_agents cannot be mentioned -- resolved
    against real membership, never a bare string match on the name.
    Slice 6 explicit requirement: this must read differently from a plain
    typo, since the fix (add them) is different from the fix for a typo
    (spell it correctly) -- a single generic message would make the two
    indistinguishable."""
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
    body = r.json()["response"]
    assert "Nova exists but isn't a member of this channel yet" in body
    assert "Add them from this channel's members" in body
    assert captured == {}, "run_agent must never be called for an unresolved mention"


@pytest.mark.asyncio
async def test_mentioning_a_name_with_no_such_agent_in_the_tenant_at_all(client, monkeypatch):
    """The other half of the same disambiguation: a genuine typo (no agent
    by this name anywhere in the tenant) must read differently from the
    membership-gap case above."""
    token, tenant_id, _ = await _register(client, "mentionH")
    await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Nvoa sync it", "session_id": channel_id,
    })
    assert r.status_code == 200
    body = r.json()["response"]
    assert "'Nvoa' doesn't match any agent in your workspace" in body
    assert "isn't a member" not in body
    assert captured == {}


@pytest.mark.asyncio
async def test_mentioning_an_offboarded_agents_name_reads_as_no_such_agent(client, monkeypatch):
    """An offboarded agent can't be added back (no reactivation endpoint) --
    from the mentioning user's perspective this is the same dead end as a
    typo, not a fixable membership gap, so it must not claim "isn't a
    member yet" (which implies adding them would work)."""
    token, tenant_id, _ = await _register(client, "mentionI")
    nova_id = await _hire_agent(client, token, "Nova")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/agents/{nova_id}/offboard", headers=_auth(token))

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured))

    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Nova sync it", "session_id": channel_id,
    })
    assert r.status_code == 200
    assert "'Nova' doesn't match any agent in your workspace" in r.json()["response"]
    assert captured == {}


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


# ---------------------------------------------------------------------------
# Context filtering, reading (a) (Wunomo Projects Phase 2): enforced by
# load_agent_channel_context's query, never by a prompt instruction.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_only_sees_messages_it_authored_or_was_mentioned_in(client, monkeypatch):
    """Nova and Atlas share one channel. Atlas's private exchange with the
    user must never appear in the history a later turn loads for Nova, and
    vice versa -- the whole point of reading (a)."""
    token, tenant_id, _ = await _register(client, "ctxA")
    nova_id = await _hire_agent(client, token, "Nova")
    atlas_id = await _hire_agent(client, token, "Atlas")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{atlas_id}", headers=_auth(token))

    calls = []

    async def _run(*, user_message, tenant_id, user_id, session_id, caller_role,
                    personality_mode, operation_mode, history, context, agent_id):
        calls.append({"agent_id": agent_id, "history": list(history or [])})
        reply = f"ack: {user_message}"
        return {
            "response": reply, "provider": None, "pending_approvals": [],
            "role_denied": [], "scope_denied": [],
            "messages": list(history or []) + [AIMessage(content=reply)],
            "session_id": session_id, "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    monkeypatch.setattr(chat_module, "run_agent", _run)

    await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Nova nova secret task", "session_id": channel_id,
    })
    await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Atlas atlas secret task", "session_id": channel_id,
    })
    await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Nova nova follow up", "session_id": channel_id,
    })
    # A second Atlas turn so its loaded history (built from messages
    # strictly before this turn) has something to actually check.
    await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Atlas atlas follow up", "session_id": channel_id,
    })

    nova_calls = [c for c in calls if c["agent_id"] == nova_id]
    final_nova_history_text = " ".join(m.content for m in nova_calls[-1]["history"])
    assert "nova secret task" in final_nova_history_text
    assert "atlas secret task" not in final_nova_history_text

    atlas_calls = [c for c in calls if c["agent_id"] == atlas_id]
    final_atlas_history_text = " ".join(m.content for m in atlas_calls[-1]["history"])
    assert "atlas secret task" in final_atlas_history_text
    assert "nova secret task" not in final_atlas_history_text
    assert "nova follow up" not in final_atlas_history_text


@pytest.mark.asyncio
async def test_channel_summary_is_scoped_per_agent_not_shared(client, monkeypatch):
    """Two agents in the same channel must not collide on, or leak into,
    each other's rolling summary row -- ChatMessage.agent_id on the
    summary row itself is what keeps them independent (no new schema)."""
    import agent.dataops_agent as dataops_agent

    token, tenant_id, _ = await _register(client, "ctxB")
    nova_id = await _hire_agent(client, token, "Nova")
    atlas_id = await _hire_agent(client, token, "Atlas")
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": "General"})
    channel_id = r.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{atlas_id}", headers=_auth(token))

    fake_summarize = AsyncMock(return_value="Nova-only summary text.")
    monkeypatch.setattr(dataops_agent, "invoke_llm", fake_summarize)
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent({}))

    # One turn to Atlas first -- short, must never trigger summarization
    # and must never end up scoped under Nova's agent_id.
    await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "@Atlas quick check", "session_id": channel_id,
    })

    # 8 turns to Nova crosses CONTEXT_WINDOW_SIZE (12), matching the
    # private-session rolling-summary test's own iteration count.
    for i in range(8):
        r = await client.post("/api/v1/chat/", headers=_auth(token), json={
            "message": f"@Nova turn {i}", "session_id": channel_id,
        })
        assert r.status_code == 200

    fake_summarize.assert_called()

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == channel_id, ChatMessage.role == "summary",
        ))
        summary_rows = r.scalars().all()

    assert len(summary_rows) == 1
    assert summary_rows[0].agent_id == nova_id
    assert summary_rows[0].content == "Nova-only summary text."
