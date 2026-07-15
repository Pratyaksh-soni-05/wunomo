import uuid
import pytest

import api.v1.auth as auth_router
from services.auth_service import create_new_tenant_and_user, hash_password, get_google_authorize_url


def unique_email():
    return f"googleauth-{uuid.uuid4().hex[:10]}@example.com"


def _mock_google(monkeypatch, email: str, google_sub: str, email_verified: bool = True, name: str = "Google User"):
    async def fake_exchange(code):
        return {"id_token": "fake-id-token", "access_token": "fake-access-token"}

    async def fake_verify(id_token_str):
        return {"sub": google_sub, "email": email, "email_verified": email_verified, "name": name}

    monkeypatch.setattr(auth_router, "exchange_google_code", fake_exchange)
    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)


@pytest.mark.asyncio
async def test_login_url_returns_well_formed_url_and_state(client):
    r = await client.get("/api/v1/auth/google/login-url")
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in body["url"]
    assert body["state"]


@pytest.mark.asyncio
async def test_callback_rejects_invalid_state(client):
    r = await client.post("/api/v1/auth/google/callback", json={"code": "x", "state": "not-a-real-state"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_rejects_reused_state(client):
    url_resp = await client.get("/api/v1/auth/google/login-url")
    state = url_resp.json()["state"]
    # First use fails at Google's token exchange (real call, fake code) but
    # still consumes the state — real behavior, not mocked, matches the live
    # test already done manually against the real Google endpoint.
    await client.post("/api/v1/auth/google/callback", json={"code": "definitely-fake", "state": state})
    replay = await client.post("/api/v1/auth/google/callback", json={"code": "definitely-fake", "state": state})
    assert replay.status_code == 400
    assert replay.json()["detail"] == "Invalid or expired state"


@pytest.mark.asyncio
async def test_new_workspace_signup_via_google(client, monkeypatch):
    email = unique_email()
    _mock_google(monkeypatch, email, google_sub="google-sub-1")

    url_resp = await client.get("/api/v1/auth/google/login-url")
    state = url_resp.json()["state"]
    r = await client.post("/api/v1/auth/google/callback", json={
        "code": "fake", "state": state, "new_tenant_name": "Google Signup Corp",
    })
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["tenant_id"]


@pytest.mark.asyncio
async def test_auto_links_to_existing_password_account_when_google_verified(client, monkeypatch):
    email = unique_email()
    tenant, user = await create_new_tenant_and_user(
        tenant_name="Link Corp", email=email, auth_method="password",
        hashed_password=hash_password("somepass"),
    )
    assert user.google_id is None

    _mock_google(monkeypatch, email, google_sub="google-sub-2", email_verified=True)
    url_resp = await client.get("/api/v1/auth/google/login-url")
    state = url_resp.json()["state"]
    r = await client.post("/api/v1/auth/google/callback", json={
        "code": "fake", "state": state, "intended_tenant_id": tenant.id,
    })
    assert r.status_code == 200
    assert r.json()["tenant_id"] == tenant.id

    from database import AsyncSessionLocal
    from models.all_models import User
    async with AsyncSessionLocal() as db:
        refreshed = await db.get(User, user.id)
    assert refreshed.google_id == "google-sub-2"
    assert refreshed.email_verified is True


@pytest.mark.asyncio
async def test_blocks_auto_link_when_google_email_not_verified(client, monkeypatch):
    """The locked Phase 3 rule: without Google's own email_verified: true,
    auto-linking to an existing password account must be blocked, not
    silently linked and not silently ignored."""
    email = unique_email()
    tenant, user = await create_new_tenant_and_user(
        tenant_name="Unverified Link Corp", email=email, auth_method="password",
        hashed_password=hash_password("somepass"),
    )

    _mock_google(monkeypatch, email, google_sub="google-sub-3", email_verified=False)
    url_resp = await client.get("/api/v1/auth/google/login-url")
    state = url_resp.json()["state"]
    r = await client.post("/api/v1/auth/google/callback", json={
        "code": "fake", "state": state, "intended_tenant_id": tenant.id,
    })
    assert r.status_code == 403

    from database import AsyncSessionLocal
    from models.all_models import User
    async with AsyncSessionLocal() as db:
        refreshed = await db.get(User, user.id)
    assert refreshed.google_id is None
    assert refreshed.email_verified is False


@pytest.mark.asyncio
async def test_returning_google_user_logs_in_without_reverifying(client, monkeypatch):
    email = unique_email()
    _mock_google(monkeypatch, email, google_sub="google-sub-4", email_verified=True)

    url1 = await client.get("/api/v1/auth/google/login-url")
    first = await client.post("/api/v1/auth/google/callback", json={
        "code": "fake", "state": url1.json()["state"], "new_tenant_name": "Returning Google Corp",
    })
    assert first.status_code == 200
    tenant_id = first.json()["tenant_id"]

    # Second login, this time Google claims email_verified=False — must not
    # matter, since this account is already linked (google_id set).
    _mock_google(monkeypatch, email, google_sub="google-sub-4", email_verified=False)
    url2 = await client.get("/api/v1/auth/google/login-url")
    second = await client.post("/api/v1/auth/google/callback", json={
        "code": "fake", "state": url2.json()["state"],
    })
    assert second.status_code == 200
    assert second.json()["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_multiple_tenant_matches_returns_choose_workspace(client, monkeypatch):
    email = unique_email()
    tenant_a, _ = await create_new_tenant_and_user(
        tenant_name="Google Multi A", email=email, auth_method="password",
        hashed_password=hash_password("x"),
    )
    tenant_b, _ = await create_new_tenant_and_user(
        tenant_name="Google Multi B", email=email, auth_method="password",
        hashed_password=hash_password("x"),
    )

    _mock_google(monkeypatch, email, google_sub="google-sub-5", email_verified=True)
    url_resp = await client.get("/api/v1/auth/google/login-url")
    r = await client.post("/api/v1/auth/google/callback", json={"code": "fake", "state": url_resp.json()["state"]})
    assert r.status_code == 200
    assert r.json()["status"] == "choose_workspace"
    tenant_ids = {opt["tenant_id"] for opt in r.json()["options"]}
    assert tenant_ids == {tenant_a.id, tenant_b.id}

    # Google's code+state are single-use and already consumed — a second
    # /google/callback with the same values must fail, proving finalization
    # has to go through the resolution token instead.
    replay = await client.post("/api/v1/auth/google/callback", json={"code": "fake", "state": url_resp.json()["state"]})
    assert replay.status_code == 400

    resolution_token = r.json()["resolution_token"]
    resolved = await client.post("/api/v1/auth/resolve-workspace", json={
        "resolution_token": resolution_token, "tenant_id": tenant_a.id,
    })
    assert resolved.status_code == 200
    assert resolved.json()["tenant_id"] == tenant_a.id

    replay_resolution = await client.post("/api/v1/auth/resolve-workspace", json={
        "resolution_token": resolution_token, "tenant_id": tenant_b.id,
    })
    assert replay_resolution.status_code == 400
