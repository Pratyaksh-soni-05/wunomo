"""Token revocation (Security Master Ranking Item #4).

The headline test is `test_exploit_replayed_jwt_after_removal_is_rejected`: the
exact live-reproduced exploit — capture a JWT, remove the user, replay the
token — asserted to fail closed.
"""
import uuid

import pytest


async def _register(client, prefix: str) -> dict:
    r = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": f"{prefix} owner",
        "tenant_name": f"{prefix} Co {uuid.uuid4().hex[:6]}",
    })
    assert r.status_code == 200, r.text
    return r.json()


async def _invite_and_accept(client, owner_token: str, role: str = "data_analyst") -> dict:
    """A second real member in the owner's tenant, via the real invite flow."""
    email = f"member-{uuid.uuid4().hex[:8]}@example.com"
    inv = await client.post(
        "/api/v1/team/invites",
        json={"email": email, "role": role},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert inv.status_code == 200, inv.text
    token = inv.json()["invite_link_token"]

    acc = await client.post("/api/v1/team/invites/accept", json={
        "token": token, "password": "test1234", "full_name": "Member",
    })
    assert acc.status_code == 200, acc.text
    return acc.json()


def owner_email(reg: dict) -> str:
    """The email `_register` used, recovered from its own token so a second
    login can be performed for the same user."""
    from jose import jwt as jose_jwt
    from config import settings
    return jose_jwt.decode(reg["access_token"], settings.JWT_SECRET,
                           algorithms=[settings.JWT_ALGORITHM])["email"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── The exploit ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exploit_replayed_jwt_after_removal_is_rejected(client):
    """THE Item #4 exploit, end to end through real endpoints.

    Capture a member's JWT while they are legitimately active, have an owner
    remove them, then replay the captured token against a protected endpoint.
    The token is still cryptographically valid and unexpired — only revocation
    can stop it.
    """
    owner = await _register(client, "revoke-owner")
    member = await _invite_and_accept(client, owner["access_token"])
    stolen_token = member["access_token"]

    # The token genuinely works before removal, or the test proves nothing.
    before = await client.get("/api/v1/team/members", headers=_auth(stolen_token))
    assert before.status_code == 200, (
        f"precondition failed: the captured token should work before removal, "
        f"got {before.status_code}"
    )

    removed = await client.delete(
        f"/api/v1/team/members/{member['user_id']}",
        headers=_auth(owner["access_token"]),
    )
    assert removed.status_code == 200, removed.text

    after = await client.get("/api/v1/team/members", headers=_auth(stolen_token))
    assert after.status_code == 401, (
        f"REPLAY SUCCEEDED: a JWT captured before removal still returned "
        f"{after.status_code} afterwards. The token is unexpired and correctly "
        f"signed, so nothing but revocation can reject it."
    )


@pytest.mark.asyncio
async def test_exploit_replayed_jwt_after_demotion_loses_the_old_role(client):
    """The demotion half of the same exploit.

    A token minted while the user was an admin must not keep admin capability
    after they are demoted to viewer — the JWT still carries `role: admin`, so
    trusting the claim rather than re-checking would leave this open.
    """
    owner = await _register(client, "demote-owner")
    member = await _invite_and_accept(client, owner["access_token"], role="admin")
    admin_token = member["access_token"]

    # An admin can list invites; a viewer cannot.
    before = await client.get("/api/v1/team/invites", headers=_auth(admin_token))
    assert before.status_code == 200, (
        f"precondition failed: admin should be able to list invites, got "
        f"{before.status_code}"
    )

    demoted = await client.patch(
        f"/api/v1/team/members/{member['user_id']}/role",
        json={"role": "viewer"},
        headers=_auth(owner["access_token"]),
    )
    assert demoted.status_code == 200, demoted.text

    after = await client.get("/api/v1/team/invites", headers=_auth(admin_token))
    assert after.status_code in (401, 403), (
        f"PRIVILEGE RETAINED: a token minted while the user was admin still "
        f"returned {after.status_code} after demotion to viewer."
    )


# ── The revocation machinery ─────────────────────────────────────────────────

def test_every_issued_token_carries_a_unique_jti():
    """Revoking ONE token is only possible if tokens are distinguishable."""
    from jose import jwt as jose_jwt
    from config import settings
    from services.auth_service import create_token

    jtis = [
        jose_jwt.decode(create_token({"sub": "u1"}), settings.JWT_SECRET,
                        algorithms=[settings.JWT_ALGORITHM])["jti"]
        for _ in range(5)
    ]
    assert all(jtis), "every token must carry a jti"
    assert len(set(jtis)) == 5, "jti must be unique per token, not per user"


@pytest.mark.asyncio
async def test_blocklisted_jti_is_revoked_and_ttl_never_outlives_the_token():
    import time
    from services.token_revocation import (
        BLOCKLIST_PREFIX, _redis, is_revoked, revoke_jti,
    )

    jti = f"jti-{uuid.uuid4().hex[:10]}"
    exp = int(time.time()) + 900  # 15 minutes of life left
    payload = {"sub": "someone", "jti": jti, "epoch": 0}

    assert await is_revoked(payload) is False
    await revoke_jti(jti, exp)
    assert await is_revoked(payload) is True

    # The entry must expire with the token, never outlive it: a blocklist that
    # accumulates forever is unbounded keyspace, and one that expires early
    # silently un-revokes a token.
    ttl = await _redis().ttl(f"{BLOCKLIST_PREFIX}:{jti}")
    assert 0 < ttl <= 900


@pytest.mark.asyncio
async def test_already_expired_token_is_not_written_to_the_blocklist():
    """An expired JWT is rejected by the JWT layer anyway, so an entry for it
    would be pure keyspace growth with no security value."""
    import time
    from services.token_revocation import BLOCKLIST_PREFIX, _redis, revoke_jti

    jti = f"expired-{uuid.uuid4().hex[:10]}"
    await revoke_jti(jti, int(time.time()) - 60)
    assert await _redis().exists(f"{BLOCKLIST_PREFIX}:{jti}") == 0


@pytest.mark.asyncio
async def test_epoch_bump_revokes_older_tokens_but_not_newer_ones():
    from services.token_revocation import bump_epoch, current_epoch, is_revoked

    user_id = f"user-{uuid.uuid4().hex[:10]}"
    assert await current_epoch(user_id) == 0

    old_token = {"sub": user_id, "jti": "a", "epoch": 0}
    assert await is_revoked(old_token) is False

    new_epoch = await bump_epoch(user_id)
    assert new_epoch == 1
    assert await is_revoked(old_token) is True, "the pre-bump token must be dead"
    # A token minted after the bump carries the new epoch and must survive.
    assert await is_revoked({"sub": user_id, "jti": "b", "epoch": new_epoch}) is False


@pytest.mark.asyncio
async def test_one_users_revocation_does_not_touch_another_user():
    """Epochs are per-user; a shared or mis-keyed counter would log everyone
    out the first time anyone revoked."""
    from services.token_revocation import bump_epoch, is_revoked

    a, b = f"a-{uuid.uuid4().hex[:8]}", f"b-{uuid.uuid4().hex[:8]}"
    await bump_epoch(a)
    assert await is_revoked({"sub": a, "epoch": 0}) is True
    assert await is_revoked({"sub": b, "epoch": 0}) is False


# ── POST /auth/revoke ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revoke_all_logs_out_every_session_including_the_caller(client):
    owner = await _register(client, "revokeall")
    token = owner["access_token"]
    assert (await client.get("/api/v1/team/members", headers=_auth(token))).status_code == 200

    r = await client.post("/api/v1/auth/revoke", json={"scope": "all"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] == "all_sessions"

    after = await client.get("/api/v1/team/members", headers=_auth(token))
    assert after.status_code == 401, (
        f"the caller's own token survived a scope=all revocation ({after.status_code})"
    )


@pytest.mark.asyncio
async def test_revoke_all_kills_a_second_session_of_the_same_user(client):
    """The actual point of "log out all devices": a token the caller is not
    currently holding must die too."""
    owner = await _register(client, "revokemulti")

    second = await client.post("/api/v1/auth/login", data={
        "username": owner_email(owner), "password": "test1234",
    })
    assert second.status_code == 200, second.text
    other_device = second.json()["access_token"]
    assert (await client.get("/api/v1/team/members",
                             headers=_auth(other_device))).status_code == 200

    await client.post("/api/v1/auth/revoke", json={"scope": "all"},
                      headers=_auth(owner["access_token"]))

    after = await client.get("/api/v1/team/members", headers=_auth(other_device))
    assert after.status_code == 401, (
        f"a second device's token survived 'log out all devices' ({after.status_code})"
    )


@pytest.mark.asyncio
async def test_revoke_current_kills_only_the_calling_token(client):
    owner = await _register(client, "revokeone")

    second = await client.post("/api/v1/auth/login", data={
        "username": owner_email(owner), "password": "test1234",
    })
    other_device = second.json()["access_token"]

    r = await client.post("/api/v1/auth/revoke", json={"scope": "current"},
                          headers=_auth(owner["access_token"]))
    assert r.status_code == 200
    assert r.json()["revoked"] == "current_session"

    assert (await client.get("/api/v1/team/members",
                             headers=_auth(owner["access_token"]))).status_code == 401
    assert (await client.get("/api/v1/team/members",
                             headers=_auth(other_device))).status_code == 200, (
        "scope=current must not disturb the user's other sessions"
    )


@pytest.mark.asyncio
async def test_revoke_rejects_an_unknown_scope(client):
    owner = await _register(client, "revokebad")
    r = await client.post("/api/v1/auth/revoke", json={"scope": "everything"},
                          headers=_auth(owner["access_token"]))
    assert r.status_code == 400


# ── Both middlewares, not only get_current_user ──────────────────────────────

@pytest.mark.asyncio
async def test_revoked_token_sets_no_tenant_context_in_the_middleware():
    """A revoked token must not scope RLS on its way to being rejected.

    Checked at the middleware directly: by the time get_current_user returns
    401 the tenant context has already been established for that request, so
    only the middleware's own behaviour can prove this.
    """
    from api.v1.tenant_middleware import TenantContextMiddleware
    from services.auth_service import create_token
    from services.token_revocation import bump_epoch

    user_id = f"mw-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    token = create_token({"sub": user_id, "tenant_id": tenant_id, "epoch": 0})
    headers = [(b"authorization", f"Bearer {token}".encode())]

    assert await TenantContextMiddleware._tenant_from_headers(headers) == tenant_id

    await bump_epoch(user_id)
    assert await TenantContextMiddleware._tenant_from_headers(headers) is None, (
        "a revoked token still established an RLS tenant context"
    )


@pytest.mark.asyncio
async def test_revoked_token_gets_no_tenant_rate_limit_bucket():
    """A revoked token must not spend its former tenant's rate-limit budget."""
    from api.v1.rate_limit_middleware import RateLimitMiddleware
    from services.auth_service import create_token
    from services.token_revocation import bump_epoch

    user_id = f"rlmw-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    token = create_token({"sub": user_id, "tenant_id": tenant_id, "epoch": 0})
    headers = [(b"authorization", f"Bearer {token}".encode())]

    assert await RateLimitMiddleware._tenant_from_headers(headers) == tenant_id

    await bump_epoch(user_id)
    assert await RateLimitMiddleware._tenant_from_headers(headers) is None, (
        "a revoked token was still keyed to its tenant's rate-limit bucket"
    )


# ── tenant_id claim is verified, not trusted ─────────────────────────────────

@pytest.mark.asyncio
async def test_token_whose_tenant_id_does_not_match_the_user_row_is_rejected(client):
    """The claim was previously trusted without ever being compared to the DB.

    Forging it requires the signing key, so this is defence in depth rather
    than a live hole — but both middlewares scope RLS and rate limiting off
    this claim before get_current_user runs, so it should be checked rather
    than assumed.
    """
    owner = await _register(client, "tenantmismatch")
    from services.auth_service import create_token

    forged = create_token({
        "sub": owner["user_id"],
        "tenant_id": str(uuid.uuid4()),   # a tenant this user does not belong to
        "email": "x@example.com", "role": "owner",
        "auth_method": "password", "epoch": 0,
    })

    r = await client.get("/api/v1/team/members", headers=_auth(forged))
    assert r.status_code == 401, (
        f"a validly-signed token claiming the wrong tenant was accepted "
        f"({r.status_code})"
    )
