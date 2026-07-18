import uuid
import pytest

import api.v1.team as team_api


@pytest.fixture
def captured_invite(monkeypatch):
    """Mocks Resend delivery (real end-to-end delivery is separately
    live-verified against the account owner's own inbox, per CLAUDE.md's
    Resend sandbox gotcha) while still exercising the real
    generate/hash/store path and capturing the real token. Patched on
    api.v1.team (not services.team_service) since that's where the name is
    actually resolved at call time - team.py imports the function directly
    rather than the module."""
    captured = {}

    async def fake_send(*, email, token, tenant_name, inviter_email, role):
        captured["email"] = email
        captured["token"] = token
        captured["tenant_name"] = tenant_name
        captured["role"] = role
        return "fake-message-id"

    monkeypatch.setattr(team_api, "send_invite_email", fake_send)
    return captured


async def _register(client, prefix="teaminvite"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Team Invite Test",
        "tenant_name": f"Team Invite Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


def unique_email():
    return f"invitee-{uuid.uuid4().hex[:10]}@example.com"


@pytest.mark.asyncio
async def test_owner_can_invite_and_invitee_accepts_into_existing_tenant(client, captured_invite):
    owner_token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {owner_token}"}
    email = unique_email()

    r = await client.post("/api/v1/team/invites", json={"email": email, "role": "data_analyst"}, headers=headers)
    assert r.status_code == 200
    assert captured_invite["email"] == email
    assert captured_invite["role"] == "data_analyst"
    token = captured_invite["token"]

    verify = await client.get(f"/api/v1/team/invites/verify?token={token}")
    assert verify.status_code == 200
    assert verify.json()["role"] == "data_analyst"
    assert verify.json()["email"] == email

    accept = await client.post("/api/v1/team/invites/accept", json={
        "token": token, "password": "newpass123", "full_name": "New Analyst",
    })
    assert accept.status_code == 200
    body = accept.json()
    assert body["tenant_id"] == tenant_id
    assert body["role"] == "data_analyst"

    login = await client.post("/api/v1/auth/login", data={"username": email, "password": "newpass123"})
    assert login.status_code == 200
    assert login.json()["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_viewer_cannot_create_invite(client, captured_invite):
    owner_token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {owner_token}"}

    from database import AsyncSessionLocal
    from models.all_models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.tenant_id == tenant_id))
        user = r.scalars().first()
        user.role = "viewer"
        await db.commit()
        await db.refresh(user)
        from services.auth_service import issue_token_for_user
        viewer_token = issue_token_for_user(user, "password")

    r = await client.post(
        "/api/v1/team/invites", json={"email": unique_email(), "role": "viewer"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invite_rejects_email_already_a_member_of_the_tenant(client, captured_invite):
    email = f"selfmember-{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Owner", "tenant_name": f"Self Member Corp {uuid.uuid4().hex[:6]}",
    })
    owner_token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {owner_token}"}

    # inviting the tenant's own owner-account email into the same tenant
    r = await client.post("/api/v1/team/invites", json={"email": email, "role": "viewer"}, headers=headers)
    assert r.status_code == 400
    assert "already a member" in r.json()["detail"]


@pytest.mark.asyncio
async def test_expired_or_bogus_token_rejected(client):
    r = await client.get("/api/v1/team/invites/verify?token=not-a-real-token")
    assert r.status_code == 404

    r = await client.post("/api/v1/team/invites/accept", json={
        "token": "not-a-real-token", "password": "whatever123",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_revoked_invite_cannot_be_accepted(client, captured_invite):
    owner_token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {owner_token}"}
    email = unique_email()

    r = await client.post("/api/v1/team/invites", json={"email": email, "role": "viewer"}, headers=headers)
    invite_id = r.json()["id"]
    token = captured_invite["token"]

    revoke = await client.delete(f"/api/v1/team/invites/{invite_id}", headers=headers)
    assert revoke.status_code == 200

    accept = await client.post("/api/v1/team/invites/accept", json={"token": token, "password": "x1234567"})
    assert accept.status_code == 400


@pytest.mark.asyncio
async def test_second_invite_to_same_email_supersedes_the_first(client, captured_invite):
    owner_token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {owner_token}"}
    email = unique_email()

    r1 = await client.post("/api/v1/team/invites", json={"email": email, "role": "viewer"}, headers=headers)
    token1 = captured_invite["token"]

    r2 = await client.post("/api/v1/team/invites", json={"email": email, "role": "data_engineer"}, headers=headers)
    token2 = captured_invite["token"]
    assert token1 != token2

    stale_accept = await client.post("/api/v1/team/invites/accept", json={"token": token1, "password": "x1234567"})
    assert stale_accept.status_code == 400

    fresh_accept = await client.post("/api/v1/team/invites/accept", json={"token": token2, "password": "x1234567"})
    assert fresh_accept.status_code == 200
    assert fresh_accept.json()["role"] == "data_engineer"
