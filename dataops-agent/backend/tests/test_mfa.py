"""Security Master Ranking Item #13 -- TOTP MFA.

MEASURED BEFORE BUILDING: no TOTP, WebAuthn, MFA or 2FA field, route, or
dependency existed anywhere (backend, frontend, docs -- the only "mfa"
substring in the tree was inside a fake Fernet token in a test). The three
login paths (password, email-code, Google) plus the pending-identity
finalisation and workspace switch all converged on one call,
issue_token_and_remember(), with no second step. That convergence is what
the design leans on: establish_session() now sits at that point, so every
path gets the second factor from one place.

What this file proves: the setup/enable/login happy path; wrong-code
rejection at enable and at login; TOTP replay within the window; backup
code login, single-use, and the count; challenge exhaustion; the secret and
backup codes are not readable in the raw row; the owner/admin mandate with
its grace period and the enrolment exemption; the email-code/Google path
and workspace switch get the same gate; disable is refused for owners and
honoured for others; and composition with Items #3 and #4.
"""

import uuid
from datetime import datetime, timedelta

import pyotp
import pytest
from sqlalchemy import select, text

from models.all_models import User
from services import mfa_service
from services.auth_service import resolve_identity, switch_workspace
from services.rate_limit import PREAUTH_PATHS, RateLimitCategory, categorise
from services.tenant_context import tenant_session
from services.token_revocation import current_epoch

pytestmark = pytest.mark.asyncio
PW = "test1234"


async def _register(client, role="owner"):
    email = f"mfa-{uuid.uuid4().hex[:8]}@example.com"
    reg = (await client.post("/api/v1/auth/register", json={
        "email": email, "password": PW, "full_name": "MFA", "tenant_name": f"MFA Corp {uuid.uuid4().hex[:6]}",
    })).json()
    if role != "owner":
        async with tenant_session(reg["tenant_id"]) as db:
            u = (await db.execute(select(User).where(User.id == reg["user_id"]))).scalar_one()
            u.role = role
            await db.commit()
    return {"email": email, "token": reg["access_token"], "tenant_id": reg["tenant_id"],
            "user_id": reg["user_id"], "h": {"Authorization": f"Bearer {reg['access_token']}"}}


async def _login(client, email, password=PW):
    return await client.post("/api/v1/auth/login", data={"username": email, "password": password})


async def _enable(client, acct):
    """Full setup: returns (secret, backup_codes, fresh_headers)."""
    setup = (await client.post("/api/v1/auth/mfa/setup", headers=acct["h"])).json()
    secret = setup["secret"]
    r = await client.post("/api/v1/auth/mfa/enable", headers=acct["h"],
                          json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    body = r.json()
    return secret, body["backup_codes"], {"Authorization": f"Bearer {body['access_token']}"}


# ── Task 3 + 7: setup, verify-and-enable, happy path ─────────────────────────

async def test_setup_returns_a_provisioning_uri_and_nothing_is_enabled_yet(client):
    a = await _register(client)
    st = (await client.get("/api/v1/auth/mfa/status", headers=a["h"])).json()
    assert st == {**st, "enabled": False, "required": True, "overdue": False}
    assert st["enrollment_deadline"] is not None          # owner: mandatory, in grace

    r = await client.post("/api/v1/auth/mfa/setup", headers=a["h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provisioning_uri"].startswith("otpauth://totp/Wunomo:") and "issuer=Wunomo" in body["provisioning_uri"]
    assert body["secret"] in body["provisioning_uri"]
    # pending only: the row is untouched and login still needs no second step
    async with tenant_session(a["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == a["user_id"]))).scalar_one()
    assert u.mfa_enabled is False and u.mfa_secret is None
    assert "access_token" in (await _login(client, a["email"])).json()


async def test_wrong_code_at_enable_is_rejected_and_nothing_persists(client):
    a = await _register(client)
    setup = (await client.post("/api/v1/auth/mfa/setup", headers=a["h"])).json()
    wrong = str((int(pyotp.TOTP(setup["secret"]).now()) + 1) % 1_000_000).zfill(6)
    r = await client.post("/api/v1/auth/mfa/enable", headers=a["h"], json={"code": wrong})
    assert r.status_code == 400 and "not valid" in r.json()["detail"]
    async with tenant_session(a["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == a["user_id"]))).scalar_one()
    assert u.mfa_enabled is False and u.mfa_secret is None and u.mfa_backup_codes is None


async def test_enable_happy_path_then_login_requires_and_accepts_a_code(client):
    a = await _register(client)
    secret, codes, fresh = await _enable(client, a)
    assert len(codes) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    st = (await client.get("/api/v1/auth/mfa/status", headers=fresh)).json()
    assert st["enabled"] is True and st["backup_codes_remaining"] == 10 and st["enrollment_deadline"] is None

    # login: first factor alone no longer yields a token
    r = await _login(client, a["email"])
    assert r.status_code == 200, r.text
    step1 = r.json()
    assert step1["status"] == "mfa_required" and "access_token" not in step1 and step1["mfa_token"]

    # second factor: a fresh code (the enable code is replay-locked for its window)
    code = pyotp.TOTP(secret).at(datetime.utcnow() + timedelta(seconds=30))
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": code})
    assert r.status_code == 200, r.text
    assert r.json()["factor"] == "totp" and r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["mfa_enabled"] is True
    # the challenge is single-use
    r2 = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": code})
    assert r2.status_code == 400


async def test_wrong_code_at_login_is_rejected_with_attempts_left(client):
    a = await _register(client)
    secret, _, _ = await _enable(client, a)
    step1 = (await _login(client, a["email"])).json()
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": "000000"})
    assert r.status_code == 400 and "4 attempt(s) left" in r.json()["detail"]
    # the challenge survives a wrong guess; the right code still works
    code = pyotp.TOTP(secret).at(datetime.utcnow() + timedelta(seconds=30))
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": code})
    assert r.status_code == 200, r.text


async def test_totp_code_cannot_be_replayed_inside_its_window(client):
    a = await _register(client)
    secret, _, _ = await _enable(client, a)
    code = pyotp.TOTP(secret).at(datetime.utcnow() + timedelta(seconds=30))
    t1 = (await _login(client, a["email"])).json()["mfa_token"]
    assert (await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t1, "code": code})).status_code == 200
    t2 = (await _login(client, a["email"])).json()["mfa_token"]
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t2, "code": code})
    assert r.status_code == 400, "a shoulder-surfed code must be dead once its owner has used it"


# ── Task 6 + 7: backup codes ─────────────────────────────────────────────────

async def test_backup_code_logs_in_once_and_is_then_dead(client):
    a = await _register(client)
    _, codes, _ = await _enable(client, a)
    t1 = (await _login(client, a["email"])).json()["mfa_token"]
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t1, "code": codes[0].lower()})
    assert r.status_code == 200, r.text
    assert r.json()["factor"] == "backup" and r.json()["backup_codes_remaining"] == 9
    # same code again, new challenge: refused
    t2 = (await _login(client, a["email"])).json()["mfa_token"]
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t2, "code": codes[0]})
    assert r.status_code == 400
    # a different unused code still works
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t2, "code": codes[1]})
    assert r.status_code == 200 and r.json()["backup_codes_remaining"] == 8


async def test_challenge_dies_after_five_wrong_codes_even_if_the_sixth_is_right(client):
    a = await _register(client)
    secret, _, _ = await _enable(client, a)
    t = (await _login(client, a["email"])).json()["mfa_token"]
    for i in range(5):
        r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t, "code": "000000"})
        assert r.status_code == 400
    assert "Too many" in r.json()["detail"]
    code = pyotp.TOTP(secret).at(datetime.utcnow() + timedelta(seconds=30))
    r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t, "code": code})
    assert r.status_code == 400 and "Log in again" in r.json()["detail"]


# ── Task 2 + 6: storage ──────────────────────────────────────────────────────

async def test_secret_and_backup_codes_are_not_readable_in_the_raw_row(client):
    a = await _register(client)
    secret, codes, _ = await _enable(client, a)
    async with tenant_session(a["tenant_id"]) as db:
        raw = (await db.execute(text(
            "SELECT mfa_secret::text, mfa_backup_codes::text FROM users WHERE id = :id"), {"id": a["user_id"]})).one()
    assert secret not in raw[0] and raw[0].strip('"').startswith("gAAAA"), raw[0][:40]
    for c in codes:
        assert c not in raw[1] and c.replace("-", "") not in raw[1]
    # and the ORM read decrypts to exactly the secret the authenticator holds
    async with tenant_session(a["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == a["user_id"]))).scalar_one()
    assert u.mfa_secret == {"secret": secret}


# ── Task 5: mandatory for owner/admin ────────────────────────────────────────

async def test_owner_past_grace_is_blocked_everywhere_except_the_way_out(client):
    a = await _register(client)
    async with tenant_session(a["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == a["user_id"]))).scalar_one()
        assert u.mfa_required_since is not None            # stamped at signup
        u.mfa_required_since = datetime.utcnow() - timedelta(days=8)
        await db.commit()
    r = await client.get("/api/v1/sources/", headers=a["h"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_enrollment_required"
    # the auth routes stay open so they can enrol and see why
    assert (await client.get("/api/v1/auth/me", headers=a["h"])).json()["mfa_overdue"] is True
    assert (await client.get("/api/v1/auth/mfa/status", headers=a["h"])).json()["overdue"] is True
    _, _, fresh = await _enable(client, a)
    assert (await client.get("/api/v1/sources/", headers=fresh)).status_code == 200


async def test_owner_inside_grace_and_a_viewer_past_it_are_not_blocked(client):
    owner = await _register(client)
    assert (await client.get("/api/v1/sources/", headers=owner["h"])).status_code == 200
    viewer = await _register(client, role="viewer")
    async with tenant_session(viewer["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == viewer["user_id"]))).scalar_one()
        u.mfa_required_since = datetime.utcnow() - timedelta(days=30)   # irrelevant for a viewer
        await db.commit()
    me = (await client.get("/api/v1/auth/me", headers=viewer["h"])).json()
    assert me["mfa_required"] is False and me["mfa_overdue"] is False
    assert (await client.get("/api/v1/sources/", headers=viewer["h"])).status_code == 200


async def test_promotion_to_admin_starts_the_grace_clock_now(client):
    owner = await _register(client)
    # a member created a month ago, then promoted today
    async with tenant_session(owner["tenant_id"]) as db:
        member = User(id=str(uuid.uuid4()), tenant_id=owner["tenant_id"], email=f"m-{uuid.uuid4().hex[:6]}@example.com",
                      hashed_password="x", role="viewer", created_at=datetime.utcnow() - timedelta(days=30))
        db.add(member)
        await db.commit()
        member_id = member.id
    r = await client.patch(f"/api/v1/team/members/{member_id}/role", headers=owner["h"], json={"role": "admin"})
    assert r.status_code == 200, r.text
    async with tenant_session(owner["tenant_id"]) as db:
        m = (await db.execute(select(User).where(User.id == member_id))).scalar_one()
    assert m.mfa_required_since is not None
    assert datetime.utcnow() - m.mfa_required_since < timedelta(minutes=1)
    assert not mfa_service.enrollment_overdue(m.role, m.mfa_enabled, m.mfa_required_since, m.created_at)


async def test_owner_cannot_disable_but_a_viewer_can_with_a_valid_code(client):
    owner = await _register(client)
    secret, _, fresh = await _enable(client, owner)
    code = pyotp.TOTP(secret).at(datetime.utcnow() + timedelta(seconds=30))
    r = await client.post("/api/v1/auth/mfa/disable", headers=fresh, json={"code": code})
    assert r.status_code == 403

    viewer = await _register(client, role="viewer")
    secret, _, fresh = await _enable(client, viewer)
    assert (await _login(client, viewer["email"])).json()["status"] == "mfa_required"
    r = await client.post("/api/v1/auth/mfa/disable", headers=fresh, json={"code": "000000"})
    assert r.status_code == 400                             # a code is required
    code = pyotp.TOTP(secret).at(datetime.utcnow() + timedelta(seconds=30))
    r = await client.post("/api/v1/auth/mfa/disable", headers=fresh, json={"code": code})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert "access_token" in (await _login(client, viewer["email"])).json()   # no second step now


# ── Task 4: every login path gets the gate ───────────────────────────────────

async def test_email_code_and_google_path_get_the_same_gate(client):
    """resolve_identity() is the shared post-proof resolver for BOTH the
    email-code and Google routes; a user with MFA must come back as a
    challenge from it, never a token."""
    a = await _register(client)
    await _enable(client, a)
    out = await resolve_identity(a["email"], "email_code")
    assert out["status"] == "mfa_required" and "token" not in out and out["mfa_token"]
    out = await resolve_identity(a["email"], "google", google_id="g-1", provider_email_verified=True)
    assert out["status"] == "mfa_required"


async def test_workspace_switch_into_an_mfa_account_is_challenged(client):
    """Same email, two tenants; the target account has MFA, the current one
    does not. Proving identity for tenant A must not skip tenant B's second
    factor."""
    a = await _register(client)
    secret, _, _ = await _enable(client, a)
    # a second tenant for the same email, without MFA
    reg_b = (await client.post("/api/v1/auth/register", json={
        "email": a["email"], "password": PW, "full_name": "MFA", "tenant_name": f"Other {uuid.uuid4().hex[:6]}",
    })).json()
    assert reg_b.get("tenant_id") and reg_b["tenant_id"] != a["tenant_id"], reg_b
    out = await switch_workspace(a["email"], reg_b["tenant_id"], a["tenant_id"])
    assert out["status"] == "mfa_required" and "access_token" not in out


# ── Task 8: composition with Item #4 (revocation) ────────────────────────────

async def test_enabling_mfa_bumps_the_epoch_and_hands_back_a_surviving_token(client):
    a = await _register(client)
    before = await current_epoch(a["user_id"])
    _, _, fresh = await _enable(client, a)
    assert await current_epoch(a["user_id"]) == before + 1
    assert (await client.get("/api/v1/auth/me", headers=a["h"])).status_code == 401     # old session dead
    assert (await client.get("/api/v1/auth/me", headers=fresh)).status_code == 200      # the caller lives on


async def test_backup_code_login_does_not_bump_the_epoch(client):
    a = await _register(client)
    _, codes, fresh = await _enable(client, a)
    epoch = await current_epoch(a["user_id"])
    t = (await _login(client, a["email"])).json()["mfa_token"]
    assert (await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": t, "code": codes[0]})).status_code == 200
    assert await current_epoch(a["user_id"]) == epoch
    assert (await client.get("/api/v1/auth/me", headers=fresh)).status_code == 200


# ── Task 9: composition with Item #3 (rate limiting) ─────────────────────────

def test_mfa_verify_is_in_the_preauth_bucket():
    assert "/api/v1/auth/mfa/verify" in PREAUTH_PATHS
    assert categorise("/api/v1/auth/mfa/verify") == RateLimitCategory.PREAUTH
    # the authenticated management routes are ordinary per-tenant traffic
    assert categorise("/api/v1/auth/mfa/setup") != RateLimitCategory.PREAUTH


async def test_verify_is_rate_limited_per_ip_like_login(client):
    a = await _register(client)
    await _enable(client, a)
    # the pre-auth bucket counts every request whatever the outcome; 10/min
    codes = []
    for _ in range(12):
        r = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": "nope", "code": "000000"})
        codes.append(r.status_code)
    assert 429 in codes and codes[-1] == 429, codes
