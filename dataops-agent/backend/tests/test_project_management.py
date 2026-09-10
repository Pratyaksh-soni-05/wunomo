"""Wunomo Projects Phase 4, item 3: project lifecycle management --
rename and delete, plus the new GET /{project_id}/channels read side that
feeds the frontend's delete-confirmation dialog.

Delete is the one with real stakes: neither ProjectAgent nor
Channel.project_id has an ON DELETE clause, so api/v1/projects.py's
delete_project() must explicitly clear both before removing the Project
row. The two outcomes this file exists to prove, verbatim from the
product requirement: agents survive as unassigned and still appear on
GET /api/v1/agents/, and a channel whose project was deleted still opens
and still works (can still receive and route a real message).
"""
import uuid

import pytest
from sqlalchemy import select

import api.v1.chat as chat_module
from database import AsyncSessionLocal
from models.all_models import ProjectAgent, User
from services.auth_service import hash_password, issue_token_for_user
from tests.test_channels import _fake_run_agent


async def _register(client, prefix="projmgmt"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Project Management Test",
        "tenant_name": f"Project Management Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _viewer(tenant_id, prefix="viewer"):
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("test1234"), full_name=prefix, role="viewer",
            is_active=True, email_verified=True,
        )
        db.add(user)
        await db.commit()
        return issue_token_for_user(user, "password")


async def _create_project(client, token, name="Q3 Revenue Migration"):
    r = await client.post("/api/v1/projects/", json={"name": name}, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _hire_agent(client, token, name, project_id=None):
    body = {"name": name}
    if project_id is not None:
        body["project_id"] = project_id
    r = await client.post("/api/v1/agents/", headers=_auth(token), json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _create_channel(client, token, name, project_id=None):
    body = {"name": name}
    if project_id is not None:
        body["project_id"] = project_id
    r = await client.post("/api/v1/channels/", headers=_auth(token), json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rename_project_succeeds(client):
    token, _, _ = await _register(client, "renameA")
    project_id = await _create_project(client, token, "Old Name")

    r = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "New Name"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "New Name"

    r = await client.get("/api/v1/projects/", headers=_auth(token))
    assert {p["name"] for p in r.json()["projects"]} == {"New Name"}


@pytest.mark.asyncio
async def test_rename_project_rejects_empty_name(client):
    token, _, _ = await _register(client, "renameB")
    project_id = await _create_project(client, token)

    r = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "   "}, headers=_auth(token))
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_rename_project_rejects_duplicate_name(client):
    token, _, _ = await _register(client, "renameC")
    await _create_project(client, token, "Taken")
    other_id = await _create_project(client, token, "Free")

    r = await client.patch(f"/api/v1/projects/{other_id}", json={"name": "Taken"}, headers=_auth(token))
    assert r.status_code == 409, r.text
    assert "already exists" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rename_project_allows_keeping_its_own_current_name(client):
    """Renaming a project to the name it already has must not 409 against
    itself -- _name_collision's exclude_project_id exists for exactly this."""
    token, _, _ = await _register(client, "renameD")
    project_id = await _create_project(client, token, "Same Name")

    r = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "Same Name"}, headers=_auth(token))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_rename_project_404_for_nonexistent(client):
    token, _, _ = await _register(client, "renameE")
    r = await client.patch(f"/api/v1/projects/{uuid.uuid4()}", json={"name": "X"}, headers=_auth(token))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_rename_project_never_leaks_across_tenants(client):
    token_a, _, _ = await _register(client, "renameF1")
    project_id = await _create_project(client, token_a)

    token_b, _, _ = await _register(client, "renameF2")
    r = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "Hijacked"}, headers=_auth(token_b))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_rename_project_requires_agents_manage_permission(client):
    token, tenant_id, _ = await _register(client, "renameG")
    project_id = await _create_project(client, token)
    viewer_token = await _viewer(tenant_id, "renameviewer")

    r = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "Nope"}, headers=_auth(viewer_token))
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# GET /{project_id}/channels -- feeds the delete-confirmation dialog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_project_channels_returns_real_channels(client):
    token, _, _ = await _register(client, "chanlistA")
    project_id = await _create_project(client, token)
    channel_id = await _create_channel(client, token, "marketing-ops", project_id=project_id)
    await _create_channel(client, token, "unrelated")  # not in the project

    r = await client.get(f"/api/v1/projects/{project_id}/channels", headers=_auth(token))
    assert r.status_code == 200, r.text
    channels = r.json()["channels"]
    assert {c["id"] for c in channels} == {channel_id}
    assert channels[0]["name"] == "marketing-ops"


@pytest.mark.asyncio
async def test_list_project_channels_404_for_nonexistent(client):
    token, _, _ = await _register(client, "chanlistB")
    r = await client.get(f"/api/v1/projects/{uuid.uuid4()}/channels", headers=_auth(token))
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Delete -- the core requirement: agents survive unassigned, channels
# survive ungrouped and still functional.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_project_agents_survive_as_unassigned(client):
    token, tenant_id, _ = await _register(client, "delA")
    project_id = await _create_project(client, token, "Doomed Project")
    nova_id = await _hire_agent(client, token, "Nova", project_id=project_id)
    atlas_id = await _hire_agent(client, token, "Atlas", project_id=project_id)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ProjectAgent).where(ProjectAgent.project_id == project_id))
        assert len(r.scalars().all()) == 2, "sanity check: both agents actually joined the project"

    r = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"id": project_id, "deleted": True}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ProjectAgent).where(ProjectAgent.project_id == project_id))
        assert r.scalars().all() == [], "ProjectAgent rows must be cleared, not orphaned pointing at a dead project"

    r = await client.get("/api/v1/agents/", headers=_auth(token))
    assert r.status_code == 200, r.text
    agent_ids = {a["id"] for a in r.json()["agents"]}
    assert {nova_id, atlas_id} <= agent_ids, "agents must survive and still appear on /agents"
    for agent in r.json()["agents"]:
        if agent["id"] in (nova_id, atlas_id):
            assert agent["status"] == "active", "deleting the project must not touch agent status"

    r = await client.get(f"/api/v1/projects/{project_id}/agents", headers=_auth(token))
    assert r.status_code == 404, "the project itself is gone"


@pytest.mark.asyncio
async def test_delete_project_channel_survives_and_still_works(client, monkeypatch):
    token, tenant_id, user_id = await _register(client, "delB")
    project_id = await _create_project(client, token, "Doomed Project")
    channel_id = await _create_channel(client, token, "marketing-ops", project_id=project_id)
    nova_id = await _hire_agent(client, token, "Nova")
    await client.post(f"/api/v1/channels/{channel_id}/members/agents/{nova_id}", headers=_auth(token))

    r = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(token))
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/channels/{channel_id}", headers=_auth(token))
    assert r.status_code == 200, "a channel whose project was deleted must still open"
    body = r.json()
    assert body["project_id"] is None, "the FK must be nulled, not left dangling at a dead project id"
    assert body["name"] == "marketing-ops"
    assert {a["id"] for a in body["agents"]} == {nova_id}, "membership must survive the ungrouping untouched"

    captured = {}
    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent(captured, "still here."))
    r = await client.post("/api/v1/chat/", headers=_auth(token), json={
        "message": "are you still working?", "session_id": channel_id,
    })
    assert r.status_code == 200, r.text
    assert captured["agent_id"] == nova_id, "the channel must still route messages after its project is gone"
    assert r.json()["response"] == "still here."


@pytest.mark.asyncio
async def test_delete_project_404_for_nonexistent(client):
    token, _, _ = await _register(client, "delC")
    r = await client.delete(f"/api/v1/projects/{uuid.uuid4()}", headers=_auth(token))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_delete_project_never_leaks_across_tenants(client):
    token_a, _, _ = await _register(client, "delD1")
    project_id = await _create_project(client, token_a)

    token_b, _, _ = await _register(client, "delD2")
    r = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(token_b))
    assert r.status_code == 404, r.text

    r = await client.get("/api/v1/projects/", headers=_auth(token_a))
    assert len(r.json()["projects"]) == 1, "the other tenant's failed delete must not have touched this project"


@pytest.mark.asyncio
async def test_delete_project_requires_agents_manage_permission(client):
    token, tenant_id, _ = await _register(client, "delE")
    project_id = await _create_project(client, token)
    viewer_token = await _viewer(tenant_id, "delviewer")

    r = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(viewer_token))
    assert r.status_code == 403, r.text

    r = await client.get("/api/v1/projects/", headers=_auth(token))
    assert len(r.json()["projects"]) == 1, "the denied delete must not have gone through"
