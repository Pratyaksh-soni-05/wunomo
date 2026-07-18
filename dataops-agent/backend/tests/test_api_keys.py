import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User, ApiKey
from sqlalchemy import select
from services.auth_service import issue_token_for_user


async def _register(client, prefix="apikeytest"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Api Key Test", "tenant_name": f"Api Key Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


@pytest.mark.asyncio
async def test_owner_can_create_key_and_raw_key_is_shown_once(client):
    token, tenant_id, user_id = await _register(client)
    r = await client.post("/api/v1/api-keys/", json={"name": "CI pipeline"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "CI pipeline"
    assert body["raw_key"].startswith("axm_live_")
    assert body["key_prefix"] in body["raw_key"]
    assert body["created_by_user_id"] == user_id
    assert body["is_revoked"] is False


@pytest.mark.asyncio
async def test_created_key_is_stored_hashed_not_raw(client):
    token, tenant_id, _ = await _register(client)
    r = await client.post("/api/v1/api-keys/", json={"name": "test key"}, headers={"Authorization": f"Bearer {token}"})
    raw_key = r.json()["raw_key"]

    async with AsyncSessionLocal() as db:
        rr = await db.execute(select(ApiKey).where(ApiKey.tenant_id == tenant_id))
        stored = rr.scalars().first()
        assert stored.key_hash != raw_key
        assert len(stored.key_hash) == 64  # sha256 hex digest


@pytest.mark.asyncio
async def test_list_never_exposes_raw_key_or_hash(client):
    token, tenant_id, _ = await _register(client)
    await client.post("/api/v1/api-keys/", json={"name": "key one"}, headers={"Authorization": f"Bearer {token}"})

    r = await client.get("/api/v1/api-keys/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    keys = r.json()["api_keys"]
    assert len(keys) == 1
    assert "raw_key" not in keys[0]
    assert "key_hash" not in keys[0]
    assert keys[0]["key_prefix"].startswith("axm_live_")


@pytest.mark.asyncio
async def test_owner_can_revoke_a_key(client):
    token, tenant_id, _ = await _register(client)
    create_r = await client.post("/api/v1/api-keys/", json={"name": "to revoke"}, headers={"Authorization": f"Bearer {token}"})
    key_id = create_r.json()["id"]

    r = await client.delete(f"/api/v1/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["is_revoked"] is True

    list_r = await client.get("/api/v1/api-keys/", headers={"Authorization": f"Bearer {token}"})
    assert list_r.json()["api_keys"][0]["revoked_at"] is not None


@pytest.mark.asyncio
async def test_revoke_is_idempotent(client):
    token, tenant_id, _ = await _register(client)
    create_r = await client.post("/api/v1/api-keys/", json={"name": "double revoke"}, headers={"Authorization": f"Bearer {token}"})
    key_id = create_r.json()["id"]

    r1 = await client.delete(f"/api/v1/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    r2 = await client.delete(f"/api/v1/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_revoke_unknown_key_returns_404(client):
    token, _, _ = await _register(client)
    r = await client.delete("/api/v1/api-keys/nonexistent-id", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_rejects_empty_name(client):
    token, _, _ = await _register(client)
    r = await client.post("/api/v1/api-keys/", json={"name": "   "}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_viewer_cannot_create_list_or_revoke_keys(client):
    _, tenant_id, user_id = await _register(client)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
        await db.refresh(user)
        viewer_token = issue_token_for_user(user, "password")

    headers = {"Authorization": f"Bearer {viewer_token}"}
    assert (await client.post("/api/v1/api-keys/", json={"name": "x"}, headers=headers)).status_code == 403
    assert (await client.get("/api/v1/api-keys/", headers=headers)).status_code == 403
    assert (await client.delete("/api/v1/api-keys/some-id", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_api_keys_are_tenant_scoped(client):
    token_a, tenant_a, _ = await _register(client, "keyisoa")
    token_b, tenant_b, _ = await _register(client, "keyisob")

    await client.post("/api/v1/api-keys/", json={"name": "tenant a's key"}, headers={"Authorization": f"Bearer {token_a}"})

    b_list = await client.get("/api/v1/api-keys/", headers={"Authorization": f"Bearer {token_b}"})
    assert b_list.json()["api_keys"] == []
