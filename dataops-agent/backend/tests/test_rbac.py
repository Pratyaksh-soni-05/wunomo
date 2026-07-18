import uuid
import pytest
from datetime import datetime, timezone, timedelta

from database import AsyncSessionLocal
from models.all_models import User
from models.cicd import PipelineCommit
from sqlalchemy import select


async def _register(client, prefix="rbac"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "RBAC Test",
        "tenant_name": f"RBAC Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _set_role(user_id: str, role: str) -> str:
    """Directly downgrades a user's role via DB (no role-change endpoint
    exists yet at this point in the phase) and returns a fresh JWT carrying
    the new role claim."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = role
        await db.commit()

    from services.auth_service import issue_token_for_user
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        return issue_token_for_user(user, "password")


async def _make_pending_commit(tenant_id, commit_sha="abc123def456"):
    async with AsyncSessionLocal() as db:
        commit = PipelineCommit(
            id=str(uuid.uuid4()), tenant_id=tenant_id, commit_sha=commit_sha,
            branch="main", author="tester", commit_message="risky change",
            gate_decision="pending_approval", risk_score=0.8,
            trigger_time=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(commit)
        await db.commit()
        return commit.id


@pytest.mark.asyncio
async def test_owner_can_approve_cicd_deployment(client):
    token, tenant_id, user_id = await _register(client)
    commit_id = await _make_pending_commit(tenant_id)

    r = await client.post(
        f"/api/v1/cicd/commits/{commit_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_approve_cicd_deployment(client):
    _, tenant_id, user_id = await _register(client)
    viewer_token = await _set_role(user_id, "viewer")
    commit_id = await _make_pending_commit(tenant_id)

    r = await client.post(
        f"/api/v1/cicd/commits/{commit_id}/approve",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403

    async with AsyncSessionLocal() as db:
        rr = await db.execute(select(PipelineCommit).where(PipelineCommit.id == commit_id))
        commit = rr.scalar_one()
        assert commit.gate_decision == "pending_approval"


@pytest.mark.asyncio
async def test_data_engineer_cannot_reject_cicd_deployment(client):
    _, tenant_id, user_id = await _register(client)
    de_token = await _set_role(user_id, "data_engineer")
    commit_id = await _make_pending_commit(tenant_id)

    r = await client.post(
        f"/api/v1/cicd/commits/{commit_id}/reject",
        headers={"Authorization": f"Bearer {de_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_delete_pipeline_but_data_engineer_can(client):
    owner_token, tenant_id, user_id = await _register(client)
    headers = {"Authorization": f"Bearer {owner_token}"}
    pipe = await client.post("/api/v1/pipelines/", json={"name": "RBAC Test Pipeline"}, headers=headers)
    pipeline_id = pipe.json()["id"]

    viewer_token = await _set_role(user_id, "viewer")
    r = await client.delete(
        f"/api/v1/pipelines/{pipeline_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403

    de_token = await _set_role(user_id, "data_engineer")
    r = await client.delete(
        f"/api/v1/pipelines/{pipeline_id}",
        headers={"Authorization": f"Bearer {de_token}"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_delete_source(client):
    _, tenant_id, user_id = await _register(client)
    viewer_token = await _set_role(user_id, "viewer")

    r = await client.delete(
        "/api/v1/sources/nonexistent-id",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_delete_quality_rule(client):
    _, tenant_id, user_id = await _register(client)
    viewer_token = await _set_role(user_id, "viewer")

    r = await client.delete(
        "/api/v1/quality/nonexistent-id",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_run_sql_but_data_analyst_reaches_the_real_endpoint(client):
    _, tenant_id, user_id = await _register(client)
    viewer_token = await _set_role(user_id, "viewer")

    r = await client.post(
        "/api/v1/transformations/run/sql",
        json={"source_id": "nonexistent-id", "sql": "SELECT 1"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403

    analyst_token = await _set_role(user_id, "data_analyst")
    r = await client.post(
        "/api/v1/transformations/run/sql",
        json={"source_id": "nonexistent-id", "sql": "SELECT 1"},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r.status_code != 403  # past the gate; real endpoint now rejects the fake source_id itself


@pytest.mark.asyncio
async def test_viewer_cannot_run_pandas(client):
    _, tenant_id, user_id = await _register(client)
    viewer_token = await _set_role(user_id, "viewer")

    r = await client.post(
        "/api/v1/transformations/run/pandas",
        json={"source_id": "nonexistent-id", "code": "result = df"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_resolve_cicd_incident_but_admin_reaches_the_real_endpoint(client):
    _, tenant_id, user_id = await _register(client)
    viewer_token = await _set_role(user_id, "viewer")

    r = await client.patch(
        "/api/v1/cicd/incidents/nonexistent-id/resolve",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403

    admin_token = await _set_role(user_id, "admin")
    r = await client.patch(
        "/api/v1/cicd/incidents/nonexistent-id/resolve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code != 403  # past the gate; real endpoint now 404s on the fake id itself
