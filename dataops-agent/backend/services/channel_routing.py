"""Wunomo Projects Phase 2: @mention routing and per-agent context
filtering.

Resolving a parsed mention (or its absence) against a channel's REAL
membership (channel_agents) -- never a bare string match against an
agent's name alone. An agent removed from a channel cannot be mentioned
into it again just because its name still appears somewhere in scrollback.
"""
from sqlalchemy import func, or_, select

from models.all_models import AgentInstance, ChannelAgent, ChatMessage


async def resolve_mentioned_agent(db, channel_id: str, name: str) -> AgentInstance | None:
    """Case-insensitive match against this channel's real agent members."""
    r = await db.execute(
        select(AgentInstance)
        .join(ChannelAgent, ChannelAgent.agent_id == AgentInstance.id)
        .where(ChannelAgent.channel_id == channel_id, func.lower(AgentInstance.name) == name.lower())
    )
    return r.scalar_one_or_none()


async def channel_agent_members(db, channel_id: str) -> list[AgentInstance]:
    r = await db.execute(
        select(AgentInstance)
        .join(ChannelAgent, ChannelAgent.agent_id == AgentInstance.id)
        .where(ChannelAgent.channel_id == channel_id)
    )
    return list(r.scalars().all())


async def load_agent_channel_context(db, channel_id: str, tenant_id: str, agent_id: str):
    """The real security boundary (Wunomo Projects Phase 2 -- context
    filtering, reading (a)): an agent sees only messages it authored or
    was mentioned in, within this channel -- enforced HERE, by query,
    never by a prompt instruction an LLM could be talked out of.
    Returns (history_msgs, summary_row_or_None), the same shape private
    chat's own history load produces, so chat.py can convert either into
    LangChain messages and window/summarize them identically.

    The rolling summary is scoped per (channel, agent) via
    ChatMessage.agent_id on the summary row itself -- no new column
    needed. Different agents in the same channel see different message
    subsets by this same rule, so a single shared summary would either
    leak one agent's excluded messages into another's compressed view,
    or have to be recomputed from scratch per agent anyway; a real row
    per agent is the simpler, correct answer.

    KNOWN LIMITATION, not implemented here (see GOTCHAS.md): this filters
    WHICH messages an agent sees (reading (a)), never redacts CONTENT
    within a message it's otherwise allowed to see (reading (b)). An
    agent addressed in a thread sees the full text of every message this
    query returns, including tool call arguments that may reference a
    source outside its own agent_sources scope."""
    r = await db.execute(select(ChatMessage).where(
        ChatMessage.session_id == channel_id, ChatMessage.tenant_id == tenant_id,
        ChatMessage.role == "summary", ChatMessage.agent_id == agent_id,
    ).order_by(ChatMessage.created_at.desc()).limit(1))
    summary_row = r.scalar_one_or_none()

    query = select(ChatMessage).where(
        ChatMessage.session_id == channel_id, ChatMessage.tenant_id == tenant_id,
        ChatMessage.role.in_(("user", "assistant")),
        or_(ChatMessage.mentioned_agent_id == agent_id, ChatMessage.agent_id == agent_id),
    )
    if summary_row is not None:
        query = query.where(ChatMessage.created_at > summary_row.created_at)
    r = await db.execute(query.order_by(ChatMessage.created_at.asc()).limit(200))
    return list(r.scalars().all()), summary_row
