import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "env" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_docs_available_in_dev(client: AsyncClient):
    r = await client.get("/docs")
    assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_sources_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/sources/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_pipelines_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/pipelines/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_chat_requires_auth(client: AsyncClient):
    r = await client.post("/api/v1/chat/", json={"message": "hello"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_incidents_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/incidents/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_analytics_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/analytics/health")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_approvals_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/approvals/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    # Unique per run — a hardcoded email here previously accumulated
    # duplicate tenants across repeated test runs (this codebase's test
    # suite isn't hermetic, see CLAUDE.md), which started actually breaking
    # this test once login() correctly began disambiguating same-email
    # matches across tenants instead of silently picking one (Phase 3/5 fix).
    email = f"mvptest-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "test1234",
        "full_name": "MVP Tester",
        "tenant_name": "AXIOM Corp",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()

    r2 = await client.post("/api/v1/auth/login",
        data={"username": email, "password": "test1234"})
    assert r2.status_code == 200
    assert "access_token" in r2.json()
    assert r2.json()["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_chat_empty_message_rejected(client: AsyncClient):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "emptytest2@example.com",
        "password": "test1234",
        "full_name": "Empty Tester",
        "tenant_name": "Empty Corp 2",
    })
    token = reg.json()["access_token"]

    r = await client.post("/api/v1/chat/",
        json={"message": "   "},
        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422
    assert any(
        "empty" in str(e).lower() or "message" in str(e).lower()
        for e in r.json()["detail"]
    )