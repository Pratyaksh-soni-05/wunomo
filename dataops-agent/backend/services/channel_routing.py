"""Wunomo Projects Phase 2: @mention routing.

Resolving a parsed mention (or its absence) against a channel's REAL
membership (channel_agents) -- never a bare string match against an
agent's name alone. An agent removed from a channel cannot be mentioned
into it again just because its name still appears somewhere in scrollback.
"""
from sqlalchemy import func, select

from models.all_models import AgentInstance, ChannelAgent


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
