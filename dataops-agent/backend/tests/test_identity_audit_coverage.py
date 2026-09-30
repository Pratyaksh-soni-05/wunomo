"""Audit coverage for the six identity-creation/linking events found to
have none, 2026-09-30 -- a real WorkOS SSO browser round-trip succeeded
and server-side verification found sso.user_provisioned nowhere in
audit_logs, because _provision_sso_user() only ever called log.info(...)
with that string, never AuditTrail.log_action. A read-only sweep of every
place the backend creates or links identity found the same gap in five
sibling sites: create_new_tenant_and_user, accept_invite, and all three
branches of _link_and_issue (Google/email-code/SSO auto-link). See
docs/context/GOTCHAS.md for the full finding and the [CORRECTED] marker
on the 2026-09-22 entry this disproves.

Each test here fails on pre-fix code (0 matching audit_logs rows) and
passes after it. The three linking tests additionally assert the
payload's shape, not just the row's existence -- account-takeover
relevant fields (previous_auth_methods, email_verified_source,
auto_linked), and explicitly that no google_id/sso_subject VALUE ever
appears in a payload, only the fact that one was set.
"""
import uuid

import pytest
from sqlalchemy import select

from models.all_models import AuditLog, User
from services.auth_service import create_new_tenant_and_user, hash_password
from services.tenant_context import tenant_session

# Reused, not redefined -- pytest resolves a fixture by name from whatever
# is imported into this module's namespace, so importing the function
# itself (not just calling it) makes it usable here exactly as in its own
# file, with no duplicated mock logic to drift out of sync.
from tests.test_team_invites import captured_invite
from tests.test_email_code_auth import captured_code

pytestmark = pytest.mark.asyncio


async def _audit_rows(tenant_id: str, action: str) -> list[AuditLog]:
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(AuditLog).where(
            AuditLog.tenant_id == tenant_id, AuditLog.action == action,
        ))
        return r.scalars().all()


def unique_email(prefix="identityaudit"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


# ── 1. user.registered ────────────────────────────────────────────────────

async def test_password_registration_writes_an_audit_row(client):
    email = unique_email("register")
    reg = (await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234", "full_name": "New Owner",
        "tenant_name": f"Audit Register Corp {uuid.uuid4().hex[:6]}",
    })).json()
    rows = await _audit_rows(reg["tenant_id"], "user.registered")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == email
    assert row.resource_type == "user" and row.resource_id == reg["user_id"]
    assert row.payload["auth_method"] == "password"


# ── 2. sso.user_provisioned ────────────────────────────────────────────────

async def test_sso_jit_provisioning_writes_an_audit_row(client, monkeypatch):
    from config import settings
    import services.sso_service as sso_service

    # A real, per-tenant-unique subdomain, not plain "example.com" -- SSO
    # domain claims are globally unique, and unique_email()'s uniqueness is
    # in the local part only. Matches test_sso.py's own _owner() pattern.
    domain = f"{uuid.uuid4().hex[:8]}.example"
    owner_email = f"owner@{domain}"
    reg = (await client.post("/api/v1/auth/register", json={
        "email": owner_email, "password": "test1234", "full_name": "Owner",
        "tenant_name": f"Audit SSO Corp {uuid.uuid4().hex[:6]}",
    })).json()
    tenant_id, owner_token = reg["tenant_id"], reg["access_token"]
    conn_id = "conn_01AUDITCOVERAGEXXXXXXXXXX"
    cfg = await client.put("/api/v1/auth/sso/config", headers={"Authorization": f"Bearer {owner_token}"}, json={
        "connection_id": conn_id, "email_domain": domain, "enabled": True, "satisfies_mfa": False,
    })
    assert cfg.status_code == 200, cfg.text

    monkeypatch.setattr(settings, "WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "WORKOS_CLIENT_ID", "client_fake")
    new_email = f"newhire@{domain}"
    st = await client.post("/api/v1/auth/sso/start", json={"email": new_email})
    assert st.status_code == 200, st.text

    async def fake_fetch_profile(code):
        return {"id": "prof_audit_test", "email": new_email, "connection_id": conn_id,
                "organization_id": "org_x", "first_name": "New", "last_name": "Hire", "idp_id": "idp-1"}
    monkeypatch.setattr(sso_service, "fetch_profile", fake_fetch_profile)

    cb = await client.post("/api/v1/auth/sso/callback", json={"code": "good-code", "state": st.json()["state"]})
    assert cb.status_code == 200, cb.text

    async with tenant_session(tenant_id) as db:
        u = (await db.execute(select(User).where(User.email == new_email))).scalar_one()

    rows = await _audit_rows(tenant_id, "sso.user_provisioned")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == new_email
    assert row.resource_type == "user" and row.resource_id == u.id
    assert row.payload["provider"] == "workos"
    assert row.payload["connection_id"] == conn_id
    assert row.payload["email_domain"] == domain


# ── 3. user.invite_accepted ────────────────────────────────────────────────

async def test_invite_acceptance_writes_an_audit_row(client, captured_invite):
    owner_email = unique_email("inviteowner")
    reg = (await client.post("/api/v1/auth/register", json={
        "email": owner_email, "password": "test1234", "full_name": "Owner",
        "tenant_name": f"Audit Invite Corp {uuid.uuid4().hex[:6]}",
    })).json()
    tenant_id, owner_token, owner_id = reg["tenant_id"], reg["access_token"], reg["user_id"]
    invitee_email = unique_email("invitee")

    r = await client.post("/api/v1/team/invites", json={"email": invitee_email, "role": "data_analyst"},
                          headers={"Authorization": f"Bearer {owner_token}"})
    assert r.status_code == 200, r.text
    token = captured_invite["token"]

    accept = await client.post("/api/v1/team/invites/accept", json={
        "token": token, "password": "newpass123", "full_name": "New Analyst",
    })
    assert accept.status_code == 200, accept.text
    new_user_id = accept.json()["user_id"]

    rows = await _audit_rows(tenant_id, "user.invite_accepted")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == invitee_email
    assert row.resource_type == "user" and row.resource_id == new_user_id
    assert row.payload["role"] == "data_analyst"
    assert row.payload["invited_by_user_id"] == owner_id


# ── 4. user.linked_google ─────────────────────────────────────────────────

async def test_google_auto_link_writes_an_audit_row_with_no_token_material(client, monkeypatch):
    import api.v1.auth as auth_router

    email = unique_email("googlelink")
    tenant, user = await create_new_tenant_and_user(
        tenant_name="Audit Google Link Corp", email=email, auth_method="password",
        hashed_password=hash_password("somepass"),
    )
    assert user.google_id is None

    async def fake_exchange(code):
        return {"id_token": "fake-id-token", "access_token": "fake-access-token"}

    async def fake_verify(id_token_str):
        return {"sub": "google-sub-audit-test", "email": email, "email_verified": True, "name": "G User"}

    monkeypatch.setattr(auth_router, "exchange_google_code", fake_exchange)
    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)

    url_resp = await client.get("/api/v1/auth/google/login-url")
    state = url_resp.json()["state"]
    r = await client.post("/api/v1/auth/google/callback", json={
        "code": "fake", "state": state, "intended_tenant_id": tenant.id,
    })
    assert r.status_code == 200, r.text

    rows = await _audit_rows(tenant.id, "user.linked_google")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == email
    assert row.resource_type == "user" and row.resource_id == user.id
    assert row.payload["provider"] == "google"
    assert row.payload["previous_auth_methods"] == ["password"]
    assert row.payload["email_verified_source"] == "google"
    assert row.payload["auto_linked"] is True
    payload_str = str(row.payload)
    assert "google-sub-audit-test" not in payload_str


# ── 5. user.linked_email_code ─────────────────────────────────────────────

async def test_email_code_auto_link_writes_an_audit_row(client, captured_code):
    email = unique_email("emailcodelink")
    tenant, user = await create_new_tenant_and_user(
        tenant_name="Audit Email Code Link Corp", email=email, auth_method="password",
        hashed_password=hash_password("somepass"),
    )
    assert user.email_verified is False

    await client.post("/api/v1/auth/email-code/request", json={"email": email, "intended_tenant_id": tenant.id})
    code = captured_code["code"]
    verify = await client.post("/api/v1/auth/email-code/verify", json={"email": email, "code": code})
    assert verify.status_code == 200, verify.text

    rows = await _audit_rows(tenant.id, "user.linked_email_code")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == email
    assert row.resource_type == "user" and row.resource_id == user.id
    assert row.payload["provider"] == "email_code"
    assert row.payload["previous_auth_methods"] == ["password"]
    assert row.payload["email_verified_source"] == "email code"
    assert row.payload["auto_linked"] is True


# ── 6. user.linked_sso ─────────────────────────────────────────────────────

async def test_sso_link_to_existing_password_account_writes_an_audit_row_with_no_identity_values(client, monkeypatch):
    """Explicitly the account-takeover-relevant case: an EXISTING password
    account gets an SSO identity linked onto it. Asserts the payload's
    fields (not just the row's existence) and that no sso_subject/google_id
    VALUE appears anywhere in the payload -- only that one was set."""
    from config import settings
    import services.sso_service as sso_service

    domain = f"{uuid.uuid4().hex[:8]}.example"
    owner_email = f"owner@{domain}"
    reg = (await client.post("/api/v1/auth/register", json={
        "email": owner_email, "password": "test1234", "full_name": "Owner",
        "tenant_name": f"Audit SSO Link Corp {uuid.uuid4().hex[:6]}",
    })).json()
    tenant_id, owner_token, owner_id = reg["tenant_id"], reg["access_token"], reg["user_id"]
    conn_id = "conn_01AUDITLINKCOVERAGEXXXXXX"
    cfg = await client.put("/api/v1/auth/sso/config", headers={"Authorization": f"Bearer {owner_token}"}, json={
        "connection_id": conn_id, "email_domain": domain, "enabled": True, "satisfies_mfa": False,
    })
    assert cfg.status_code == 200, cfg.text

    monkeypatch.setattr(settings, "WORKOS_API_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "WORKOS_CLIENT_ID", "client_fake")
    st = await client.post("/api/v1/auth/sso/start", json={"email": owner_email})
    assert st.status_code == 200, st.text

    sso_subject_value = f"prof_{uuid.uuid4().hex[:10]}"

    async def fake_fetch_profile(code):
        return {"id": sso_subject_value, "email": owner_email, "connection_id": conn_id,
                "organization_id": "org_x", "first_name": "Ada", "last_name": "Lovelace", "idp_id": "idp-1"}
    monkeypatch.setattr(sso_service, "fetch_profile", fake_fetch_profile)

    cb = await client.post("/api/v1/auth/sso/callback", json={"code": "good-code", "state": st.json()["state"]})
    assert cb.status_code == 200, cb.text

    rows = await _audit_rows(tenant_id, "user.linked_sso")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == owner_email
    assert row.resource_type == "user" and row.resource_id == owner_id
    assert row.payload["provider"] == "workos"
    assert row.payload["connection_id"] == conn_id
    assert row.payload["previous_auth_methods"] == ["password"]
    assert row.payload["email_verified_source"] == "tenant verified domain"
    assert row.payload["auto_linked"] is True

    payload_str = str(row.payload)
    assert sso_subject_value not in payload_str
    assert "google-sub" not in payload_str
