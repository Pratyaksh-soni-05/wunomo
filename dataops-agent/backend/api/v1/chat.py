import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from .auth import get_current_user, enforce_quota, enforce_agent_budget
from agent.dataops_agent import run_agent, run_agent_stream, window_and_summarize, _finalize_agent_result
from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, AgentInstanceStatus, Channel, ChannelUser, ChatMessage, Handoff, Task, TaskShape,
)
from sqlalchemy import select, func, delete
from datetime import datetime, timezone, timedelta
import uuid
from models.approval_model import ApprovalRequest, ApprovalStatus
from schemas.chat_schema import ChatRequest
from services.channel_routing import load_agent_channel_context, resolve_channel_message_target
from modules.orchestration.supervisor import parse_all_mentions, run_supervisor
from langchain_core.messages import AIMessage as LCAIMessage, ToolMessage as LCToolMessage, SystemMessage as LCSystemMessage
import structlog

log = structlog.get_logger()

router = APIRouter()


def _extract_tool_trace(new_messages, blocked_tool_calls, role_denied_calls, scope_denied_calls=None) -> list[dict]:
    """Build a tool-call trace for this turn from the graph's own new messages:
    every AIMessage.tool_calls paired with its ToolMessage result (matched by
    tool_call_id), plus any tool calls approval_gate_node blocked before they
    ever reached ToolNode, plus any tool calls the role-permission gate
    stripped before approval_gate_node ever saw them (role_denied_calls —
    these are a distinct status from "blocked_pending_approval": a role
    denial can never later become approved, unlike a risk-blocked call, so
    the frontend must not offer the same "review on the Approvals screen"
    affordance for it), plus any tool calls the agent-scope gate stripped
    (scope_denied_calls, Wunomo Projects Phase 1 — a distinct status from
    role denial: the caller's role was fine, the calling agent just isn't
    scoped to the resolved source, and each entry already carries its own
    specific, legible reason naming the agent and source — see
    agent_scope_denial_reason — never a generic "permission denied").
    Tool outputs are already capped by cap_tool_result() before they enter
    this list (see agent/tools/_utils.py) — no re-truncation needed here."""
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
                    # A source-lock conflict (Wunomo Projects Phase 2, item 5)
                    # is discovered only AFTER the tool actually runs -- it
                    # returns a normal {"error": ..., "lock_conflict": True}
                    # result, not a pre-flight denial like scope/role. Without
                    # this check it renders identically to a real success
                    # (Wunomo Projects Phase 2 frontend, slice 9): a lock
                    # conflict in chat fails fast and does NOT retry on its
                    # own (contrast a task step, which pauses and the beat
                    # tick retries) -- the frontend needs a distinct status to
                    # say that correctly rather than relying on the LLM
                    # choosing to relay the raw error text.
                    try:
                        parsed = json.loads(result) if isinstance(result, str) else result
                    except (json.JSONDecodeError, TypeError):
                        parsed = None
                    if isinstance(parsed, dict) and parsed.get("lock_conflict"):
                        status = "denied_source_locked"
                else:
                    continue
                trace.append({
                    "tool": call["name"], "args": call["args"],
                    "result": result, "status": status,
                })
    for call in role_denied_calls:
        trace.append({
            "tool": call["name"], "args": call.get("args", {}),
            "result": None, "status": "denied_insufficient_role",
        })
    for call in (scope_denied_calls or []):
        # scope_denial (Wunomo Projects Phase 2 frontend, slice 9) carries
        # the structured {agent_id, agent_name, source_id, source_name} the
        # frontend needs to render a real "grant access" link pre-scoped to
        # this exact agent/source -- not just the prose reason string.
        scope_denial = call.get("scope_denial") or {}
        trace.append({
            "tool": call["name"], "args": call.get("args", {}),
            "result": None, "status": "denied_out_of_scope", "reason": call.get("reason"),
            "agent_id": scope_denial.get("agent_id"), "agent_name": scope_denial.get("agent_name"),
            "source_id": scope_denial.get("source_id"), "source_name": scope_denial.get("source_name"),
        })
    return trace

def _no_route_response(session_id: str, text: str) -> dict:
    """Returned when a channel message can't be routed to a real agent
    (an unresolved @mention, or ambiguity with no mention at all) --
    never a guess, matching the "never guess" rule Tier 1 argument
    resolution already established for task execution."""
    return {
        "session_id": session_id, "response": text, "provider": None,
        "pending_approvals": [], "tool_calls": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/")
async def chat(req: ChatRequest, user=Depends(enforce_quota("ai_credits"))):
    session_id = req.session_id or str(uuid.uuid4())
    tenant_id = user["tenant_id"]
    message_text = req.message
    mentioned_agent_id = None

    async with AsyncSessionLocal() as db:
        # Wunomo Projects Phase 2: a channel's messages use its own real
        # id as their session_id, by convention (see models/all_models.py's
        # Channel docstring) -- no schema flag needed, just a real-row
        # lookup against this session_id.
        r = await db.execute(select(Channel).where(Channel.id == session_id, Channel.tenant_id == tenant_id))
        channel = r.scalar_one_or_none()

        if channel is not None:
            # Channel membership replaces the private-session ownership
            # check below -- multiple users legitimately share a channel.
            r = await db.execute(select(ChannelUser).where(
                ChannelUser.channel_id == channel.id, ChannelUser.user_id == user["sub"],
            ))
            if r.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="You are not a member of this channel.")

            # @mention routing: the tagged agent responds, nobody else.
            # Resolved against real channel_agents membership -- an agent
            # not added to this channel cannot be mentioned into it,
            # regardless of what its name looks like in the message text.
            # Shared with the channel-upload endpoint (Wunomo Projects
            # Phase 4, api/v1/channels.py) via resolve_channel_message_
            # target() -- one real implementation of "which agent does
            # this address," not two that could quietly diverge.
            resolved_agent_id, route_error, remaining_text = await resolve_channel_message_target(
                db, channel.id, tenant_id, req.message,
            )
            if route_error is not None:
                return _no_route_response(session_id, route_error)
            agent_id = resolved_agent_id
            mentioned_agent_id = resolved_agent_id
            message_text = remaining_text or req.message

            # Context filtering, reading (a) (Wunomo Projects Phase 2):
            # an agent sees only messages it authored or was mentioned
            # in, within this channel -- enforced by this query, never
            # by a prompt instruction. See load_agent_channel_context's
            # own docstring for reading (b)'s known limitation
            # (content-aware redaction is not implemented).
            history_msgs, summary_row = await load_agent_channel_context(db, channel.id, tenant_id, agent_id)
        else:
            # Ownership check: a session_id may only be continued by the
            # user who started it. GET /sessions and GET /sessions/{id}/
            # history have always filtered by user_id -- this write path
            # never did, meaning any tenant member who knew (or was
            # given, or guessed) another user's session_id could post
            # into it and silently ride along on that session's turn. A
            # brand-new session_id (no rows yet) has no owner to
            # conflict with, so it's always allowed.
            r = await db.execute(select(ChatMessage.user_id).where(
                ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id,
            ).limit(1))
            existing_owner = r.scalar_one_or_none()
            if existing_owner is not None and existing_owner != user["sub"]:
                raise HTTPException(status_code=403, detail="This session belongs to a different user.")

            # Context windowing (Wunomo Projects Phase 0, commit 6): find
            # the most recent already-persisted summary for this session,
            # if any — everything at or before it is already compressed,
            # so only real turns strictly after that point need to be
            # loaded and re-passed to window_and_summarize(). The
            # original raw rows are never deleted (a customer can still
            # scroll back through real history in the UI); this only
            # changes what gets replayed to the LLM.
            r = await db.execute(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id,
                ChatMessage.user_id == user["sub"], ChatMessage.role == "summary",
            ).order_by(ChatMessage.created_at.desc()).limit(1))
            summary_row = r.scalar_one_or_none()

            query = select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id,
                ChatMessage.user_id == user["sub"], ChatMessage.role.in_(("user", "assistant")),
            )
            if summary_row is not None:
                query = query.where(ChatMessage.created_at > summary_row.created_at)
            r = await db.execute(query.order_by(ChatMessage.created_at.asc()).limit(200))
            history_msgs = r.scalars().all()

            # Wunomo Projects Phase 1: resolve the tenant's real agent so
            # the scope gate (agent_scope_denied_tool_calls, see
            # agent_node) has an actual agent_id to check against —
            # without this, run_agent() falls back to its exact
            # pre-Phase-0 behavior and the scope gate is a permanent
            # no-op. Every private-chat tenant has exactly one agent
            # today (AXIOM) -- take the oldest ACTIVE one
            # deterministically. A tenant with zero agent rows
            # (shouldn't happen post-backfill) falls back to
            # agent_id=None, the same transitional no-op as before.
            r = await db.execute(select(AgentInstance).where(
                AgentInstance.tenant_id == tenant_id, AgentInstance.status == AgentInstanceStatus.ACTIVE,
            ).order_by(AgentInstance.created_at.asc()).limit(1))
            agent_row = r.scalar_one_or_none()
            agent_id = agent_row.id if agent_row is not None else None

    # Gate 2 of the two-gate token-budget path (Wunomo Projects Phase 1,
    # part two) - the tenant-level gate already ran as enforce_quota's
    # own dependency above; this is the agent-level one, checked as soon
    # as a real agent_id exists and before any further LLM spend
    # (summarization included) happens for this turn.
    await enforce_agent_budget(agent_id)

    from langchain_core.messages import HumanMessage, AIMessage
    history = []
    for m in history_msgs:
        if m.role == "user":
            history.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            history.append(AIMessage(content=m.content))

    # Windowing/summarization applies identically whether this history
    # came from a private session or a channel's already-agent-filtered
    # query above -- window_and_summarize() itself doesn't know or care
    # which. For a channel, the resulting summary row is scoped to this
    # agent (see the persistence block below), matching how
    # load_agent_channel_context() looked it up.
    history, new_summary = await window_and_summarize(
        history, tenant_id=tenant_id, session_id=session_id,
        prior_summary=summary_row.content if summary_row is not None else None,
    )

    result = await run_agent(
        user_message=message_text, tenant_id=tenant_id, user_id=user["sub"],
        session_id=session_id, caller_role=user["role"], personality_mode=req.personality_mode,
        operation_mode=req.operation_mode, history=history, context=req.context,
        agent_id=agent_id,
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
        tool_trace = _extract_tool_trace(
            new_messages, result["pending_approvals"], result.get("role_denied", []),
            result.get("scope_denied", []),
        )

        if new_summary is not None:
            # Only ever written when window_and_summarize() actually moved
            # the window this turn (see its own docstring) - not on every
            # turn. role="summary" is a plain string in an already-
            # unconstrained column, not new schema; the loading query
            # above is what makes this row authoritative for future turns
            # (everything at or before it is excluded from the next load).
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                session_id=session_id, role="summary", content=new_summary,
                personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                created_at=datetime.utcnow(),
                agent_id=(agent_id if channel is not None else None),
            ))

        # mentioned_agent_id (Wunomo Projects Phase 2) is only ever set on
        # the user's own message -- it names who THEY addressed, not who
        # produced the reply. agent_id on the assistant's reply names the
        # real agent that answered (previously always left NULL on every
        # ChatMessage row here, even in private chat) -- required the
        # moment a channel can hold more than one agent, since otherwise
        # replies in the transcript would be visually indistinguishable.
        for role, content, calls, msg_agent_id, msg_mentioned_agent_id in [
            ("user", req.message, [], None, mentioned_agent_id),
            ("assistant", result["response"], tool_trace, agent_id, None),
        ]:
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                session_id=session_id, role=role, content=content,
                agent_id=msg_agent_id, mentioned_agent_id=msg_mentioned_agent_id,
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


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


# Sentinel telling chat_stream()'s SSE generator the background task is
# done and no more frames are coming -- an object(), not None/False, so it
# can never collide with a real queued value.
_STREAM_DONE = object()


async def _run_agent_and_persist_stream(
    queue: "asyncio.Queue", *, message_text: str, tenant_id: str, user: dict,
    session_id: str, req: ChatRequest, agent_id, history: list, channel, mentioned_agent_id,
    new_summary,
) -> None:
    """The real work behind POST /api/v1/chat/stream: runs
    run_agent_stream(), relays each event onto `queue` as an SSE frame,
    then persists EXACTLY what POST /api/v1/chat/ persists above (same
    ChatMessage rows, same ApprovalRequest creation, same summary
    handling, via the same _extract_tool_trace()) — using
    _finalize_agent_result() (agent/dataops_agent.py) so the two routes
    can never quietly diverge on how a final AgentState becomes a
    response.

    Deliberately run as its own asyncio.Task (see chat_stream() below),
    never awaited inline inside the SSE generator: Starlette cancels the
    generator's own task when the HTTP client disconnects, but a plain
    `asyncio.create_task(...)` is not a child of that cancellation scope
    — cancelling the generator does not cancel this task, it just means
    nothing is reading `queue` anymore. The agent run and the persistence
    below always run to completion regardless of whether a client is
    still listening. That's what "write on stream close, not only on
    clean completion" requires: persisting only whatever text streamed
    before a disconnect would leave a truncated, not "complete", row.
    Both failure paths below (the agent run raising, or persistence
    itself failing) are caught so the `_STREAM_DONE` sentinel is always
    eventually queued — otherwise a client that stayed connected through
    an error would hang forever on `queue.get()`.
    """
    # The responding agent is already resolved by the caller (chat_stream())
    # before this task is ever scheduled -- known before the first token,
    # not just at the end. Emitted once, first, so the streaming placeholder
    # (§7.3.C) can carry the correct avatar for the whole turn instead of
    # only from `done` onward.
    await queue.put(_sse("start", {"agent_id": agent_id, "session_id": session_id}))

    accumulated_text: list[str] = []
    final_state = None
    try:
        async for ev in run_agent_stream(
            user_message=message_text, tenant_id=tenant_id, user_id=user["sub"],
            session_id=session_id, caller_role=user["role"], personality_mode=req.personality_mode,
            operation_mode=req.operation_mode, history=history, context=req.context,
            agent_id=agent_id,
        ):
            if ev["type"] == "token":
                accumulated_text.append(ev["delta"])
                await queue.put(_sse("token", {"delta": ev["delta"]}))
            elif ev["type"] == "tool_start":
                await queue.put(_sse("tool_start", {"name": ev["name"], "args_summary": ev["args_summary"]}))
            elif ev["type"] == "tool_end":
                await queue.put(_sse("tool_end", {
                    "name": ev["name"], "result_summary": ev["result_summary"], "ok": ev["ok"],
                }))
            elif ev["type"] == "final_state":
                final_state = ev["state"]
    except Exception as exc:
        log.error("chat_stream.agent_run_failed", error=str(exc), tenant_id=tenant_id, session_id=session_id)
        await queue.put(_sse("error", {
            "message": "AXIOM hit an error before finishing this response. Please try again.",
        }))

    try:
        if final_state is not None:
            result = _finalize_agent_result(final_state, session_id, tenant_id, user["sub"])
            new_messages = final_state["messages"][len(history):]
            tool_trace = _extract_tool_trace(
                new_messages, result["pending_approvals"], result.get("role_denied", []),
                result.get("scope_denied", []),
            )
        else:
            # The graph never reached its final state -- a real error
            # mid-run (a client disconnect never lands here, see the
            # docstring above: this function keeps running regardless).
            # Persist whatever text actually streamed so the row is still
            # a valid, complete row -- possibly partial content, but never
            # a missing one.
            result = {
                "response": "".join(accumulated_text) or "AXIOM hit an error before finishing this response.",
                "provider": None, "used_fallback": None, "usage": None, "pending_approvals": [],
            }
            tool_trace = []

        assistant_message_id = str(uuid.uuid4())
        # Carries risk_level/reason straight off the row just created (not
        # re-derived from `pa`) so the SSE payload can never drift from what
        # was actually persisted -- same values ApprovalRequest.risk_level/
        # reason end up holding after the defaults below apply.
        created_approvals: list[dict] = []
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
                    created_approvals.append({
                        "approval_request_id": approval.id,
                        "risk_level": approval.risk_level,
                        "reason": approval.reason,
                    })

            if new_summary is not None:
                db.add(ChatMessage(
                    id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                    session_id=session_id, role="summary", content=new_summary,
                    personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                    created_at=datetime.utcnow(),
                    agent_id=(agent_id if channel is not None else None),
                ))

            for role, content, calls, msg_id, msg_agent_id, msg_mentioned_agent_id in [
                ("user", req.message, [], str(uuid.uuid4()), None, mentioned_agent_id),
                ("assistant", result["response"], tool_trace, assistant_message_id, agent_id, None),
            ]:
                db.add(ChatMessage(
                    id=msg_id, tenant_id=tenant_id, user_id=user["sub"],
                    session_id=session_id, role=role, content=content,
                    agent_id=msg_agent_id, mentioned_agent_id=msg_mentioned_agent_id,
                    personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                    tool_calls=calls, created_at=datetime.utcnow(),
                ))
            await db.commit()

        for created in created_approvals:
            await queue.put(_sse("approval_required", created))

        await queue.put(_sse("done", {
            "message_id": assistant_message_id,
            "session_id": session_id,
            "provider": result.get("provider"),
            "used_fallback": result.get("used_fallback"),
            "usage": result.get("usage"),
            # The agent that actually produced this turn's response --
            # same value just persisted as this ChatMessage row's agent_id.
            # Lets the live-streaming placeholder message (§7.3.C) resolve
            # its avatar without waiting for the post-done history refetch.
            "agent_id": agent_id,
        }))
    except Exception as exc:
        log.error("chat_stream.persistence_failed", error=str(exc), tenant_id=tenant_id, session_id=session_id)
        await queue.put(_sse("error", {
            "message": "Your message was received but saving the response failed. Please refresh and check history.",
        }))
    finally:
        await queue.put(_STREAM_DONE)


def _stream_response(queue: "asyncio.Queue") -> StreamingResponse:
    """Shared by both chat_stream() branches (single-agent and
    supervisor) -- the SSE plumbing itself (drain `queue` until
    _STREAM_DONE, wrap in a StreamingResponse with the same headers) is
    identical either way; only which background task feeds the queue
    differs."""
    async def event_source():
        while True:
            item = await queue.get()
            if item is _STREAM_DONE:
                break
            yield item

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def _run_supervisor_and_stream(
    queue: "asyncio.Queue", *, message_text: str, tenant_id: str, user: dict,
    session_id: str, req: ChatRequest, channel: Channel,
) -> None:
    """The multi-agent sibling of _run_agent_and_persist_stream -- a
    message resolving to two or more @mentions runs through
    run_supervisor() (modules/orchestration/supervisor.py) instead of the
    single-agent graph, chosen by chat_stream() itself before either path
    starts.

    run_supervisor() is still a single blocking call that internally loops
    run_node/handoff_node until nothing more is ready -- this function
    still can't return anything to the client until the whole DAG drains
    -- but every dispatched sub-task now streams for real while that's
    happening: modules/orchestration/supervisor.py's _run_one_task uses
    run_agent_stream() (the same generator the single-agent path consumes)
    and relays its token/tool_start/tool_end events, tagged with
    task_id/agent_id, through the `sink` closure below -- passed all the
    way down as SupervisorState's event_sink. Parallel tasks in the same
    wave run via asyncio.gather and stream concurrently; interleaved
    events for different task_ids on the same `queue` are the expected
    shape (asyncio.Queue.put is safe from multiple coroutines at once),
    not something serialized away. A `supervisor_task` "queued" ack fires
    the moment dispatch_node creates each Task row -- before this function
    has any results at all -- so the client learns who's answering before
    anyone has answered anything (§7.3.B).

    Persistence now happens at the source too: supervisor.py's own
    _persist_task_completion_message writes the ChatMessage for a
    completed task's real response (never a fabricated "OK, working on
    it" placeholder) the moment that task actually completes -- inside
    _run_one_task for the initial wave here, but also inside
    resolve_task_approval() for a task that completes later from a human's
    approval click, an entirely separate HTTP request this function never
    sees. Reading `result["tasks"]` back here for persistence, the
    original design, could never have covered that second case: this
    function only exists while run_supervisor() is actually running.

    The `error` (refusal) outcome persists nothing at all, matching the
    existing single-mention _no_route_response()'s own "this never really
    happened" precedent.
    """
    await queue.put(_sse("start", {"agent_id": None, "session_id": session_id}))

    async def sink(event_type: str, data: dict) -> None:
        await queue.put(_sse(event_type, data))

    # Captured before run_supervisor() runs, not after it returns (item 4a,
    # blueprint chrome pass screenshot review -- found live: a "Started
    # task" ack rendered ABOVE the user message that caused it). This
    # function's own ChatMessage rows below are only persisted once
    # run_supervisor() has already fully drained the turn -- including
    # running Nova's task to its approval pause -- so a plain
    # datetime.utcnow() called at persistence time gave the user's own
    # message a created_at LATER than the live "queued" acks dispatch_node
    # already streamed to the client while run_supervisor() was still
    # running. Every live per-task event is tagged with a client-side
    # timestamp captured as it arrives, which is necessarily before
    # run_supervisor() returns -- so the user's own message needs a
    # timestamp from before that call too, for GET .../history to ever
    # reconstruct the same order the live turn actually rendered in.
    turn_started_at = datetime.utcnow()

    try:
        result = await run_supervisor(
            tenant_id=tenant_id, channel_id=channel.id, project_id=channel.project_id,
            user_id=user["sub"], caller_role=user["role"], message=message_text,
            event_sink=sink,
        )
    except Exception as exc:
        log.error("chat_stream.supervisor_run_failed", error=str(exc), tenant_id=tenant_id, session_id=session_id)
        await queue.put(_sse("error", {
            "message": "AXIOM hit an error coordinating this multi-agent request. Please try again.",
            "kind": None,
        }))
        await queue.put(_STREAM_DONE)
        return

    try:
        if result.get("error"):
            await queue.put(_sse("error", {"message": result["error"], "kind": result.get("error_kind")}))
            await queue.put(_sse("done", {
                "message_id": None, "session_id": session_id, "provider": None,
                "used_fallback": None, "usage": None, "agent_id": None,
            }))
            return

        async with AsyncSessionLocal() as db:
            # The user's own message persists here (unlike the refusal
            # branch above) -- real Task/Handoff rows exist for this
            # turn, so the visible transcript must not lose the message
            # that caused them. mentioned_agent_id stays None: it's a
            # single-agent column, and no one value is honest for a
            # multi-mention message.
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                session_id=session_id, role="user", content=req.message,
                agent_id=None, mentioned_agent_id=None,
                personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                tool_calls=[], created_at=turn_started_at,
            ))

            # An @mention naming a real agent who isn't on this channel/
            # tenant -- the multi-agent equivalent of the single-mention
            # path's route_error, surfaced the same way shape I already
            # covers (§7.3.I), not a new event type.
            for u in result.get("unresolved_mentions", []):
                await queue.put(_sse("system_line", {"text": u["reason"]}))

            # Dispatched tasks: no persistence or `supervisor_task` event
            # happens here anymore -- both now happen at the source, live,
            # inside supervisor.py's own dispatch_node (the "queued" ack)
            # and _run_one_task (running/completed/failed/paused, plus the
            # ChatMessage for a real completion), relayed through the
            # `sink` closure above as run_supervisor() executes rather than
            # reconstructed here after the fact. This is also what makes a
            # task that finishes LATER -- via a retry or a human's
            # approval click, an entirely separate HTTP request with no
            # `result["tasks"]` to read back -- persist its answer at all;
            # reading it only from this function's own `result` never
            # could.
            #
            # Every inferred edge is surfaced, never silent -- one system
            # line per entry, same shape I unresolved_mentions above uses.
            # Persisted, unlike unresolved_mentions: this explains WHY a
            # real, now-permanent Task row is ordered the way it is --
            # losing it on refresh would leave the dispatched agents'
            # real replies (which DO persist, above) with no visible
            # explanation for their ordering. role="system_notice" (see
            # _handoff_entries' own comment on this free-text value) --
            # a system-authored note, not any one agent's own words.
            for notice_index, notice in enumerate(result.get("inferred_edge_notices", [])):
                # turn_started_at + a tiny per-notice increment, not a fresh
                # datetime.utcnow() (same reasoning as the user message
                # above, and the same bug: a notice explains an edge
                # inferred during planning, before any task ran, but a
                # plain "now" here timestamps it after the whole turn
                # already drained). The increment keeps multiple notices
                # from tying exactly with each other or with the user
                # message while still sorting the whole group before any
                # live per-task event, which necessarily arrives later.
                db.add(ChatMessage(
                    id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"],
                    session_id=session_id, role="system_notice", content=notice,
                    agent_id=None, mentioned_agent_id=None,
                    personality_mode=req.personality_mode, operation_mode=req.operation_mode,
                    tool_calls=[], created_at=turn_started_at + timedelta(microseconds=notice_index + 1),
                ))
                await queue.put(_sse("system_line", {"text": notice}))

            # Partial dispatch: needs_clarification and dispatched `tasks`
            # above are not mutually exclusive -- both can be non-empty
            # on the same result, and both are emitted here, not
            # collapsed into one outcome.
            for ask in (result.get("needs_clarification") or []):
                await queue.put(_sse("needs_clarification", {
                    "question": ask["question"], "agents": ask["agents"], "options": ask["options"],
                }))

            # Handoffs already persist (dispatch_node/handoff_node,
            # unchanged by this pass) -- relayed live here from the real,
            # already-committed rows, not re-derived.
            for handoff_id in result.get("handoffs_created", []):
                handoff = await db.get(Handoff, handoff_id)
                if handoff is None:
                    continue
                from_agent = await db.get(AgentInstance, handoff.from_agent_id)
                to_agent = await db.get(AgentInstance, handoff.to_agent_id)
                await queue.put(_sse("handoff", {
                    "from_agent_id": handoff.from_agent_id,
                    "from_agent_name": from_agent.name if from_agent is not None else handoff.from_agent_id,
                    "to_agent_id": handoff.to_agent_id,
                    "to_agent_name": to_agent.name if to_agent is not None else handoff.to_agent_id,
                    "payload_summary": handoff.payload_summary,
                    "withheld": handoff.withheld,
                }))

            await db.commit()

        await queue.put(_sse("done", {
            "message_id": None, "session_id": session_id, "provider": None,
            "used_fallback": None, "usage": None, "agent_id": None,
        }))
    except Exception as exc:
        log.error("chat_stream.supervisor_persistence_failed", error=str(exc), tenant_id=tenant_id, session_id=session_id)
        await queue.put(_sse("error", {
            "message": "Your message was received but saving the response failed. Please refresh and check history.",
            "kind": None,
        }))
    finally:
        await queue.put(_STREAM_DONE)


@router.post("/stream")
async def chat_stream(req: ChatRequest, user=Depends(enforce_quota("ai_credits"))):
    """Streaming sibling of POST /api/v1/chat/ (above) — same channel/
    session resolution, same history load and windowing, same quota
    (Depends(enforce_quota("ai_credits")) below) and agent-budget gates,
    same persistence at the end. The only difference is that LLM/tool
    progress is relayed to the client as Server-Sent Events while it
    happens (via run_agent_stream(), agent/dataops_agent.py) instead of
    buffering the whole turn before returning one JSON body.

    POST /api/v1/chat/ itself is untouched by this route's existence —
    it still calls run_agent() exactly as before.

    Twelve event types, one JSON object per `data:` line -- the original
    seven are the single-agent path (unchanged, still the ONLY path for a
    message resolving to zero or one @mention); the five after are the
    supervisor path (a message resolving to two or more @mentions,
    checked by mention COUNT alone, before any target is resolved).
    token/tool_start/tool_end are now genuinely SHARED between both paths
    (not single-agent-only, as an earlier pass of this docstring said) --
    see below.
      start                {agent_id, session_id}
      token                {delta, task_id, agent_id}
      tool_start           {name, args_summary, task_id, agent_id}
      tool_end             {name, result_summary, ok, task_id, agent_id}
      approval_required    {approval_request_id, risk_level, reason}
      error                {message, kind}
      done                 {message_id, session_id, provider, used_fallback, usage, agent_id}
      supervisor_task      {task_id, agent_id, agent_name, status, response, message_id}
      system_line          {text}
      needs_clarification  {question, agents, options}
      handoff              {from_agent_id, from_agent_name, to_agent_id, to_agent_name, payload_summary, withheld}

    `error.kind` is only ever set on the supervisor path -- one of
    "ceiling" / "fan_in" / "cycle" for a hard refusal, or null for every
    other error (including the single-agent path's own, which never sets
    it at all). `agent_id` is null on `start`/`done` for the supervisor
    path -- no single agent is "the" responder to a multi-agent turn.

    `start` is always the first event, emitted before any token (single-
    agent path) or before run_supervisor() is even called (supervisor
    path) -- the responding agent, where there is exactly one, is already
    resolved by this function itself, above, before either background
    task is ever scheduled, so the client doesn't have to wait for `done`
    to know which agent is answering (§7.3.C's streaming avatar).

    The supervisor path now streams too: modules/orchestration/supervisor.py's
    _run_one_task uses run_agent_stream() (same as the single-agent path)
    for each dispatched sub-task, relaying its own token/tool_start/
    tool_end live through an event_sink threaded down from
    _run_supervisor_and_stream -- `task_id`/`agent_id` on each of those
    three events is how a client routes a given delta to the right message
    when several agents are running at once (parallel tasks stream
    genuinely concurrently; interleaved task_ids on these events is the
    expected shape, not a bug). `task_id`/`agent_id` are absent (never
    present, not merely null) on the single-agent path's own emissions of
    these same three event types -- there is only ever one message for
    them to belong to there.

    supervisor_task itself now fires up to three times per task, not once:
    "queued" the moment dispatch_node creates the Task row (before run_node
    has started a single one of these -- the acknowledgement §7.3.B needs,
    now genuinely immediate), "running" the moment _run_one_task actually
    starts it, then exactly one terminal status (completed/failed/
    paused_needs_approval). `response`/`message_id` are only ever non-null
    on that terminal "completed" emission.

    session_id is always present on `start` and `done`, including when the
    client supplied one -- a sessionless client (no session_id in the
    request, the private-chat "first message" case) otherwise has no way to
    learn the server-generated id from the stream. risk_level/reason on
    approval_required are read straight off the ApprovalRequest row just
    created (see _run_agent_and_persist_stream), not re-derived, so the
    live notice can say what's actually being asked instead of a generic
    banner.

    Quota/budget enforcement happens BEFORE the stream opens: this route's
    own Depends(enforce_quota("ai_credits")) above, and
    enforce_agent_budget() below, both run to completion — and therefore
    can both still raise a normal HTTPException (402) — before any
    StreamingResponse is constructed. A quota failure is always a normal
    JSON 402 response, never an SSE `error` event.

    Persistence and the actual agent run happen in a background
    asyncio.Task (_run_agent_and_persist_stream), independent of whether
    the HTTP client keeps reading — see that function's own docstring for
    why a disconnect never cancels it, and
    tests/test_chat_stream.py::test_mid_stream_disconnect_still_persists_a_complete_row
    for the proof.
    """
    session_id = req.session_id or str(uuid.uuid4())
    tenant_id = user["tenant_id"]
    message_text = req.message
    mentioned_agent_id = None

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Channel).where(Channel.id == session_id, Channel.tenant_id == tenant_id))
        channel = r.scalar_one_or_none()

        if channel is not None:
            r = await db.execute(select(ChannelUser).where(
                ChannelUser.channel_id == channel.id, ChannelUser.user_id == user["sub"],
            ))
            if r.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="You are not a member of this channel.")

            # Branch on mention COUNT alone, before resolving any target --
            # a message naming two or more agents goes to the supervisor
            # instead of resolve_channel_message_target()'s single-target
            # resolution. Zero or one mention (including the "no mention,
            # exactly one agent in the channel" auto-route case) takes the
            # existing path below completely unchanged -- that path is
            # proven and this pass must not touch it. The supervisor
            # branch needs no history/window/agent-budget prep at all
            # (run_supervisor()'s own dispatched tasks never take a
            # `history` argument -- see _run_supervisor_and_stream's
            # docstring), so it returns directly from inside this `async
            # with` block rather than falling through to that prep below.
            if len(parse_all_mentions(req.message)) >= 2:
                queue: asyncio.Queue = asyncio.Queue()
                asyncio.create_task(_run_supervisor_and_stream(
                    queue, message_text=req.message, tenant_id=tenant_id, user=user,
                    session_id=session_id, req=req, channel=channel,
                ))
                return _stream_response(queue)

            resolved_agent_id, route_error, remaining_text = await resolve_channel_message_target(
                db, channel.id, tenant_id, req.message,
            )
            if route_error is not None:
                # Nothing would ever have streamed -- same "never guess"
                # contract as the buffered route's _no_route_response, and
                # the same plain-JSON shape (not an SSE stream, since no
                # agent run ever starts).
                return _no_route_response(session_id, route_error)
            agent_id = resolved_agent_id
            mentioned_agent_id = resolved_agent_id
            message_text = remaining_text or req.message

            history_msgs, summary_row = await load_agent_channel_context(db, channel.id, tenant_id, agent_id)
        else:
            r = await db.execute(select(ChatMessage.user_id).where(
                ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id,
            ).limit(1))
            existing_owner = r.scalar_one_or_none()
            if existing_owner is not None and existing_owner != user["sub"]:
                raise HTTPException(status_code=403, detail="This session belongs to a different user.")

            r = await db.execute(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id,
                ChatMessage.user_id == user["sub"], ChatMessage.role == "summary",
            ).order_by(ChatMessage.created_at.desc()).limit(1))
            summary_row = r.scalar_one_or_none()

            query = select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id,
                ChatMessage.user_id == user["sub"], ChatMessage.role.in_(("user", "assistant")),
            )
            if summary_row is not None:
                query = query.where(ChatMessage.created_at > summary_row.created_at)
            r = await db.execute(query.order_by(ChatMessage.created_at.asc()).limit(200))
            history_msgs = r.scalars().all()

            r = await db.execute(select(AgentInstance).where(
                AgentInstance.tenant_id == tenant_id, AgentInstance.status == AgentInstanceStatus.ACTIVE,
            ).order_by(AgentInstance.created_at.asc()).limit(1))
            agent_row = r.scalar_one_or_none()
            agent_id = agent_row.id if agent_row is not None else None

    # Gate 2 of the two-gate token-budget path -- the tenant-level gate
    # already ran as this route's own Depends() above. Both this call and
    # that dependency complete (or raise a normal 402) before anything
    # below opens a StreamingResponse.
    await enforce_agent_budget(agent_id)

    from langchain_core.messages import HumanMessage, AIMessage
    history = []
    for m in history_msgs:
        if m.role == "user":
            history.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            history.append(AIMessage(content=m.content))

    history, new_summary = await window_and_summarize(
        history, tenant_id=tenant_id, session_id=session_id,
        prior_summary=summary_row.content if summary_row is not None else None,
    )

    queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(_run_agent_and_persist_stream(
        queue, message_text=message_text, tenant_id=tenant_id, user=user,
        session_id=session_id, req=req, agent_id=agent_id, history=history,
        channel=channel, mentioned_agent_id=mentioned_agent_id, new_summary=new_summary,
    ))
    return _stream_response(queue)


@router.get("/sessions")
async def list_sessions(user=Depends(get_current_user)):
    """Tenant-scoped AND user-scoped: sessions are private per-user (like the
    rest of this chat interface), not visible to other members of the same
    tenant — see CLAUDE.md Phase 8 for the reasoning.

    Excludes any session_id that's actually a real Channel's id (finding
    #70, WALKTHROUGH_FINDINGS_2026-08.md): a channel message's user_id is
    always the real posting user, so without this exclusion a channel a
    user has ever posted in shows up here as an ordinary private session
    — title, message count, and all — indistinguishable from a real 1:1
    AXIOM conversation. A channel's activity belongs exclusively to
    GET /api/v1/channels/, never here."""
    async with AsyncSessionLocal() as db:
        channel_ids = select(Channel.id).where(Channel.tenant_id == user["tenant_id"])
        r = await db.execute(
            select(
                ChatMessage.session_id,
                func.min(ChatMessage.created_at).label("started_at"),
                func.max(ChatMessage.created_at).label("last_activity"),
                func.count().label("message_count"),
            )
            .where(
                ChatMessage.tenant_id == user["tenant_id"], ChatMessage.user_id == user["sub"],
                ChatMessage.session_id.notin_(channel_ids),
            )
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


# Maps the real ApprovalStatus enum to a trace-status string the frontend
# can render distinctly from the still-pending "blocked_pending_approval"
# it's replacing. See _resolve_blocked_call_statuses' docstring for why
# this exists at all.
_APPROVAL_STATUS_TO_TRACE_STATUS = {
    ApprovalStatus.PENDING: "blocked_pending_approval",
    ApprovalStatus.APPROVED: "approval_approved",
    ApprovalStatus.REJECTED: "approval_rejected",
    ApprovalStatus.EXECUTED: "approval_executed",
    ApprovalStatus.FAILED: "approval_failed",
}


async def _resolve_blocked_call_statuses(db, tenant_id: str, session_id: str, msgs) -> list[dict]:
    """A blocked tool call is persisted with status "blocked_pending_approval"
    at write time and, until now, stayed frozen at that value forever in
    chat history — even after the real ApprovalRequest was later approved,
    rejected, or executed on the Approvals screen. This resolves each
    blocked call's *current* status at read time instead (a real, if
    coarse, join against ApprovalRequest — no push infrastructure, per the
    locked cheap-fix design in FRONTEND_BUILD_PLAN.md's P1 list).

    ApprovalRequest doesn't store the LangChain tool_call_id, so it can't
    be joined on exactly — correlated instead by (tenant_id, session_id,
    action_name) in chronological order, consuming one ApprovalRequest per
    matching blocked call as they're encountered. Correct in the common
    case (no more than one concurrently-blocked call per action_name per
    session); a real tool_call_id column would be needed for a fully
    precise join, out of scope for this cheap version.
    """
    ar = await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.tenant_id == tenant_id, ApprovalRequest.session_id == session_id)
        .order_by(ApprovalRequest.created_at.asc())
    )
    pending_by_action: dict[str, list[ApprovalRequest]] = {}
    for approval in ar.scalars().all():
        pending_by_action.setdefault(approval.action_name, []).append(approval)

    resolved_messages = []
    for m in msgs:
        calls = [dict(c) for c in (m.tool_calls or [])]
        for call in calls:
            if call.get("status") != "blocked_pending_approval":
                continue
            queue = pending_by_action.get(call.get("tool"))
            if not queue:
                continue
            approval = queue.pop(0)
            call["status"] = _APPROVAL_STATUS_TO_TRACE_STATUS.get(approval.status, call["status"])
            call["approval_id"] = approval.id
            if approval.execution_result is not None:
                call["result"] = approval.execution_result
        resolved_messages.append({
            "role": m.role, "content": m.content, "tool_calls": calls,
            "timestamp": str(m.created_at),
            # Already stored on every ChatMessage row (see the model's own
            # comment) but never serialized out until now -- the frontend
            # needs a real per-message agent identity to color an avatar by
            # employee_type (§7.4/§7.3.B-C); resolving that against a
            # guess instead of this real column was exactly the wrong
            # trade-off once a channel has more than one agent in it.
            "agent_id": m.agent_id, "mentioned_agent_id": m.mentioned_agent_id,
        })
    return resolved_messages


async def _task_card_entries(db, tenant_id: str, user_id: str, session_id: str) -> list[dict]:
    """Wunomo Projects Phase 4 frontend, slice 11: the inline "Started
    task: ..." card shown when a task is created from chat was purely
    client-side state (LocalChatMessage.taskCard) that never survived a
    session switch or page reload -- the write side (originating_session_id
    getting set) was already correct; nothing ever read it back. Computed
    fresh here from the real, already-persisted Task rows rather than a
    second stored copy that could drift -- the same principle behind every
    other *_reason() helper in api/v1/tasks.py. Interleaved into the real
    message timeline by created_at below, matching where the card actually
    appeared the first time (right after the message that triggered it).

    Excludes SUPERVISOR_INTENT tasks (blueprint chrome pass,
    feature/blueprint-workspace-chrome) -- a supervisor-dispatched task
    already gets full representation in the thread through its own
    ChatMessage row (an acknowledgement/result) and, when it has a
    dependent, a Handoff row -- this card was never designed to represent
    that path, it just wasn't filtered against it. Found live during this
    pass's own screenshot-verification loop: every supervisor task in a
    channel rendered TWICE, once as this generic "Started task: ... [View
    progress]" card and again as its real B/D-shaped message -- and the
    card's own timestamp (a bare str(datetime), pre-existing) sorting
    against a mis-parsed-without-Z reading of it made the duplicate appear
    to render before the user's own message that triggered it, which is
    what surfaced this in the first place. The original manual-task-card
    case this function was built for (TaskCreateModal, still real on
    /chat) is unaffected -- that path never sets task_shape to
    SUPERVISOR_INTENT."""
    r = await db.execute(select(Task).where(
        Task.tenant_id == tenant_id, Task.user_id == user_id, Task.originating_session_id == session_id,
        Task.task_shape != TaskShape.SUPERVISOR_INTENT,
    ).order_by(Task.created_at.asc()))
    return [
        {
            "role": "assistant", "content": "", "tool_calls": [], "timestamp": str(t.created_at),
            "taskCard": {"id": t.id, "goal": t.goal},
        }
        for t in r.scalars().all()
    ]


async def _handoff_entries(db, tenant_id: str, channel_id: str) -> list[dict]:
    """Same established pattern as _task_card_entries() just above --
    computed fresh from the real, already-persisted Handoff rows (written
    by the supervisor's handoff_node, unchanged by this pass) rather than
    a second stored copy, interleaved into the real message timeline by
    created_at. role="system_notice" (a free-text value on this
    already-unconstrained column, same precedent as role="summary")
    rather than "assistant" -- a handoff is a system event between two
    agents, not one agent's own words, and the frontend must render it
    distinctly (§7.3.F) rather than as if AXIOM said it.

    Not user_id-scoped like _task_card_entries() is: a Handoff belongs to
    the channel as a whole (two agents, no initiating human), so every
    member sees the same handoffs regardless of which of them triggered
    the underlying dispatch -- deliberately different from task cards,
    which are private per the user who started them."""
    r = await db.execute(select(Handoff).where(
        Handoff.tenant_id == tenant_id, Handoff.channel_id == channel_id,
    ).order_by(Handoff.created_at.asc()))
    handoffs = r.scalars().all()
    entries = []
    for h in handoffs:
        from_agent = await db.get(AgentInstance, h.from_agent_id)
        to_agent = await db.get(AgentInstance, h.to_agent_id)
        from_name = from_agent.name if from_agent is not None else h.from_agent_id
        to_name = to_agent.name if to_agent is not None else h.to_agent_id
        text = f"{from_name} handed over to {to_name}. {h.payload_summary}"
        if h.withheld:
            # Always [] today (see the Handoff model's own comment -- no
            # redaction logic exists yet), but the moment it isn't, this
            # is a privacy feature (§7.3.F), not decoration -- rendered
            # whenever present, same wording the live SSE `handoff` event
            # builds client-side for the pre-refresh view.
            text += f" ({to_name} did not receive: {', '.join(h.withheld)}.)"
        entries.append({
            "role": "system_notice", "content": text, "tool_calls": [],
            "timestamp": str(h.created_at), "agent_id": None, "mentioned_agent_id": None,
            # Structured fields matching the live "handoff" SSE event
            # exactly (api/v1/chat.py's own emission above) -- added so
            # §7.3.F's real card (separate from/to avatars, its own
            # payload_summary line, a distinctly-styled withheld line) can
            # render after a page reload too, not only for the live,
            # pre-refresh few seconds. Before this, a reload silently
            # downgraded a rendered Handoff card back to plain sentence
            # text (`content` above) with no way for the frontend to tell
            # the two apart -- `content` is kept for any caller that only
            # ever reads the flattened sentence, but a caller that wants
            # the real card checks for `from_agent_id` first.
            "from_agent_id": h.from_agent_id, "from_agent_name": from_name,
            "to_agent_id": h.to_agent_id, "to_agent_name": to_name,
            "payload_summary": h.payload_summary, "withheld": h.withheld,
        })
    return entries


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.tenant_id == user["tenant_id"],
            ChatMessage.user_id == user["sub"],
        ).order_by(ChatMessage.created_at.asc()))
        msgs = r.scalars().all()
        messages = await _resolve_blocked_call_statuses(db, user["tenant_id"], session_id, msgs)
        task_cards = await _task_card_entries(db, user["tenant_id"], user["sub"], session_id)
        handoffs = await _handoff_entries(db, user["tenant_id"], session_id)
        messages = sorted(messages + task_cards + handoffs, key=lambda m: m["timestamp"])
        return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user=Depends(get_current_user)):
    """Item 4 (2026-08 walkthrough): hard-deletes every ChatMessage row for
    this conversation. Tenant+user scoped, matching list_sessions' own
    scoping (sessions are private per-user, not shared across a tenant).

    There is no ChatSession table -- a "session" is purely the session_id
    grouping key on ChatMessage, so there's nothing to cascade beyond that
    one table. Investigated before building (see findings doc item 4):
    at the time this was written, Task.originating_session_id was never
    actually set by any code path (item 46) -- that gap closed separately
    (TaskCreateModal/create_task both wire it through correctly today,
    Wunomo Projects Phase 4 frontend, slice 11), so deleting a session a
    task once originated from now leaves that task's own back-reference
    pointing at messages that no longer exist. Deliberately not guarded
    here: the task itself (goal, steps, real progress) is untouched and
    fully independent of its originating session -- only the "← Back to
    conversation" link on the task detail page would land on an empty
    thread instead of a live one, a soft UX rough edge, not a data-
    integrity problem, matching every other session_id reference in this
    codebase being FK-less by convention. ApprovalRequest.session_id IS populated for chat-originated
    approvals, but the row is fully self-contained (action_name/action_args/
    reason all live on it) and nothing joins it back to chat_messages at
    read time -- so a *resolved* approval survives its origin conversation
    being deleted with no functional loss. A *pending* one is different:
    it's a live gate a human still needs to act on, and deleting its only
    context out from under it is a bad experience even though nothing
    would technically break -- so that case alone is refused.
    """
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(func.count()).select_from(ApprovalRequest).where(
                ApprovalRequest.tenant_id == user["tenant_id"],
                ApprovalRequest.session_id == session_id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        if r.scalar_one() > 0:
            raise HTTPException(
                status_code=409,
                detail="This conversation has an approval waiting on your decision. Resolve it on the Approvals screen before deleting.",
            )

        result = await db.execute(delete(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.tenant_id == user["tenant_id"],
            ChatMessage.user_id == user["sub"],
        ))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    return {"deleted": True, "session_id": session_id}