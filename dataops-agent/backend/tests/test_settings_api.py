import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User
from sqlalchemy import select
from services.auth_service import issue_token_for_user


async def _register(client, prefix="settingsapi"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Settings API Test", "tenant_name": f"Settings API Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


@pytest.mark.asyncio
async def test_get_settings_returns_real_workspace_name_and_nothing_else_for_a_fresh_tenant(client):
    token, tenant_id, _ = await _register(client)
    r = await client.get("/api/v1/settings/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    settings = r.json()["settings"]
    assert settings["name"].startswith("Settings API Corp")
    assert set(settings.keys()) == {"name"}  # nothing else set yet


@pytest.mark.asyncio
async def test_owner_can_rename_workspace_and_it_persists_to_the_real_tenant_row(client):
    token, tenant_id, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch("/api/v1/settings/", json={"name": "Renamed Workspace"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["settings"]["name"] == "Renamed Workspace"

    async with AsyncSessionLocal() as db:
        from models.all_models import Tenant
        rr = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        assert rr.scalar_one().name == "Renamed Workspace"

    get_r = await client.get("/api/v1/settings/", headers=headers)
    assert get_r.json()["settings"]["name"] == "Renamed Workspace"


@pytest.mark.asyncio
async def test_rename_rejects_empty_name(client):
    token, _, _ = await _register(client)
    r = await client.patch("/api/v1/settings/", json={"name": "   "}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_owner_can_set_timezone_and_description_alongside_name(client):
    token, _, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch(
        "/api/v1/settings/",
        json={"name": "Full Workspace Corp", "timezone": "Europe/London", "description": "A real test workspace"},
        headers=headers,
    )
    settings = r.json()["settings"]
    assert settings["name"] == "Full Workspace Corp"
    assert settings["timezone"] == "Europe/London"
    assert settings["description"] == "A real test workspace"


@pytest.mark.asyncio
async def test_owner_can_patch_ai_model_override(client):
    token, _, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch("/api/v1/settings/", json={"ai_model_override": "openai/gpt-oss-120b"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["settings"]["ai_model_override"] == "openai/gpt-oss-120b"

    get_r = await client.get("/api/v1/settings/", headers=headers)
    assert get_r.json()["settings"]["ai_model_override"] == "openai/gpt-oss-120b"


@pytest.mark.asyncio
async def test_patch_rejects_unsupported_model(client):
    token, _, _ = await _register(client)
    r = await client.patch(
        "/api/v1/settings/", json={"ai_model_override": "gpt-4-bogus"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_with_no_fields_returns_400(client):
    token, _, _ = await _register(client)
    r = await client.patch("/api/v1/settings/", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_viewer_cannot_patch_settings(client):
    _, tenant_id, user_id = await _register(client)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
        await db.refresh(user)
        viewer_token = issue_token_for_user(user, "password")

    r = await client.patch(
        "/api/v1/settings/", json={"timezone": "America/New_York"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_partial_update_preserves_other_fields(client):
    token, _, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.patch("/api/v1/settings/", json={"timezone": "America/New_York"}, headers=headers)
    r = await client.patch("/api/v1/settings/", json={"ai_model_override": "gemini-3.5-flash"}, headers=headers)

    settings = r.json()["settings"]
    assert settings["timezone"] == "America/New_York"
    assert settings["ai_model_override"] == "gemini-3.5-flash"


@pytest.mark.asyncio
async def test_patch_can_clear_ai_model_override_back_to_default(client):
    token, _, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.patch("/api/v1/settings/", json={"ai_model_override": "gemini-3.5-flash"}, headers=headers)
    r = await client.patch("/api/v1/settings/", json={"ai_model_override": None}, headers=headers)
    assert r.json()["settings"]["ai_model_override"] is None
