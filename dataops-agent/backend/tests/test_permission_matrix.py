"""Phase 19: role x capability matrix test.

5 roles x every REST-enforced capability in services/rbac.py's PERMISSIONS
map, each checked against one representative real endpoint, asserting
allow/deny matches the map exactly. This is the regression guard for the
REST half of the unified permission spec — see test_agent_role_gate.py for
the agent (AXIOM tool-calling) half, and
test_viewer_blocked_from_pipeline_trigger_both_consumers in that same file
for the cross-consumer proof that REST and chat actually share this one map
rather than two copies that happen to agree today.

Capabilities with no REST call site (transforms.generate — deliberately
ungated for every role, safe/sandboxed actions) are not represented here.
"""
import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User
from services.auth_service import issue_token_for_user
from services.rbac import PERMISSIONS, Role
from sqlalchemy import select


async def _register(client, prefix="matrix"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Matrix Test",
        "tenant_name": f"Matrix Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _token_for_role(user_id: str, role: str) -> str:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = role
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        return issue_token_for_user(user, "password")


# (capability, http method, path, json body-or-None) — one representative
# real endpoint per REST-enforced capability. Bodies are schema-valid for
# their endpoint's Pydantic model so an "allowed" role's request reaches
# real domain logic (which may still legitimately reject a fake resource id
# with a 400/404/402/422 — this test only asserts on 403 vs not-403, never
# on the domain-level outcome).
REPRESENTATIVE_ENDPOINTS = [
    ("sources.create", "post", "/api/v1/sources/",
     {"name": "t", "source_type": "csv", "connection_config": {"file_path": "x.csv"}}),
    ("sources.profile", "post", "/api/v1/sources/nonexistent-id/profile", None),
    ("sources.delete", "delete", "/api/v1/sources/nonexistent-id", None),
    ("pipelines.create", "post", "/api/v1/pipelines/", {"name": "t"}),
    ("pipelines.operate", "post", "/api/v1/pipelines/nonexistent-id/trigger", None),
    ("pipelines.delete", "delete", "/api/v1/pipelines/nonexistent-id", None),
    ("quality.manage", "post", "/api/v1/quality/nonexistent-id/run", None),
    ("quality.delete", "delete", "/api/v1/quality/nonexistent-id", None),
    ("transforms.execute", "post", "/api/v1/transformations/run/sql",
     {"source_id": "nonexistent-id", "sql": "SELECT 1"}),
    ("incidents.log", "post", "/api/v1/incidents/", {"title": "t"}),
    ("incidents.resolve", "post", "/api/v1/incidents/nonexistent-id/resolve",
     {"resolution_notes": "n"}),
    ("contracts.create", "post", "/api/v1/governance/contracts",
     {"name": "t", "producer_source_id": "nonexistent-id"}),
    ("contracts.validate", "post", "/api/v1/governance/contracts/nonexistent-id/validate", None),
    ("approvals.manage", "post", "/api/v1/approvals/nonexistent-id/approve", {}),
    ("cicd.approve", "post", "/api/v1/cicd/commits/nonexistent-id/approve", None),
    ("cicd.incidents.resolve", "patch", "/api/v1/cicd/incidents/nonexistent-id/resolve", None),
    ("team.manage", "get", "/api/v1/team/invites", None),
    ("settings.manage", "patch", "/api/v1/settings/", {"name": "New Name"}),
    ("api_keys.manage", "get", "/api/v1/api-keys/", None),
    ("billing.manage", "post", "/api/v1/billing/change-plan", {"plan": "growth"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("capability,method,path,body", REPRESENTATIVE_ENDPOINTS)
async def test_permission_matrix(client, capability, method, path, body):
    _, tenant_id, user_id = await _register(client)
    allowed_roles = PERMISSIONS[capability]

    for role in Role:
        token = await _token_for_role(user_id, role.value)
        headers = {"Authorization": f"Bearer {token}"}
        req = getattr(client, method)
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        r = await req(path, **kwargs)

        if role in allowed_roles:
            assert r.status_code != 403, (
                f"{role.value} should be ALLOWED for {capability} "
                f"({method.upper()} {path}) but got 403: {r.text}"
            )
        else:
            assert r.status_code == 403, (
                f"{role.value} should be DENIED for {capability} "
                f"({method.upper()} {path}) but got {r.status_code}: {r.text}"
            )


def test_every_capability_has_a_matrix_row_or_is_explicitly_exempt():
    """Guards against the matrix silently going stale if a new capability is
    added to PERMISSIONS without a corresponding representative endpoint
    (or a deliberate exemption) here."""
    exempt = {"view", "transforms.generate"}  # no REST call site by design
    covered = {cap for cap, _, _, _ in REPRESENTATIVE_ENDPOINTS}
    missing = set(PERMISSIONS) - covered - exempt
    assert not missing, f"Capabilities with no matrix row and no exemption: {missing}"
