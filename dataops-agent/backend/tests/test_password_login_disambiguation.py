import uuid
import pytest

from services.auth_service import create_new_tenant_and_user, hash_password


@pytest.mark.asyncio
async def test_login_single_tenant_match_unchanged_behavior(client):
    """No-regression check: the common case (email exists in exactly one
    tenant) must behave identically to before the fix."""
    email = f"logintest-{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Login Test", "tenant_name": "Login Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]

    login = await client.post("/api/v1/auth/login", data={"username": email, "password": "test1234"})
    assert login.status_code == 200
    body = login.json()
    assert body["tenant_id"] == tenant_id
    assert "access_token" in body


@pytest.mark.asyncio
async def test_login_wrong_password_generic_error(client):
    email = f"logintest-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Login Test", "tenant_name": "Login Test Corp 2",
    })
    login = await client.post("/api/v1/auth/login", data={"username": email, "password": "wrongpass"})
    assert login.status_code == 400


@pytest.mark.asyncio
async def test_login_disambiguates_when_same_email_multiple_tenants(client):
    """Regression test for the pre-existing bug: login() used to run
    select(User).where(User.email == ...).scalars().first() with no tenant
    scoping, silently authenticating into an arbitrary tenant if the same
    email+password existed in more than one. Must now return a
    choose_workspace response instead of picking one."""
    email = f"logintest-{uuid.uuid4().hex[:8]}@example.com"
    tenant_a, user_a = await create_new_tenant_and_user(
        tenant_name="Disambig Corp A", email=email, auth_method="password",
        hashed_password=hash_password("samepass123"),
    )
    tenant_b, user_b = await create_new_tenant_and_user(
        tenant_name="Disambig Corp B", email=email, auth_method="password",
        hashed_password=hash_password("samepass123"),
    )

    login = await client.post("/api/v1/auth/login", data={"username": email, "password": "samepass123"})
    assert login.status_code == 200
    body = login.json()
    assert body["status"] == "choose_workspace"
    returned_tenant_ids = {opt["tenant_id"] for opt in body["options"]}
    assert returned_tenant_ids == {tenant_a.id, tenant_b.id}
    assert "access_token" not in body

    # Resubmitting with a chosen tenant_id must resolve to that one specifically.
    resolved = await client.post("/api/v1/auth/login", data={
        "username": email, "password": "samepass123", "tenant_id": tenant_a.id,
    })
    assert resolved.status_code == 200
    assert resolved.json()["tenant_id"] == tenant_a.id
    assert "access_token" in resolved.json()


@pytest.mark.asyncio
async def test_login_disambiguation_respects_different_passwords_per_tenant(client):
    """Each tenant-account can have its own password (per-(tenant,email)
    identity, not a single global one) — logging in with a password that only
    matches one of the two tenants must resolve directly, not disambiguate."""
    email = f"logintest-{uuid.uuid4().hex[:8]}@example.com"
    tenant_a, _ = await create_new_tenant_and_user(
        tenant_name="Diffpass Corp A", email=email, auth_method="password",
        hashed_password=hash_password("passwordA"),
    )
    tenant_b, _ = await create_new_tenant_and_user(
        tenant_name="Diffpass Corp B", email=email, auth_method="password",
        hashed_password=hash_password("passwordB"),
    )

    login = await client.post("/api/v1/auth/login", data={"username": email, "password": "passwordA"})
    assert login.status_code == 200
    assert login.json()["tenant_id"] == tenant_a.id


@pytest.mark.asyncio
async def test_register_nudge_is_non_blocking(client):
    """Regression test for the second pre-existing gap: register() never
    checked for an existing email. Now it surfaces existing workspaces
    informationally but must still create the new tenant successfully."""
    email = f"nudgetest-{uuid.uuid4().hex[:8]}@example.com"
    first = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Nudge Test", "tenant_name": "Nudge Corp 1",
    })
    assert first.json()["existing_workspaces"] == []

    second = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Nudge Test", "tenant_name": "Nudge Corp 2",
    })
    assert second.status_code == 200
    assert len(second.json()["existing_workspaces"]) == 1
    assert second.json()["existing_workspaces"][0]["tenant_id"] == first.json()["tenant_id"]
    # Not blocked — a real second tenant was created.
    assert second.json()["tenant_id"] != first.json()["tenant_id"]
