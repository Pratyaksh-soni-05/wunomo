"""Security Master Ranking Item #14 -- enterprise SSO through WorkOS.

MEASURED FIRST: the Google OAuth flow's account resolution
(resolve_identity -> _link_and_issue -> establish_session ->
issue_token_and_remember) was reusable as-is; the SSO flow adds only the
provider leg (authorize URL, code exchange) and a tenant-scoped config.
These tests mock the WorkOS exchange exactly the way test_google_oauth.py
mocks Google's, and exercise everything after it for real: the domain
guard, JIT provisioning, linking, Option A / Option B MFA composition,
the epoch, the pre-auth index, and the rate-limit placement.

The live round-trip against WorkOS's Test Identity Provider is a separate,
manual proof (recorded in the commit); it cannot run in the suite because
it needs the deployment's redirect URI registered in the WorkOS dashboard.
"""

import uuid
from datetime import datetime, timedelta

import pyotp
import pytest
from jose import jwt
from sqlalchemy import select

from config import settings
from models.all_models import SsoDomain, User
from services import sso_service
from services.rate_limit import PREAUTH_PATHS, RateLimitCategory, categorise
from services.tenant_context import tenant_session
from services.token_revocation import bump_epoch

pytestmark = pytest.mark.asyncio
CONN = "conn_01TESTCONNECTIONXXXXXXXXXX"


async def _owner(client, domain_suffix=None):
    suffix = domain_suffix or f"{uuid.uuid4().hex[:8]}.example"
    email = f"owner@{suffix}"
    reg = (await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234", "full_name": "Owner", "tenant_name": f"SSO Corp {uuid.uuid4().hex[:6]}",
    })).json()
    return {"email": email, "domain": suffix, "tenant_id": reg["tenant_id"], "user_id": reg["user_id"],
            "token": reg["access_token"], "h": {"Authorization": f"Bearer {reg['access_token']}"}}


async def _configure(client, acct, **over):
    body = {"connection_id": CONN, "email_domain": acct["domain"], "enabled": True, "satisfies_mfa": False, **over}
    r = await client.put("/api/v1/auth/sso/config", headers=acct["h"], json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _mock_exchange(monkeypatch, *, email, connection_id=CONN, subject=None, first="Ada", last="Lovelace"):
    async def fake(code):
        assert code == "good-code"
        return {"id": subject or f"prof_{uuid.uuid4().hex[:10]}", "email": email, "connection_id": connection_id,
                "organization_id": "org_x", "first_name": first, "last_name": last, "idp_id": "idp-1"}
    monkeypatch.setattr(sso_service, "fetch_profile", fake)


async def _login_via_sso(client, monkeypatch, acct, email, asserted_email=None, **mock):
    """start -> (skip the IdP) -> callback, exactly what the browser does.
    `asserted_email` is what the IdP's profile claims, when that should
    differ from the email the flow was started with."""
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "WORKOS_CLIENT_ID", "client_fake")
    st = await client.post("/api/v1/auth/sso/start", json={"email": email})
    assert st.status_code == 200, st.text
    _mock_exchange(monkeypatch, email=asserted_email or email, **mock)
    return await client.post("/api/v1/auth/sso/callback", json={"code": "good-code", "state": st.json()["state"]})


# ── Config ───────────────────────────────────────────────────────────────────

async def test_owner_configures_sso_and_the_domain_index_follows(client):
    a = await _owner(client)
    cfg = await _configure(client, a)
    assert cfg == {"connection_id": CONN, "email_domain": a["domain"], "enabled": True, "satisfies_mfa": False}
    async with tenant_session(a["tenant_id"]) as db:
        rows = (await db.execute(select(SsoDomain).where(SsoDomain.tenant_id == a["tenant_id"]))).scalars().all()
    assert [(r.email_domain, r.connection_id) for r in rows] == [(a["domain"], CONN)]
    # disabling removes the index row; the config itself is kept
    await _configure(client, a, enabled=False)
    async with tenant_session(a["tenant_id"]) as db:
        assert (await db.execute(select(SsoDomain).where(SsoDomain.tenant_id == a["tenant_id"]))).scalars().all() == []
    assert (await client.get("/api/v1/auth/sso/config", headers=a["h"])).json()["connection_id"] == CONN


async def test_config_validation_and_domain_uniqueness(client):
    a = await _owner(client)
    r = await client.put("/api/v1/auth/sso/config", headers=a["h"],
                         json={"connection_id": "nope", "email_domain": a["domain"], "enabled": True})
    assert r.status_code == 400 and "conn_" in r.json()["detail"]
    r = await client.put("/api/v1/auth/sso/config", headers=a["h"],
                         json={"connection_id": CONN, "email_domain": "not a domain", "enabled": True})
    assert r.status_code == 400
    await _configure(client, a)
    b = await _owner(client)
    r = await client.put("/api/v1/auth/sso/config", headers=b["h"],
                         json={"connection_id": CONN, "email_domain": a["domain"], "enabled": True})
    assert r.status_code == 400 and "claimed" in r.json()["detail"]


async def test_only_an_owner_can_change_idp_mfa_trust(client):
    from services.auth_service import issue_token_for_user
    a = await _owner(client)
    await _configure(client, a)
    async with tenant_session(a["tenant_id"]) as db:
        admin = User(id=str(uuid.uuid4()), tenant_id=a["tenant_id"], email=f"admin@{a['domain']}",
                     hashed_password="x", role="admin", created_at=datetime.utcnow())
        db.add(admin)
        await db.commit()
        admin_h = {"Authorization": f"Bearer {issue_token_for_user(admin, 'password')}"}
    # an admin may edit connection/domain...
    r = await client.put("/api/v1/auth/sso/config", headers=admin_h,
                         json={"connection_id": CONN, "email_domain": a["domain"], "enabled": True, "satisfies_mfa": False})
    assert r.status_code == 200, r.text
    # ...but not flip the trust flag
    r = await client.put("/api/v1/auth/sso/config", headers=admin_h,
                         json={"connection_id": CONN, "email_domain": a["domain"], "enabled": True, "satisfies_mfa": True})
    assert r.status_code == 403
    r = await client.put("/api/v1/auth/sso/config", headers=a["h"],
                         json={"connection_id": CONN, "email_domain": a["domain"], "enabled": True, "satisfies_mfa": True})
    assert r.status_code == 200 and r.json()["satisfies_mfa"] is True
    from models.all_models import AuditLog
    async with tenant_session(a["tenant_id"]) as db:
        actions = [x.action for x in (await db.execute(select(AuditLog).where(
            AuditLog.tenant_id == a["tenant_id"]))).scalars().all()]
    assert "sso.mfa_trust_changed" in actions and "sso.config_updated" in actions


# ── Start ────────────────────────────────────────────────────────────────────

async def test_start_is_404_for_an_unknown_domain_and_503_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "WORKOS_CLIENT_ID", "client_fake")
    r = await client.post("/api/v1/auth/sso/start", json={"email": "nobody@no-such-domain.example"})
    assert r.status_code == 404
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "")
    r = await client.post("/api/v1/auth/sso/start", json={"email": "nobody@no-such-domain.example"})
    assert r.status_code == 503


async def test_start_returns_a_workos_authorize_url_for_the_tenants_connection(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "WORKOS_CLIENT_ID", "client_fake")
    r = await client.post("/api/v1/auth/sso/start", json={"email": f"someone@{a['domain']}"})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://api.workos.com/sso/authorize?")
    assert f"connection={CONN}" in url and "response_type=code" in url and "client_id=client_fake" in url
    assert "redirect_uri=" in url and r.json()["state"] in url


# ── Callback: resolution, guards, composition ────────────────────────────────

async def test_first_sso_login_provisions_a_viewer_with_no_password(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    email = f"newhire@{a['domain']}"
    r = await _login_via_sso(client, monkeypatch, a, email, subject="prof_new")
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    async with tenant_session(a["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
    assert u.role == "viewer" and u.hashed_password is None and u.sso_subject == "prof_new" and u.email_verified
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["auth_method"] == "sso" and me.json()["mfa_via_idp"] is False
    # a password login for this account is impossible: there is no password
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": "anything"})
    assert r.status_code == 400


async def test_sso_links_an_existing_password_account_in_the_domain(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    r = await _login_via_sso(client, monkeypatch, a, a["email"], subject="prof_owner")
    assert r.status_code == 200, r.text
    async with tenant_session(a["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == a["user_id"]))).scalar_one()
    assert u.sso_subject == "prof_owner" and u.role == "owner"    # linked, role untouched
    assert r.json()["user_id"] == a["user_id"]


async def test_domain_guard_refuses_an_email_outside_the_configured_domain(client, monkeypatch):
    """The SSO counterpart of Google's email_verified rule: the IdP is
    believed for its own domain only. An IdP asserting an address in
    another domain gets nothing -- no login, no account, no link."""
    a = await _owner(client)
    await _configure(client, a)
    victim = await _owner(client)                       # a real owner elsewhere
    # flow started in-domain; the IdP then asserts the victim's address
    r = await _login_via_sso(client, monkeypatch, a, f"attacker@{a['domain']}",
                             asserted_email=victim["email"], subject="prof_evil")
    assert r.status_code == 403 and "outside this workspace's SSO domain" in r.json()["detail"]
    async with tenant_session(victim["tenant_id"]) as db:
        v = (await db.execute(select(User).where(User.id == victim["user_id"]))).scalar_one()
    assert v.sso_subject is None
    async with tenant_session(a["tenant_id"]) as db:
        assert (await db.execute(select(User).where(User.email == victim["email"],
                                                    User.tenant_id == a["tenant_id"]))).scalar_one_or_none() is None


async def test_connection_mismatch_and_bad_state_are_refused(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    r = await _login_via_sso(client, monkeypatch, a, f"x@{a['domain']}", connection_id="conn_OTHER")
    assert r.status_code == 403 and "different identity provider" in r.json()["detail"]
    r = await client.post("/api/v1/auth/sso/callback", json={"code": "good-code", "state": "nope"})
    assert r.status_code == 400


async def test_state_is_single_use(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "WORKOS_CLIENT_ID", "client_fake")
    email = f"y@{a['domain']}"
    state = (await client.post("/api/v1/auth/sso/start", json={"email": email})).json()["state"]
    _mock_exchange(monkeypatch, email=email)
    assert (await client.post("/api/v1/auth/sso/callback", json={"code": "good-code", "state": state})).status_code == 200
    assert (await client.post("/api/v1/auth/sso/callback", json={"code": "good-code", "state": state})).status_code == 400


async def test_option_a_sso_still_requires_wunomo_totp(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    setup = (await client.post("/api/v1/auth/mfa/setup", headers=a["h"])).json()
    en = await client.post("/api/v1/auth/mfa/enable", headers=a["h"], json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert en.status_code == 200
    r = await _login_via_sso(client, monkeypatch, a, a["email"], subject="prof_owner")
    assert r.status_code == 200 and r.json()["status"] == "mfa_required" and "access_token" not in r.json()
    code = pyotp.TOTP(setup["secret"]).at(datetime.utcnow() + timedelta(seconds=30))
    v = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": code})
    assert v.status_code == 200 and v.json()["access_token"]


async def test_option_b_trusted_idp_skips_totp_and_satisfies_the_mandate_for_that_session(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a, satisfies_mfa=True)
    # owner has TOTP enabled AND is (artificially) past the enrolment grace
    setup = (await client.post("/api/v1/auth/mfa/setup", headers=a["h"])).json()
    en = await client.post("/api/v1/auth/mfa/enable", headers=a["h"], json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert en.status_code == 200
    r = await _login_via_sso(client, monkeypatch, a, a["email"], subject="prof_owner")
    assert r.status_code == 200 and r.json().get("access_token"), r.text
    tok = r.json()["access_token"]
    claims = jwt.decode(tok, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert claims["auth_method"] == "sso" and claims["mfa_via_idp"] is True
    # a second owner, un-enrolled and overdue: the SSO session is not blocked, a password one is
    b = await _owner(client)
    await _configure(client, b, satisfies_mfa=True)
    async with tenant_session(b["tenant_id"]) as db:
        u = (await db.execute(select(User).where(User.id == b["user_id"]))).scalar_one()
        u.mfa_required_since = datetime.utcnow() - timedelta(days=30)
        await db.commit()
    assert (await client.get("/api/v1/sources/", headers=b["h"])).status_code == 403     # password session: blocked
    r = await _login_via_sso(client, monkeypatch, b, b["email"], subject="prof_b")
    sso_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/v1/sources/", headers=sso_h)).status_code == 200         # IdP-trusted session: allowed


async def test_option_b_off_by_default_even_when_the_idp_would_be_trusted_elsewhere(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)     # satisfies_mfa default False
    r = await _login_via_sso(client, monkeypatch, a, f"z@{a['domain']}")
    claims = jwt.decode(r.json()["access_token"], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert "mfa_via_idp" not in claims


# ── Item #4 composition ──────────────────────────────────────────────────────

async def test_sso_tokens_carry_the_epoch_and_die_on_bump(client, monkeypatch):
    a = await _owner(client)
    await _configure(client, a)
    r = await _login_via_sso(client, monkeypatch, a, f"e@{a['domain']}")
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 200
    await bump_epoch(r.json()["user_id"])
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 401


# ── Item #3 composition ──────────────────────────────────────────────────────

def test_sso_start_and_callback_are_preauth_rate_limited():
    for p in ("/api/v1/auth/sso/start", "/api/v1/auth/sso/callback"):
        assert p in PREAUTH_PATHS and categorise(p) == RateLimitCategory.PREAUTH
    assert categorise("/api/v1/auth/sso/config") != RateLimitCategory.PREAUTH
