import uuid
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

import agent.dataops_agent as dataops_agent
from database import AsyncSessionLocal
from models.all_models import ChatMessage
from langchain_core.tools import tool


@tool
async def fake_lookup_tool(x: str = "") -> str:
    """Look something up (test-only fake tool)."""
    return f"found: {x}"


def unique_email(prefix="chattest"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _register(client, prefix="chattest"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": unique_email(prefix), "password": "test1234",
        "full_name": "Chat Tester", "tenant_name": f"Chat Test Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()["access_token"], reg.json()["tenant_id"], reg.json()["user_id"]


class FakeToolCallLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self._responses.pop(0)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_chat_response_includes_tool_trace(client, monkeypatch):
    """A tool-calling turn must return a tool_calls trace in the response
    body reflecting the real tool actually executed — name, args, and the
    real (already-capped) result, not just the final text answer."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_lookup_tool", "args": {"x": "widgets"}, "id": "call_1"},
        ]),
        AIMessage(content="Found widgets."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token, tenant_id, user_id = await _register(client)
    r = await client.post("/api/v1/chat/", json={"message": "look up widgets"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()

    assert body["response"] == "Found widgets."
    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["tool"] == "fake_lookup_tool"
    assert call["args"] == {"x": "widgets"}
    assert call["result"] == "found: widgets"
    assert call["status"] == "completed"


@pytest.mark.asyncio
async def test_blocked_tool_call_shows_up_in_trace(client, monkeypatch):
    """A tool call blocked by the approval gate must still appear in the
    trace (status blocked_pending_approval, no result), not be silently
    dropped — the user should see AXIOM wanted to do something, not just
    that it stopped."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_lookup_tool", "args": {"x": "risky"}, "id": "call_1"},
        ]),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: True)
    dataops_agent._cache.clear()

    token, tenant_id, user_id = await _register(client)
    r = await client.post("/api/v1/chat/", json={"message": "do the risky thing"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()

    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["status"] == "blocked_pending_approval"
    assert body["tool_calls"][0]["result"] is None


@pytest.mark.asyncio
async def test_chat_sessions_list_is_scoped_to_the_requesting_user(client, monkeypatch):
    """GET /chat/sessions must be private per-user: two different users in
    two different tenants must each see only their own sessions, and a
    second user must never see the first user's session even by tenant_id
    coincidence (they're always different tenants here, but the query must
    filter on user_id too, not just tenant_id, for defense in depth)."""
    fake_llm = FakeToolCallLLM([AIMessage(content="hi there")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token_a, _, _ = await _register(client, "sessionsa")
    r = await client.post("/api/v1/chat/", json={"message": "hello from A"}, headers=_auth(token_a))
    session_a = r.json()["session_id"]

    fake_llm2 = FakeToolCallLLM([AIMessage(content="hi there")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm2)
    dataops_agent._cache.clear()
    token_b, _, _ = await _register(client, "sessionsb")
    r = await client.post("/api/v1/chat/", json={"message": "hello from B"}, headers=_auth(token_b))
    session_b = r.json()["session_id"]

    list_a = await client.get("/api/v1/chat/sessions", headers=_auth(token_a))
    list_b = await client.get("/api/v1/chat/sessions", headers=_auth(token_b))

    ids_a = {s["session_id"] for s in list_a.json()["sessions"]}
    ids_b = {s["session_id"] for s in list_b.json()["sessions"]}

    assert session_a in ids_a
    assert session_a not in ids_b
    assert session_b in ids_b
    assert session_b not in ids_a


@pytest.mark.asyncio
async def test_chat_sessions_list_shape_and_title(client, monkeypatch):
    """Each session summary must include a title derived from the first
    user message, real started_at/last_activity timestamps, and an accurate
    message_count (user + assistant messages both counted)."""
    fake_llm = FakeToolCallLLM([AIMessage(content="Paris is the capital.")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token, _, _ = await _register(client, "titletest")
    r = await client.post("/api/v1/chat/", json={"message": "What is the capital of France?"}, headers=_auth(token))
    session_id = r.json()["session_id"]

    r = await client.get("/api/v1/chat/sessions", headers=_auth(token))
    sessions = r.json()["sessions"]
    assert len(sessions) == 1
    s = sessions[0]
    assert s["session_id"] == session_id
    assert s["title"] == "What is the capital of France?"
    assert s["message_count"] == 2
    assert s["started_at"]
    assert s["last_activity"]


@pytest.mark.asyncio
async def test_session_history_includes_tool_calls(client, monkeypatch):
    """GET /chat/sessions/{id}/history must include each message's stored
    tool_calls trace, not just role/content — the assistant message that
    made the tool call should carry it."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_lookup_tool", "args": {"x": "gadgets"}, "id": "call_1"},
        ]),
        AIMessage(content="Found gadgets."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token, _, _ = await _register(client, "historytest")
    r = await client.post("/api/v1/chat/", json={"message": "look up gadgets"}, headers=_auth(token))
    session_id = r.json()["session_id"]

    r = await client.get(f"/api/v1/chat/sessions/{session_id}/history", headers=_auth(token))
    messages = r.json()["messages"]
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert len(assistant_msg["tool_calls"]) == 1
    assert assistant_msg["tool_calls"][0]["tool"] == "fake_lookup_tool"

    user_msg = next(m for m in messages if m["role"] == "user")
    assert user_msg["tool_calls"] == []


@pytest.mark.asyncio
async def test_long_session_persists_a_rolling_summary_row(client, monkeypatch):
    """Wunomo Projects Phase 0, commit 6: once a session's real history
    exceeds CONTEXT_WINDOW_SIZE, the turn that crosses that line must
    persist a real ChatMessage(role="summary") row - that's the only way
    the compression round-trips to the next request instead of re-growing
    unbounded token cost on every future turn."""
    fake_llm = FakeToolCallLLM([AIMessage(content=f"reply {i}") for i in range(8)])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    fake_summarize = AsyncMock(return_value="Session summary text.")
    monkeypatch.setattr(dataops_agent, "invoke_llm", fake_summarize)
    dataops_agent._cache.clear()

    token, tenant_id, _ = await _register(client, "longsession")
    session_id = None
    for i in range(8):
        r = await client.post(
            "/api/v1/chat/",
            json={"message": f"turn {i}", "session_id": session_id},
            headers=_auth(token),
        )
        assert r.status_code == 200
        session_id = r.json()["session_id"]

    fake_summarize.assert_called()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == session_id, ChatMessage.role == "summary",
        ))
        summary_rows = result.scalars().all()

    assert len(summary_rows) == 1
    assert summary_rows[0].content == "Session summary text."
