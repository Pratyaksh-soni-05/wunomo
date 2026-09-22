"""Wunomo Projects Phase 4: chat-first data upload. Drop a file into a
channel, it registers as a real source, profiles itself, and gets
granted to the one agent the accompanying message resolves to -- no
manual Add Source flow for the common case.

Channels only in v1 (bare 1:1 chat isn't covered -- finding 80). Target
resolution reuses resolve_channel_message_target(), the exact same
@mention/sole-member rule a real text message uses (see test_channels.py
for that rule's own coverage) -- this file focuses on what's new: the
upload's own gates, the register+grant+profile sequence, and that it
never reverses c9df6d91 (the resolved agent never supplies source_type
or connection_config -- both come from the real file's own extension).
"""
import io
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import AgentSource, DataSource, User
from services.auth_service import hash_password, issue_token_for_user


def _csv_bytes():
    return b"a,b\n1,2\n"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _register(client, prefix="chanupload"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Channel Upload Test",
        "tenant_name": f"Channel Upload Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _member(tenant_id, role, prefix="member"):
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name=prefix, role=role,
            is_active=True, email_verified=True,
        )
        db.add(user)
        await db.commit()
        return issue_token_for_user(user, "password"), user.id


async def _hire_agent(client, token, name):
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _create_channel(client, token, name="uploads-test"):
    r = await client.post("/api/v1/channels/", headers=_auth(token), json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _add_agent_to_channel(client, token, channel_id, agent_id):
    r = await client.post(f"/api/v1/channels/{channel_id}/members/agents/{agent_id}", headers=_auth(token))
    assert r.status_code == 200, r.text


async def _is_granted(agent_id: str, source_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentSource).where(
            AgentSource.agent_id == agent_id, AgentSource.source_id == source_id,
        ))
        return r.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_with_sole_agent_member_registers_grants_and_profiles(client):
    token, tenant_id, _ = await _register(client, "solo")
    channel_id = await _create_channel(client, token)
    nova_id = await _hire_agent(client, token, "Nova")
    await _add_agent_to_channel(client, token, channel_id, nova_id)

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(token),
        files={"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"message": ""},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == nova_id
    assert body["agent_name"] == "Nova"
    assert body["source_name"] == "sales.csv"
    assert body["profiled"] is True

    assert await _is_granted(nova_id, body["source_id"])

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(DataSource.id == body["source_id"]))
        source = r.scalar_one()
        assert source.tenant_id == tenant_id
        assert source.last_profiled_at is not None  # profiling actually ran, not just registration


@pytest.mark.asyncio
async def test_upload_with_mention_resolves_the_mentioned_agent_and_grants_only_that_one(client):
    token, tenant_id, _ = await _register(client, "mention")
    channel_id = await _create_channel(client, token)
    nova_id = await _hire_agent(client, token, "Nova")
    atlas_id = await _hire_agent(client, token, "Atlas")
    await _add_agent_to_channel(client, token, channel_id, nova_id)
    await _add_agent_to_channel(client, token, channel_id, atlas_id)

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(token),
        files={"file": ("marketing.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"message": "@Nova here's the file"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == nova_id

    assert await _is_granted(nova_id, body["source_id"])
    assert not await _is_granted(atlas_id, body["source_id"])  # never every member, only the resolved one


# ---------------------------------------------------------------------------
# Ambiguous target -- must require the mention, never guess, never a picker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_with_no_mention_and_multiple_agents_is_refused_not_guessed(client):
    token, tenant_id, _ = await _register(client, "ambiguous")
    channel_id = await _create_channel(client, token)
    nova_id = await _hire_agent(client, token, "Nova")
    atlas_id = await _hire_agent(client, token, "Atlas")
    await _add_agent_to_channel(client, token, channel_id, nova_id)
    await _add_agent_to_channel(client, token, channel_id, atlas_id)

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(token),
        files={"file": ("ambiguous.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"message": ""},
    )
    assert r.status_code == 409, r.text
    assert "please @mention who you're talking to" in r.json()["detail"].lower()

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(DataSource.tenant_id == tenant_id))
        assert r.scalars().all() == [], "an ambiguous target must not create a source at all"


@pytest.mark.asyncio
async def test_upload_with_zero_agents_in_channel_refuses(client):
    token, tenant_id, _ = await _register(client, "noagents")
    channel_id = await _create_channel(client, token)

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(token),
        files={"file": ("orphan.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"message": ""},
    )
    assert r.status_code == 409, r.text
    assert "no agents are in this channel" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# File-type rejection -- same chokepoint as the existing upload path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_rejects_pdf_with_422_same_as_the_existing_upload_path(client):
    token, tenant_id, _ = await _register(client, "pdfreject")
    channel_id = await _create_channel(client, token)
    nova_id = await _hire_agent(client, token, "Nova")
    await _add_agent_to_channel(client, token, channel_id, nova_id)

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(token),
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={"message": ""},
    )
    assert r.status_code == 422, r.text
    assert "no working connector" in r.json()["detail"].lower()

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(DataSource).where(DataSource.tenant_id == tenant_id))
        assert r.scalars().all() == [], "the rejected PDF must not have been persisted as a source"


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension_with_400(client):
    token, tenant_id, _ = await _register(client, "badext")
    channel_id = await _create_channel(client, token)
    nova_id = await _hire_agent(client, token, "Nova")
    await _add_agent_to_channel(client, token, channel_id, nova_id)

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(token),
        files={"file": ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        data={"message": ""},
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Access control -- same bar as the existing upload path, just reached from
# inside a channel a human has to already be a member of
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_requires_channel_membership(client):
    token, tenant_id, _ = await _register(client, "notmember")
    channel_id = await _create_channel(client, token)
    other_token, _, _ = await _register(client, "outsider")

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(other_token),
        files={"file": ("blocked.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"message": ""},
    )
    assert r.status_code in (403, 404), r.text


@pytest.mark.asyncio
async def test_upload_requires_sources_create_permission(client):
    """Same gate as POST /api/v1/uploads/register -- a new UI entry point
    for creating a real DataSource must not be an easier path to that
    privileged action than the existing one, just because the caller
    happens to already be a channel member."""
    token, tenant_id, _ = await _register(client, "viewerupload")
    channel_id = await _create_channel(client, token)
    viewer_token, viewer_id = await _member(tenant_id, "viewer", "viewerinchannel")

    r = await client.post(f"/api/v1/channels/{channel_id}/members/users/{viewer_id}", headers=_auth(token))
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/channels/{channel_id}/upload", headers=_auth(viewer_token),
        files={"file": ("blocked.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"message": ""},
    )
    assert r.status_code == 403, r.text
