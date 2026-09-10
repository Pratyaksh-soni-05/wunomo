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
import os
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from .agents import _grant_source_within_session
from .auth import enforce_quota, get_current_user, require_permission
from .uploads import ALLOWED_EXTS
from database import AsyncSessionLocal
from models.all_models import AgentInstance, AgentInstanceStatus, Channel, ChannelAgent, ChannelUser, Project, User
from modules.ingestion.connector_manager import UPLOAD_DIR, ConnectorManager
from modules.ingestion.schema_profiler import SchemaProfiler
from services.channel_routing import resolve_channel_message_target

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
    """Blocked (409) when this would leave the channel with zero human
    members (Wunomo Projects Phase 2 frontend, slice 7, explicit user
    decision) -- _require_membership gates every management action
    including adding a new member, so a channel with no human members
    left has nobody in the tenant who can ever add themselves back in.
    In practice this can only ever be a self-removal: the caller must
    already be a member to reach this endpoint at all, so if exactly one
    member remains, it can only be the caller. There is no delete-channel
    or dedicated leave endpoint in this codebase today -- the real,
    honest way out named in the refusal is to add a second person first
    (still allowed while you're the sole member) and then remove
    yourself, which succeeds once you're no longer alone."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])
        if channel.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Channel not found.")

        r = await db.execute(select(func.count()).select_from(ChannelUser).where(ChannelUser.channel_id == channel_id))
        member_count = r.scalar_one()
        r = await db.execute(select(ChannelUser).where(
            ChannelUser.channel_id == channel_id, ChannelUser.user_id == target_user_id,
        ))
        if r.scalar_one_or_none() is not None and member_count <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "You're the only person in this channel — add someone else before leaving, "
                    "so it doesn't become unreachable to everyone in your workspace."
                ),
            )

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


@router.post("/{channel_id}/upload")
async def upload_to_channel(
    channel_id: str,
    file: UploadFile = File(...),
    message: str = Form(""),
    _perm=Depends(require_permission("sources.create")),
    user=Depends(enforce_quota("data_sources")),
):
    """Chat-first data upload (Wunomo Projects Phase 4): drop a file into
    a channel, it registers as a real source, profiles itself, and gets
    granted to the one agent the accompanying message resolves to --
    "no manual Add Source flow" for the common case, per explicit
    requirement. Channels only in v1, not private 1:1 chat -- bare AXIOM
    chat currently resolves to "oldest active agent" (finding 80, not yet
    fixed), and this feature needs an unambiguous target to grant to.

    Same sources.create + data_sources-quota gate upload_and_register()
    (api/v1/uploads.py) already requires for the identical underlying
    action (creating a real DataSource) -- a new UI entry point must not
    be an easier path to a privileged action than the one it's shortening.

    Target resolution reuses resolve_channel_message_target() -- the
    exact same @mention/sole-member rule a real text message uses, not a
    second one. A channel with two or more agents and no @mention on the
    accompanying message gets the identical "please @mention who you're
    talking to" refusal a text message would: requiring the mention
    (rather than a new "pick an agent" surface) means there is exactly
    one way to address a specific agent anywhere in this product, not two
    that could drift apart on what counts as ambiguous.

    Deliberately does NOT reverse c9df6d91: source_type and
    connection_config are derived from the real uploaded file's own
    extension inside register_uploaded_file(), the same function the
    existing upload path already uses -- neither the uploading human nor
    the resolved agent ever supplies either value. This endpoint only
    adds two things on top of that existing path: granting the one
    resolved agent (never every channel member), and profiling
    immediately (existing sources still require a separate manual
    Profile click -- see the self-test guide's own §2.3 note on that gap).
    Both happen silently; nothing here ever calls the LLM."""
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        channel = await _require_membership(db, channel_id, user["sub"])

        agent_id, route_error, _ = await resolve_channel_message_target(db, channel.id, tenant_id, message or "")
        if route_error is not None:
            raise HTTPException(status_code=409, detail=route_error)

        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

        dest = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.{ext}")
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        source_result = await ConnectorManager(tenant_id).register_uploaded_file(file.filename, dest)
        if "error" in source_result:
            raise HTTPException(status_code=source_result.get("status_code", 409), detail=source_result["error"])

        source_id = source_result["id"]
        await _grant_source_within_session(db, agent_id, source_id)
        await db.commit()

        agent = await db.get(AgentInstance, agent_id)
        profile_result = await SchemaProfiler(tenant_id, source_id, agent_id).profile()

    return {
        "channel_id": channel_id,
        "agent_id": agent_id,
        "agent_name": agent.name if agent else agent_id,
        "source_id": source_id,
        "source_name": source_result["name"],
        "profiled": "error" not in profile_result,
    }

    return {"channel_id": channel_id, "agent_id": agent_id, "added": False}
