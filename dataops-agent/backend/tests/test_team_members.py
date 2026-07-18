import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User
from sqlalchemy import select
from services.auth_service import issue_token_for_user


async def _register(client, prefix="teammember"):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Team Member Test", "tenant_name": f"Team Member Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"], email


async def _add_member(tenant_id: str, role: str) -> tuple[str, str, str]:
    """Directly inserts a second real member into the tenant (no invite
    flow exercised here - that's covered in test_team_invites.py) and
    returns (user_id, email, token)."""
    email = f"member-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSessionLocal() as db:
        from services.auth_service import hash_password
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=email,
            hashed_password=hash_password("memberpass123"),
            full_name="Second Member", role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = issue_token_for_user(user, "password")
        return user.id, email, token


@pytest.mark.asyncio
async def test_any_member_can_list_team(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    r = await client.get("/api/v1/team/members", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200
    emails = [m["email"] for m in r.json()["members"]]
    assert owner_email in emails


@pytest.mark.asyncio
async def test_admin_can_change_a_data_analysts_role(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    admin_id, admin_email, admin_token = await _add_member(tenant_id, "admin")
    analyst_id, analyst_email, _ = await _add_member(tenant_id, "data_analyst")

    r = await client.patch(
        f"/api/v1/team/members/{analyst_id}/role", json={"role": "data_engineer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        rr = await db.execute(select(User).where(User.id == analyst_id))
        assert rr.scalar_one().role == "data_engineer"


@pytest.mark.asyncio
async def test_admin_cannot_change_an_owners_role(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    admin_id, admin_email, admin_token = await _add_member(tenant_id, "admin")

    r = await client.patch(
        f"/api/v1/team/members/{owner_id}/role", json={"role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_promote_someone_to_owner(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    admin_id, admin_email, admin_token = await _add_member(tenant_id, "admin")
    analyst_id, analyst_email, _ = await _add_member(tenant_id, "data_analyst")

    r = await client.patch(
        f"/api/v1/team/members/{analyst_id}/role", json={"role": "owner"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_demote_the_last_owner(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)

    r = await client.patch(
        f"/api/v1/team/members/{owner_id}/role", json={"role": "admin"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 400
    assert "last owner" in r.json()["detail"]


@pytest.mark.asyncio
async def test_owner_can_demote_a_second_owner(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    second_owner_id, second_owner_email, _ = await _add_member(tenant_id, "owner")

    r = await client.patch(
        f"/api/v1/team/members/{second_owner_id}/role", json={"role": "admin"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_owner_can_remove_a_member_and_they_can_no_longer_log_in(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    member_id, member_email, _ = await _add_member(tenant_id, "data_engineer")

    login_before = await client.post("/api/v1/auth/login", data={"username": member_email, "password": "memberpass123"})
    assert login_before.status_code == 200

    r = await client.delete(f"/api/v1/team/members/{member_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200

    login_after = await client.post("/api/v1/auth/login", data={"username": member_email, "password": "memberpass123"})
    assert login_after.status_code == 400  # matches this codebase's "Invalid credentials" convention

    listing = await client.get("/api/v1/team/members", headers={"Authorization": f"Bearer {owner_token}"})
    member = next(m for m in listing.json()["members"] if m["id"] == member_id)
    assert member["is_active"] is False


@pytest.mark.asyncio
async def test_cannot_remove_yourself(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)

    r = await client.delete(f"/api/v1/team/members/{owner_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_cannot_remove_an_owner(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    admin_id, admin_email, admin_token = await _add_member(tenant_id, "admin")

    r = await client.delete(f"/api/v1/team/members/{owner_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_remove_a_second_owner_when_not_the_last_one(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    second_owner_id, second_owner_email, _ = await _add_member(tenant_id, "owner")

    r = await client.delete(f"/api/v1/team/members/{second_owner_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200  # fine, 2 owners existed at the time of removal


@pytest.mark.asyncio
async def test_viewer_cannot_change_roles_or_remove_members(client):
    owner_token, tenant_id, owner_id, owner_email = await _register(client)
    viewer_id, viewer_email, viewer_token = await _add_member(tenant_id, "viewer")

    r = await client.patch(
        f"/api/v1/team/members/{owner_id}/role", json={"role": "viewer"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403

    r2 = await client.delete(f"/api/v1/team/members/{owner_id}", headers={"Authorization": f"Bearer {viewer_token}"})
    assert r2.status_code == 403
