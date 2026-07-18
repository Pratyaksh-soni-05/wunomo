import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User
from sqlalchemy import select
from services.auth_service import hash_password, issue_token_for_user


async def _register(client, prefix="themetest"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Theme Test", "tenant_name": f"Theme Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


@pytest.mark.asyncio
async def test_get_me_includes_theme_null_by_default(client):
    token, _, _ = await _register(client)
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["theme"] is None


@pytest.mark.asyncio
async def test_patch_me_sets_theme_and_persists(client):
    token, _, user_id = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch("/api/v1/auth/me", json={"theme": "dark"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["theme"] == "dark"

    async with AsyncSessionLocal() as db:
        rr = await db.execute(select(User.theme).where(User.id == user_id))
        assert rr.scalar() == "dark"

    get_r = await client.get("/api/v1/auth/me", headers=headers)
    assert get_r.json()["theme"] == "dark"


@pytest.mark.asyncio
async def test_patch_me_rejects_invalid_theme(client):
    token, _, _ = await _register(client)
    r = await client.patch(
        "/api/v1/auth/me", json={"theme": "rainbow"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_me_with_no_fields_returns_400(client):
    token, _, _ = await _register(client)
    r = await client.patch("/api/v1/auth/me", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_me_can_clear_theme_back_to_null(client):
    token, _, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.patch("/api/v1/auth/me", json={"theme": "light"}, headers=headers)
    r = await client.patch("/api/v1/auth/me", json={"theme": None}, headers=headers)
    assert r.json()["theme"] is None


@pytest.mark.asyncio
async def test_theme_is_per_user_not_per_tenant(client):
    """Two members of the SAME tenant must be able to set different
    themes independently - it's a personal preference, not workspace-wide."""
    owner_token, tenant_id, owner_id = await _register(client)

    async with AsyncSessionLocal() as db:
        member = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=f"member-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("x"), role="viewer",
        )
        db.add(member)
        await db.commit()
        await db.refresh(member)
        member_token = issue_token_for_user(member, "password")

    await client.patch("/api/v1/auth/me", json={"theme": "dark"}, headers={"Authorization": f"Bearer {owner_token}"})
    await client.patch("/api/v1/auth/me", json={"theme": "light"}, headers={"Authorization": f"Bearer {member_token}"})

    owner_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
    member_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {member_token}"})
    assert owner_me.json()["theme"] == "dark"
    assert member_me.json()["theme"] == "light"
