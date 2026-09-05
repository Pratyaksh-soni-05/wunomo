"""Wunomo Projects Phase 2: channels.

A channel is a real, first-class row (see models/all_models.py's Channel
docstring for why, over extending the bare session_id convention) that
groups human and agent members for a multi-participant conversation.
Creating a channel needs no capability gate beyond authentication -- the
same access starting a chat or a task already has (see api/v1/tasks.py's
own docstring for that precedent); channel membership doesn't expand what
anyone or any agent is allowed to do, it only decides who can address
whom inside a shared conversation. Managing membership (adding/removing a
user or agent) requires the caller to already be a member -- a plain
"you can't manage a room you're not in" rule, not a permission tier.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import AgentInstance, AgentInstanceStatus, Channel, ChannelAgent, ChannelUser, Project, User

router = APIRouter()


async def _require_membership(db, channel_id: str, user_id: str) -> Channel:
    r = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = r.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found.")
    r = await db.execute(select(ChannelUser).where(
        ChannelUser.channel_id == channel_id, ChannelUser.user_id == user_id,
    ))
    if r.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="You are not a member of this channel.")
    return channel


class ChannelCreate(BaseModel):
    name: str
    project_id: Optional[str] = None


@router.post("/")
async def create_channel(body: ChannelCreate, user=Depends(get_current_user)):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty.")
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        if body.project_id is not None:
            r = await db.execute(select(Project).where(Project.id == body.project_id, Project.tenant_id == tenant_id))
            if r.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Project not found.")

        channel = Channel(id=str(uuid.uuid4()), tenant_id=tenant_id, project_id=body.project_id, name=body.name.strip())
        db.add(channel)
        await db.flush()
        db.add(ChannelUser(id=str(uuid.uuid4()), channel_id=channel.id, user_id=user["sub"]))
        await db.commit()
        await db.refresh(channel)

    return {"id": channel.id, "name": channel.name, "project_id": channel.project_id, "created_at": channel.created_at}


@router.get("/")
async def list_channels(user=Depends(get_current_user)):
    """agent_count (Wunomo Projects Phase 2 frontend, slice 6): lets the
    sidebar flag a channel that currently has zero active agent members --
    reachable either by never having added one, or by offboarding a
    channel's only agent (offboard_agent removes its channel_agents rows)
    -- without a human having to open it first and hit a dead message.
    Offboarded agents don't count, matching channel_agent_members'/
    resolve_mentioned_agent's own convention."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(
                Channel,
                func.count(ChannelAgent.id).filter(AgentInstance.status == AgentInstanceStatus.ACTIVE),
            )
            .join(ChannelUser, ChannelUser.channel_id == Channel.id)
            .outerjoin(ChannelAgent, ChannelAgent.channel_id == Channel.id)
            .outerjoin(AgentInstance, AgentInstance.id == ChannelAgent.agent_id)
            .where(Channel.tenant_id == tenant_id, ChannelUser.user_id == user["sub"])
            .group_by(Channel.id)
            .order_by(Channel.created_at.desc())
        )
        rows = r.all()
    return {"channels": [
        {"id": c.id, "name": c.name, "project_id": c.project_id, "created_at": c.created_at, "agent_count": count}
        for c, count in rows
    ]}


@router.get("/{channel_id}")
async def get_channel(channel_id: str, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])
        if channel.tenant_id != user["tenant_id"]:
            raise HTTPException(status_code=404, detail="Channel not found.")

        r = await db.execute(
            select(User.id, User.email).join(ChannelUser, ChannelUser.user_id == User.id)
            .where(ChannelUser.channel_id == channel_id)
        )
        members_users = [{"id": uid, "email": email} for uid, email in r.all()]

        r = await db.execute(
            select(AgentInstance.id, AgentInstance.name).join(ChannelAgent, ChannelAgent.agent_id == AgentInstance.id)
            .where(ChannelAgent.channel_id == channel_id)
        )
        members_agents = [{"id": aid, "name": name} for aid, name in r.all()]

    return {
        "id": channel.id, "name": channel.name, "project_id": channel.project_id,
        "users": members_users, "agents": members_agents,
    }


@router.post("/{channel_id}/members/users/{target_user_id}")
async def add_user_member(channel_id: str, target_user_id: str, user=Depends(get_current_user)):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])
        if channel.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Channel not found.")

        r = await db.execute(select(User).where(User.id == target_user_id, User.tenant_id == tenant_id))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="User not found.")

        r = await db.execute(select(ChannelUser).where(
            ChannelUser.channel_id == channel_id, ChannelUser.user_id == target_user_id,
        ))
        if r.scalar_one_or_none() is None:
            db.add(ChannelUser(id=str(uuid.uuid4()), channel_id=channel_id, user_id=target_user_id))
            await db.commit()

    return {"channel_id": channel_id, "user_id": target_user_id, "added": True}


@router.delete("/{channel_id}/members/users/{target_user_id}")
async def remove_user_member(channel_id: str, target_user_id: str, user=Depends(get_current_user)):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])
        if channel.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Channel not found.")

        from sqlalchemy import delete
        await db.execute(delete(ChannelUser).where(
            ChannelUser.channel_id == channel_id, ChannelUser.user_id == target_user_id,
        ))
        await db.commit()

    return {"channel_id": channel_id, "user_id": target_user_id, "added": False}


@router.post("/{channel_id}/members/agents/{agent_id}")
async def add_agent_member(channel_id: str, agent_id: str, user=Depends(get_current_user)):
    """Membership only -- does not grant the agent anything it isn't
    already permitted (role) or scoped (agent_sources) to touch. It only
    makes the agent addressable in this channel via @mention."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])
        if channel.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Channel not found.")

        r = await db.execute(select(AgentInstance).where(AgentInstance.id == agent_id, AgentInstance.tenant_id == tenant_id))
        agent = r.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found.")

        r = await db.execute(select(ChannelAgent).where(
            ChannelAgent.channel_id == channel_id, ChannelAgent.agent_id == agent_id,
        ))
        if r.scalar_one_or_none() is None:
            db.add(ChannelAgent(id=str(uuid.uuid4()), channel_id=channel_id, agent_id=agent_id))
            await db.commit()

    return {"channel_id": channel_id, "agent_id": agent_id, "agent_name": agent.name, "added": True}


@router.delete("/{channel_id}/members/agents/{agent_id}")
async def remove_agent_member(channel_id: str, agent_id: str, user=Depends(get_current_user)):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])
        if channel.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Channel not found.")

        from sqlalchemy import delete
        await db.execute(delete(ChannelAgent).where(
            ChannelAgent.channel_id == channel_id, ChannelAgent.agent_id == agent_id,
        ))
        await db.commit()

    return {"channel_id": channel_id, "agent_id": agent_id, "added": False}
