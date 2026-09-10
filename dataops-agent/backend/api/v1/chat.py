import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from .auth import get_current_user, enforce_quota, enforce_agent_budget
from agent.dataops_agent import run_agent, window_and_summarize
from database import AsyncSessionLocal
from models.all_models import AgentInstance, AgentInstanceStatus, Channel, ChannelUser, ChatMessage, Task
from sqlalchemy import select, func, delete
from datetime import datetime, timezone
import uuid
from models.approval_model import ApprovalRequest, ApprovalStatus
from schemas.chat_schema import ChatRequest
from services.channel_routing import load_agent_channel_context, resolve_channel_message_target
from langchain_core.messages import AIMessage as LCAIMessage, ToolMessage as LCToolMessage, SystemMessage as LCSystemMessage

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
    appeared the first time (right after the message that triggered it)."""
    r = await db.execute(select(Task).where(
        Task.tenant_id == tenant_id, Task.user_id == user_id, Task.originating_session_id == session_id,
    ).order_by(Task.created_at.asc()))
    return [
        {
            "role": "assistant", "content": "", "tool_calls": [], "timestamp": str(t.created_at),
            "taskCard": {"id": t.id, "goal": t.goal},
        }
        for t in r.scalars().all()
    ]


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
        messages = sorted(messages + task_cards, key=lambda m: m["timestamp"])
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