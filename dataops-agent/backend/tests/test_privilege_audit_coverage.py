"""Audit coverage for the five privilege-event sites found in the same
sweep as the identity-creation/linking gap (PR #5, 2026-09-30): role
change, member removal, POST /auth/revoke (both scopes), and API key
create/revoke all had no audit row at all. See docs/context/GOTCHAS.md's
sweep entry for the full finding once PR #5 lands.

One test per distinct action name (six, since /auth/revoke's two scopes
are two separate actions), each confirmed failing on pre-fix code (0
matching audit_logs rows) and passing after. The API key create test
takes the REAL raw key the endpoint returns and asserts that exact
string is absent from the stored payload -- not a placeholder check.
"""
import uuid

import pytest
from sqlalchemy import select

from models.all_models import AuditLog, User
from services.auth_service import hash_password, issue_token_for_user
from services.tenant_context import tenant_session

pytestmark = pytest.mark.asyncio


async def _audit_rows(tenant_id: str, action: str) -> list[AuditLog]:
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(AuditLog).where(
            AuditLog.tenant_id == tenant_id, AuditLog.action == action,
        ))
        return r.scalars().all()


async def _register(client, prefix="privaudit"):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    reg = (await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Owner", "tenant_name": f"Priv Audit Corp {uuid.uuid4().hex[:6]}",
    })).json()
    return reg["access_token"], reg["tenant_id"], reg["user_id"], email


async def _add_member(tenant_id: str, role: str) -> tuple[str, str]:
    """A second real member, inserted directly (invite flow already covered
    by test_team_invites.py) -- matches test_team_members.py's own helper."""
    email = f"member-{uuid.uuid4().hex[:8]}@example.com"
    async with tenant_session(tenant_id) as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=email,
            hashed_password=hash_password("memberpass123"),
            full_name="Second Member", role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email


# ── 1. team.role_changed ───────────────────────────────────────────────────

async def test_role_change_writes_an_audit_row_with_old_and_new_role(client):
    owner_token, tenant_id, owner_id, _ = await _register(client, "rolechange")
    member_id, _ = await _add_member(tenant_id, "data_analyst")

    r = await client.patch(
        f"/api/v1/team/members/{member_id}/role", json={"role": "data_engineer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(tenant_id, "team.role_changed")
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "user" and row.resource_id == member_id
    assert row.payload["old_role"] == "data_analyst"
    assert row.payload["new_role"] == "data_engineer"


# ── 2. team.member_removed ────────────────────────────────────────────────

async def test_member_removal_writes_an_audit_row_with_removed_role(client):
    owner_token, tenant_id, owner_id, _ = await _register(client, "memberremove")
    member_id, _ = await _add_member(tenant_id, "viewer")

    r = await client.delete(
        f"/api/v1/team/members/{member_id}", headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(tenant_id, "team.member_removed")
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "user" and row.resource_id == member_id
    assert row.payload["removed_role"] == "viewer"


# ── 3. auth.session_revoked ───────────────────────────────────────────────

async def test_revoke_current_session_writes_an_audit_row(client):
    owner_token, tenant_id, owner_id, _ = await _register(client, "revokecurrent")

    r = await client.post(
        "/api/v1/auth/revoke", json={"scope": "current"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(tenant_id, "auth.session_revoked")
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "user" and row.resource_id == owner_id
    assert row.payload["scope"] == "current"


# ── 4. auth.all_sessions_revoked ──────────────────────────────────────────

async def test_revoke_all_sessions_writes_an_audit_row(client):
    owner_token, tenant_id, owner_id, _ = await _register(client, "revokeall")

    r = await client.post(
        "/api/v1/auth/revoke", json={"scope": "all"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(tenant_id, "auth.all_sessions_revoked")
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "user" and row.resource_id == owner_id
    assert row.payload["scope"] == "all"


# ── 5. api_key.created ────────────────────────────────────────────────────

async def test_api_key_create_writes_an_audit_row_with_no_key_material(client):
    owner_token, tenant_id, owner_id, _ = await _register(client, "apikeycreate")

    r = await client.post(
        "/api/v1/api-keys/", json={"name": "CI pipeline key"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    raw_key = r.json()["raw_key"]
    key_id = r.json()["id"]
    key_prefix = r.json()["key_prefix"]

    rows = await _audit_rows(tenant_id, "api_key.created")
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "api_key" and row.resource_id == key_id
    assert row.payload == {"name": "CI pipeline key"}

    payload_str = str(row.payload)
    assert raw_key not in payload_str
    assert key_prefix not in payload_str


# ── 6. api_key.revoked ────────────────────────────────────────────────────

async def test_api_key_revoke_writes_an_audit_row(client):
    owner_token, tenant_id, owner_id, _ = await _register(client, "apikeyrevoke")

    created = await client.post(
        "/api/v1/api-keys/", json={"name": "to be revoked"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    key_id = created.json()["id"]

    r = await client.delete(
        f"/api/v1/api-keys/{key_id}", headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text

    rows = await _audit_rows(tenant_id, "api_key.revoked")
    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "api_key" and row.resource_id == key_id
