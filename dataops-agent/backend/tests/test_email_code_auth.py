import uuid
import pytest

import services.auth_service as auth_service
from services.auth_service import create_new_tenant_and_user, hash_password


@pytest.fixture
def captured_code(monkeypatch):
    """Mocks Resend delivery (already proven live separately — see git log /
    CLAUDE.md) so the test suite doesn't consume real Resend quota or hit its
    sandbox recipient restriction, while still exercising the real
    generate/hash/store code path and capturing the real code for the test
    to submit."""
    captured = {}

    async def fake_send(email, code):
        captured["email"] = email
        captured["code"] = code
        return "fake-message-id"

    monkeypatch.setattr(auth_service, "_send_code_email", fake_send)
    return captured


def unique_email():
    return f"emailcode-{uuid.uuid4().hex[:10]}@example.com"


@pytest.mark.asyncio
async def test_request_then_verify_creates_new_tenant(client, captured_code):
    email = unique_email()
    req = await client.post("/api/v1/auth/email-code/request", json={"email": email})
    assert req.status_code == 200
    assert req.json()["status"] == "sent"
    code = captured_code["code"]
    assert len(code) == 6 and code.isdigit()

    verify = await client.post("/api/v1/auth/email-code/verify", json={
        "email": email, "code": code, "new_tenant_name": "Email Code Test Corp",
    })
    assert verify.status_code == 200
    body = verify.json()
    assert "access_token" in body
    assert body["tenant_id"]


@pytest.mark.asyncio
async def test_wrong_code_rejected_and_correct_code_still_works_within_attempt_limit(client, captured_code):
    email = unique_email()
    await client.post("/api/v1/auth/email-code/request", json={"email": email})
    code = captured_code["code"]

    wrong = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": "000000"})
    assert wrong.status_code == 400

    right = await client.post("/api/v1/auth/email-code/verify", json={
        "email": email, "code": code, "new_tenant_name": "Wrong Then Right Corp",
    })
    assert right.status_code == 200


@pytest.mark.asyncio
async def test_code_is_single_use(client, captured_code):
    email = unique_email()
    await client.post("/api/v1/auth/email-code/request", json={"email": email})
    code = captured_code["code"]

    first = await client.post("/api/v1/auth/email-code/verify", json={
        "email": email, "code": code, "new_tenant_name": "Single Use Corp",
    })
    assert first.status_code == 200

    replay = await client.post("/api/v1/auth/email-code/verify", json={
        "email": email, "code": code, "new_tenant_name": "Single Use Corp Replay",
    })
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_exhausting_max_attempts_invalidates_the_code(client, captured_code):
    email = unique_email()
    await client.post("/api/v1/auth/email-code/request", json={"email": email})
    code = captured_code["code"]

    for _ in range(auth_service.MAX_VERIFY_ATTEMPTS):
        r = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": "000000"})
        assert r.status_code == 400

    # Correct code, submitted only after the attempt budget is already spent, must still fail.
    late = await client.post("/api/v1/auth/email-code/verify", json={
        "email": email, "code": code, "new_tenant_name": "Too Late Corp",
    })
    assert late.status_code == 400


@pytest.mark.asyncio
async def test_no_account_without_new_tenant_name_does_not_create_one(client, captured_code):
    email = unique_email()
    await client.post("/api/v1/auth/email-code/request", json={"email": email})
    code = captured_code["code"]

    verify = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    assert verify.json()["status"] == "no_account"
    assert "access_token" not in verify.json()


@pytest.mark.asyncio
async def test_returning_user_single_match_logs_in_to_same_tenant(client, captured_code):
    email = unique_email()
    tenant, user = await create_new_tenant_and_user(
        tenant_name="Returning Corp", email=email, auth_method="email_code", email_verified=True,
    )

    await client.post("/api/v1/auth/email-code/request", json={"email": email})
    code = captured_code["code"]
    verify = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    assert verify.json()["tenant_id"] == tenant.id
    assert verify.json()["user_id"] == user.id


@pytest.mark.asyncio
async def test_multiple_tenant_matches_returns_choose_workspace(client, captured_code):
    email = unique_email()
    tenant_a, _ = await create_new_tenant_and_user(
        tenant_name="Multi Corp A", email=email, auth_method="password",
        hashed_password=hash_password("whatever"),
    )
    tenant_b, _ = await create_new_tenant_and_user(
        tenant_name="Multi Corp B", email=email, auth_method="password",
        hashed_password=hash_password("whatever"),
    )

    await client.post("/api/v1/auth/email-code/request", json={"email": email})
    code = captured_code["code"]
    verify = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    assert verify.json()["status"] == "choose_workspace"
    tenant_ids = {opt["tenant_id"] for opt in verify.json()["options"]}
    assert tenant_ids == {tenant_a.id, tenant_b.id}

    # The code is already single-use consumed by this point — resubmitting it
    # a second time must fail, proving the resolution-token path is genuinely
    # necessary and not just a redundant convenience.
    replay = await client.post("/api/v1/auth/email-code/verify", json={
        "email": email, "code": code, "tenant_id": tenant_a.id,
    })
    assert replay.status_code == 400

    # Finalizing via the resolution token must work instead.
    resolution_token = verify.json()["resolution_token"]
    resolved = await client.post("/api/v1/auth/resolve-workspace", json={
        "resolution_token": resolution_token, "tenant_id": tenant_a.id,
    })
    assert resolved.status_code == 200
    assert resolved.json()["tenant_id"] == tenant_a.id
    assert "access_token" in resolved.json()

    # Single-use: replaying the same resolution token must fail.
    replay_resolution = await client.post("/api/v1/auth/resolve-workspace", json={
        "resolution_token": resolution_token, "tenant_id": tenant_b.id,
    })
    assert replay_resolution.status_code == 400


@pytest.mark.asyncio
async def test_auto_link_sets_email_verified_on_existing_password_account(client, captured_code):
    """The approved auto-link design: a successful email-code verification
    against a specific existing tenant links (sets email_verified) without
    requiring a separate confirmation step."""
    from database import AsyncSessionLocal
    from models.all_models import User

    email = unique_email()
    tenant, user = await create_new_tenant_and_user(
        tenant_name="Link Test Corp", email=email, auth_method="password",
        hashed_password=hash_password("somepassword"),
    )
    assert user.email_verified is False

    await client.post("/api/v1/auth/email-code/request", json={"email": email, "intended_tenant_id": tenant.id})
    code = captured_code["code"]
    verify = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": code})
    assert verify.status_code == 200
    assert verify.json()["tenant_id"] == tenant.id

    async with AsyncSessionLocal() as db:
        refreshed = await db.get(User, user.id)
    assert refreshed.email_verified is True


@pytest.mark.asyncio
async def test_resend_cooldown_blocks_immediate_second_request(client, captured_code):
    email = unique_email()
    first = await client.post("/api/v1/auth/email-code/request", json={"email": email})
    assert first.json()["status"] == "sent"

    second = await client.post("/api/v1/auth/email-code/request", json={"email": email})
    assert second.json()["status"] == "rate_limited"


@pytest.mark.asyncio
async def test_rate_limit_bookkeeping_is_symmetric_for_nonexistent_emails(client, captured_code):
    """Enumeration-safety property: a never-before-seen email must rate-limit
    identically to a real one under the same request pattern."""
    email = unique_email()
    first = await client.post("/api/v1/auth/email-code/request", json={"email": email})
    second = await client.post("/api/v1/auth/email-code/request", json={"email": email})
    assert first.json()["status"] == "sent"
    assert second.json()["status"] == "rate_limited"
