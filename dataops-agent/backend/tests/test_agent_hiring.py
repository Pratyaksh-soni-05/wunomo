"""Wunomo Projects Phase 1, part two: projects and hiring.

Covers: projects table + project_agents join (api/v1/projects.py), and
hiring an agent (api/v1/agents.py's hire_agent) with employee_type locked
to DATAOPS and source assignment at hire time reusing the grant
endpoint's own logic (_grant_source_within_session). The per-agent
monthly_token_budget two-gate enforcement itself is covered separately in
test_agent_token_budget.py.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import DataSource, SourceType


async def _register(client, prefix="hiring"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Hiring Test",
        "tenant_name": f"Hiring Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _make_source(tenant_id: str, name="Source") -> str:
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            source_type=SourceType.POSTGRES, connection_config={},
        )
        db.add(source)
        await db.commit()
        return source.id


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_list_projects(client):
    token, tenant_id, _ = await _register(client, "projA")
    r = await client.post("/api/v1/projects/", json={"name": "Q3 Revenue Migration"}, headers=_auth(token))
    assert r.status_code == 200
    project_id = r.json()["id"]

    r = await client.get("/api/v1/projects/", headers=_auth(token))
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["projects"]}
    assert names == {"Q3 Revenue Migration"}

    r = await client.get(f"/api/v1/projects/{project_id}/agents", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["agents"] == []


@pytest.mark.asyncio
async def test_duplicate_project_name_rejected(client):
    token, tenant_id, _ = await _register(client, "projB")
    await client.post("/api/v1/projects/", json={"name": "Dup"}, headers=_auth(token))
    r = await client.post("/api/v1/projects/", json={"name": "Dup"}, headers=_auth(token))
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_viewer_cannot_create_a_project(client):
    from services.auth_service import issue_token_for_user
    from models.all_models import User

    token, tenant_id, user_id = await _register(client, "projC")
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        viewer_token = issue_token_for_user(r.scalar_one(), "password")

    r = await client.post("/api/v1/projects/", json={"name": "Nope"}, headers=_auth(viewer_token))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Hiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hire_agent_with_project_sources_and_budget(client):
    token, tenant_id, _ = await _register(client, "hireA")
    r = await client.post("/api/v1/projects/", json={"name": "Warehouse Migration"}, headers=_auth(token))
    project_id = r.json()["id"]
    source_a = await _make_source(tenant_id, "Warehouse")
    source_b = await _make_source(tenant_id, "CRM")

    r = await client.post("/api/v1/agents/", headers=_auth(token), json={
        "name": "Nova", "project_id": project_id, "source_ids": [source_a, source_b],
        "monthly_token_budget": 40000,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Nova"
    assert body["employee_type"] == "dataops"
    assert body["monthly_token_budget"] == 40000
    assert {s["id"] for s in body["sources"]} == {source_a, source_b}

    # Source assignment at hire time really used the grant path -- the
    # agent's real scope now includes both sources, queryable the same
    # way a post-hoc grant would leave it.
    r = await client.get(f"/api/v1/agents/{body['id']}/sources", headers=_auth(token))
    assert {s["id"] for s in r.json()["sources"]} == {source_a, source_b}

    # And it's really linked to the project.
    r = await client.get(f"/api/v1/projects/{project_id}/agents", headers=_auth(token))
    assert {a["id"] for a in r.json()["agents"]} == {body["id"]}


@pytest.mark.asyncio
async def test_hire_agent_without_project_or_sources(client):
    token, tenant_id, _ = await _register(client, "hireB")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "Solo"})
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] is None
    assert body["sources"] == []
    assert body["monthly_token_budget"] is None


@pytest.mark.asyncio
async def test_hire_rejects_a_locked_employee_type(client):
    """The proposal's own rule -- "never imply a Coming Soon employee is
    available" -- held at the API boundary, not just the frontend hire
    screen. LEDGER/PULSE/etc. have no real AgentEmployeeType member yet."""
    token, tenant_id, _ = await _register(client, "hireC")
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={
        "name": "Ledger Bot", "employee_type": "ledger",
    })
    assert r.status_code == 422
    assert "isn't available yet" in r.json()["detail"]


@pytest.mark.asyncio
async def test_hire_rejects_duplicate_name(client):
    token, tenant_id, _ = await _register(client, "hireD")
    await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "AXIOM"})
    r = await client.post("/api/v1/agents/", headers=_auth(token), json={"name": "AXIOM"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_hire_rejects_a_cross_tenant_project_and_source(client):
    token_a, tenant_a, _ = await _register(client, "hireE1")
    _, tenant_b, _ = await _register(client, "hireE2")

    r = await client.post("/api/v1/projects/", headers=_auth(token_a), json={"name": "P"})
    project_a = r.json()["id"]
    source_b = await _make_source(tenant_b, "Other tenant's source")

    r = await client.post("/api/v1/agents/", headers=_auth(token_a), json={
        "name": "CrossCheck", "source_ids": [source_b],
    })
    assert r.status_code == 404

    r = await client.post("/api/v1/agents/", headers=_auth(token_a), json={
        "name": "CrossCheck2", "project_id": "not-real-and-not-tenant-a-anyway",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_hire(client):
    from services.auth_service import issue_token_for_user
    from models.all_models import User

    token, tenant_id, user_id = await _register(client, "hireF")
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        viewer_token = issue_token_for_user(r.scalar_one(), "password")

    r = await client.post("/api/v1/agents/", headers=_auth(viewer_token), json={"name": "Nope"})
    assert r.status_code == 403
