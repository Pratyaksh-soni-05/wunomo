"""Wunomo Projects Phase 2: @mention routing and per-agent context
filtering.

Resolving a parsed mention (or its absence) against a channel's REAL
membership (channel_agents) -- never a bare string match against an
agent's name alone. An agent removed from a channel cannot be mentioned
into it again just because its name still appears somewhere in scrollback.
"""
from sqlalchemy import func, or_, select

from models.all_models import AgentInstance, AgentInstanceStatus, ChannelAgent, ChatMessage
from services.mentions import parse_mention


async def resolve_mentioned_agent(db, channel_id: str, name: str) -> AgentInstance | None:
    """Case-insensitive match against this channel's real agent members.
    Excludes OFFBOARDED agents (Wunomo Projects Phase 2 frontend, slice 4)
    -- offboarding must actually remove reachability, not just relabel a
    status column; an offboarded agent left resolvable here would still
    answer to @mention despite the UI claiming it's gone."""
    r = await db.execute(
        select(AgentInstance)
        .join(ChannelAgent, ChannelAgent.agent_id == AgentInstance.id)
        .where(
            ChannelAgent.channel_id == channel_id, func.lower(AgentInstance.name) == name.lower(),
            AgentInstance.status == AgentInstanceStatus.ACTIVE,
        )
    )
    return r.scalar_one_or_none()


async def find_active_agent_in_tenant(db, tenant_id: str, name: str) -> AgentInstance | None:
    """Tenant-wide (not channel-scoped) case-insensitive name match, ACTIVE
    only. Exists to let chat.py tell apart two different unmentionable-
    agent failures that resolve_mentioned_agent's own None can't
    distinguish by itself: a genuine typo (no such agent anywhere in this
    tenant) versus a real, active agent that simply hasn't been added to
    THIS channel yet -- the first needs a spelling fix, the second needs
    an actual add-member action, and conflating them into one generic
    message makes a typo indistinguishable from a fixable membership gap
    (Wunomo Projects Phase 2 frontend, slice 6, explicit user requirement)."""
    r = await db.execute(
        select(AgentInstance).where(
            AgentInstance.tenant_id == tenant_id, func.lower(AgentInstance.name) == name.lower(),
            AgentInstance.status == AgentInstanceStatus.ACTIVE,
        )
    )
    return r.scalar_one_or_none()


async def channel_agent_members(db, channel_id: str) -> list[AgentInstance]:
    """Excludes OFFBOARDED agents -- same reasoning as resolve_mentioned_agent
    above. This also feeds the "exactly one agent in the channel" single-
    member auto-routing check in chat.py, so an offboarded agent must not
    count toward that total either."""
    r = await db.execute(
        select(AgentInstance)
        .join(ChannelAgent, ChannelAgent.agent_id == AgentInstance.id)
        .where(ChannelAgent.channel_id == channel_id, AgentInstance.status == AgentInstanceStatus.ACTIVE)
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


async def resolve_channel_message_target(
    db, channel_id: str, tenant_id: str, message: str,
) -> tuple[str | None, str | None, str]:
    """Which agent a channel message (or, as of Wunomo Projects Phase 4,
    a channel file upload) addresses. Returns (agent_id, error_message,
    remaining_text) -- exactly one of agent_id/error_message is set.
    Extracted from api/v1/chat.py's own inline routing block (word-for-
    word identical messages, not a rewrite) so a second caller (the
    channel-upload endpoint) doesn't get a second, divergently-worded
    notion of "which agent does this address" -- @mention, or the
    channel's sole member, is the one real answer everywhere in this
    product, never a picker or a guess.

    error_message is one of four real cases, same as chat.py always
    produced: an unresolvable @mention (typo -- no such agent anywhere in
    the tenant); a real, active agent that exists but isn't a member of
    THIS channel yet; zero agents in the channel; or more than one agent
    with no @mention to disambiguate. remaining_text is the message with
    a leading mention stripped (chat.py's own message_text), or the
    original message unchanged when there was nothing to strip."""
    mentioned_name, remaining_text = parse_mention(message)
    if mentioned_name is not None:
        target_agent = await resolve_mentioned_agent(db, channel_id, mentioned_name)
        if target_agent is None:
            tenant_agent = await find_active_agent_in_tenant(db, tenant_id, mentioned_name)
            if tenant_agent is None:
                return None, f"'{mentioned_name}' doesn't match any agent in your workspace.", remaining_text
            return None, (
                f"{tenant_agent.name} exists but isn't a member of this channel yet. "
                f"Add them from this channel's members, then @mention them again."
            ), remaining_text
        return target_agent.id, None, remaining_text

    members = await channel_agent_members(db, channel_id)
    if len(members) == 1:
        return members[0].id, None, message
    if not members:
        return None, "No agents are in this channel — add one from this channel's members to start talking here.", message
    return None, "More than one agent is in this channel — please @mention who you're talking to.", message
