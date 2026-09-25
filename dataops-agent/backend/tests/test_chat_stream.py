import asyncio
import json
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from sqlalchemy import select

import agent.dataops_agent as dataops_agent
from services.tenant_context import tenant_session
from models.all_models import ChatMessage, LlmUsageEvent
from services.quota_service import PLANS


@tool
async def fake_lookup_tool(x: str = "") -> str:
    """Look something up (test-only fake tool)."""
    return f"found: {x}"


class FakeToolCallLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self._responses.pop(0)


def unique_email(prefix="chatstream"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _register(client, prefix="chatstream"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": unique_email(prefix), "password": "test1234",
        "full_name": "Chat Stream Tester", "tenant_name": f"Chat Stream Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    """Parses a raw SSE byte stream (already decoded to text) of
    `event: X\\ndata: {...}\\n\\n` frames into a list of (event, payload)
    tuples, in order — mirrors exactly what a browser EventSource / the
    frontend's fetch-based SSE reader would see."""
    events = []
    for block in raw_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event_type is not None:
            events.append((event_type, data))
    return events


@pytest.mark.asyncio
async def test_chat_stream_happy_path_emits_expected_events_and_persists_like_buffered(client, monkeypatch):
    """POST /api/v1/chat/stream must emit tool_start -> tool_end -> done
    (no token events here since FakeToolCallLLM isn't a real streaming
    Runnable — see test_agent_stream.py for token-level proof) and must
    persist the exact same ChatMessage shape POST /api/v1/chat/ does:
    one user row, one assistant row carrying the real tool_calls trace."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_lookup_tool", "args": {"x": "widgets"}, "id": "call_1"},
        ]),
        AIMessage(content="Found widgets."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token, tenant_id, user_id = await _register(client)

    chunks = []
    async with client.stream(
        "POST", "/api/v1/chat/stream", json={"message": "look up widgets"}, headers=_auth(token),
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for chunk in response.aiter_text():
            chunks.append(chunk)
    events = _parse_sse("".join(chunks))

    event_types = [e for e, _ in events]
    # `start` is always first -- the responding agent is resolved before
    # _run_agent_and_persist_stream is even scheduled, not just known by
    # `done`.
    assert event_types[0] == "start"
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert event_types[-1] == "done"
    assert event_types.index("tool_start") < event_types.index("tool_end") < event_types.index("done")

    start = next(d for e, d in events if e == "start")
    assert "agent_id" in start
    assert start["session_id"]

    tool_start = next(d for e, d in events if e == "tool_start")
    assert tool_start["name"] == "fake_lookup_tool"
    assert "widgets" in tool_start["args_summary"]

    tool_end = next(d for e, d in events if e == "tool_end")
    assert tool_end["name"] == "fake_lookup_tool"
    assert tool_end["ok"] is True

    done = next(d for e, d in events if e == "done")
    assert done["message_id"]
    # session_id (Stage 1 follow-up) must always be present, including
    # when the client already supplied one -- a sessionless first message
    # needs this to learn its server-generated id, but a client that
    # already had one must see it echoed back unchanged too.
    assert done["session_id"]
    # start and done must agree on both fields -- the same resolved agent
    # and the same session, from the first event to the last.
    assert start["session_id"] == done["session_id"]
    assert start["agent_id"] == done["agent_id"]

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.tenant_id == tenant_id, ChatMessage.user_id == user_id,
        ).order_by(ChatMessage.created_at.asc()))
        rows = r.scalars().all()

    assert len(rows) == 2
    user_row, assistant_row = rows
    assert user_row.role == "user"
    assert user_row.content == "look up widgets"
    # The request never supplied a session_id -- done["session_id"] must be
    # the real, server-generated one the rows actually landed under, not
    # just any non-empty string.
    assert done["session_id"] == user_row.session_id == assistant_row.session_id
    assert assistant_row.role == "assistant"
    assert assistant_row.id == done["message_id"]
    assert assistant_row.content == "Found widgets."
    assert len(assistant_row.tool_calls) == 1
    assert assistant_row.tool_calls[0]["tool"] == "fake_lookup_tool"
    assert assistant_row.tool_calls[0]["result"] == "found: widgets"
    assert assistant_row.tool_calls[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_chat_stream_approval_required_event_matches_a_real_persisted_approval(client, monkeypatch):
    """A blocked tool call must produce an `approval_required` SSE event
    carrying the id of a real, committed ApprovalRequest row -- not just a
    generic notice -- exactly the row the Approvals screen would show,
    plus that row's real risk_level/reason (Stage 1 follow-up) so the live
    notice can say what's actually being asked instead of a generic
    banner."""
    from models.approval_model import ApprovalRequest

    @tool
    async def risky_tool(x: str = "") -> str:
        """Test-only fake tool sharing a real RISK_ACTIONS-style name."""
        return f"did: {x}"

    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "risky_tool", "args": {"x": "risky"}, "id": "call_1"},
        ]),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [risky_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"risky_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: True)
    monkeypatch.setattr(dataops_agent, "get_risk_level", lambda action: "high")
    dataops_agent._cache.clear()

    token, tenant_id, user_id = await _register(client, "approvalstream")

    chunks = []
    async with client.stream(
        "POST", "/api/v1/chat/stream", json={"message": "do the risky thing"}, headers=_auth(token),
    ) as response:
        assert response.status_code == 200
        async for chunk in response.aiter_text():
            chunks.append(chunk)
    events = _parse_sse("".join(chunks))

    approval_events = [d for e, d in events if e == "approval_required"]
    assert len(approval_events) == 1
    event = approval_events[0]
    approval_id = event["approval_request_id"]

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))
        approval = r.scalar_one()
    assert approval.tenant_id == tenant_id
    assert approval.action_name == "risky_tool"
    # The event's risk_level/reason must be the exact values that landed
    # on the real row -- not just any non-empty string -- so a mismatch
    # here (e.g. a stale copy taken before the row's defaults applied)
    # would fail loudly instead of looking coincidentally right.
    assert event["risk_level"] == approval.risk_level == "high"
    assert event["reason"] == approval.reason
    assert approval.reason


@pytest.mark.asyncio
async def test_chat_stream_done_echoes_a_client_supplied_session_id(client, monkeypatch):
    """When the client already supplied a session_id, `done` must echo
    that exact value back, not just any server-generated one -- the
    "always present" requirement covers both the sessionless and the
    already-has-one cases."""
    fake_llm = FakeToolCallLLM([AIMessage(content="hi there")])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token, tenant_id, user_id = await _register(client, "clientsession")
    client_session_id = str(uuid.uuid4())

    chunks = []
    async with client.stream(
        "POST", "/api/v1/chat/stream",
        json={"message": "hello", "session_id": client_session_id}, headers=_auth(token),
    ) as response:
        assert response.status_code == 200
        async for chunk in response.aiter_text():
            chunks.append(chunk)
    events = _parse_sse("".join(chunks))

    start = next(d for e, d in events if e == "start")
    assert start["session_id"] == client_session_id

    done = next(d for e, d in events if e == "done")
    assert done["session_id"] == client_session_id


@pytest.mark.asyncio
async def test_chat_stream_quota_exceeded_returns_402_not_sse(client):
    """Quota enforcement must complete BEFORE the stream opens — a
    tenant over its ai_credits limit gets a normal 402 JSON error body,
    never an SSE `error` event (which would require a 200 + an open
    stream first)."""
    token, tenant_id, _ = await _register(client, "quotastream")
    limit = PLANS["starter"]["ai_credits_per_month"]
    async with tenant_session(tenant_id) as db:
        db.add(LlmUsageEvent(
            id=str(uuid.uuid4()), tenant_id=tenant_id, request_type="test",
            provider="test", model="test", used_fallback=False,
            input_tokens=limit, output_tokens=0, total_tokens=limit, success=True,
        ))
        await db.commit()

    r = await client.post(
        "/api/v1/chat/stream", json={"message": "hello"}, headers=_auth(token),
    )
    assert r.status_code == 402
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"]["error"] == "quota_exceeded"
    assert r.json()["detail"]["resource"] == "ai_credits"


@pytest.mark.asyncio
async def test_chat_stream_mid_disconnect_still_persists_a_complete_row(client, monkeypatch):
    """The whole point of running the agent + persistence in a background
    task decoupled from the SSE generator: a client that reads a couple
    of frames and then disconnects must not truncate what gets saved.
    Simulates a real client hang-up by opening the stream, reading only
    the first frame, then exiting the `async with` block early (which
    closes the response and, per Starlette's disconnect-detection, tells
    the ASGI app the client is gone) — then polls the DB directly (no way
    to observe this via the now-closed HTTP response) to confirm the full,
    untruncated assistant row still landed, exactly as the happy-path
    test above asserts for a client that stayed connected throughout."""
    fake_llm = FakeToolCallLLM([
        AIMessage(content="", tool_calls=[
            {"name": "fake_lookup_tool", "args": {"x": "gadgets"}, "id": "call_1"},
        ]),
        AIMessage(content="Found gadgets, the full real answer."),
    ])
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent", lambda temperature=0.0, primary_model=None: fake_llm)
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS", [fake_lookup_tool])
    monkeypatch.setattr(dataops_agent, "TOOL_CAPABILITIES", {"fake_lookup_tool": "view"})
    monkeypatch.setattr(dataops_agent, "requires_approval", lambda action, mode: False)
    dataops_agent._cache.clear()

    token, tenant_id, user_id = await _register(client, "disconnectstream")

    async with client.stream(
        "POST", "/api/v1/chat/stream", json={"message": "look up gadgets"}, headers=_auth(token),
    ) as response:
        assert response.status_code == 200
        # Read exactly one chunk off the wire, then abandon the response —
        # the real work (agent run + persistence) is still in flight on
        # the server as its own asyncio.Task at this point.
        async for _chunk in response.aiter_text():
            break
    # `async with` exiting here closes the response without draining the
    # rest of the body -- the httpx/ASGI equivalent of a client hanging up
    # mid-stream.

    # The background task is not awaited by the request/response cycle at
    # all (see _run_agent_and_persist_stream's docstring), so give it a
    # moment to actually finish writing before asserting against the DB.
    assistant_row = None
    for _ in range(50):
        async with tenant_session(tenant_id) as db:
            r = await db.execute(select(ChatMessage).where(
                ChatMessage.tenant_id == tenant_id, ChatMessage.user_id == user_id,
                ChatMessage.role == "assistant",
            ))
            assistant_row = r.scalar_one_or_none()
        if assistant_row is not None:
            break
        await asyncio.sleep(0.1)

    assert assistant_row is not None, "assistant ChatMessage row was never persisted after a mid-stream disconnect"
    assert assistant_row.content == "Found gadgets, the full real answer."
    assert len(assistant_row.tool_calls) == 1
    assert assistant_row.tool_calls[0]["tool"] == "fake_lookup_tool"
    assert assistant_row.tool_calls[0]["result"] == "found: gadgets"
    assert assistant_row.tool_calls[0]["status"] == "completed"

    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.tenant_id == tenant_id, ChatMessage.user_id == user_id, ChatMessage.role == "user",
        ))
        user_row = r.scalar_one()
    assert user_row.content == "look up gadgets"
