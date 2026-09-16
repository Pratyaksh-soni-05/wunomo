"""POST /sources/ must say no with a 4xx, not with a 200 that says "error".

Found 2026-09-17 by a tester following the security self-test guide: a
Postgres source whose host/database matched the app's own DSN was
correctly refused by ConnectorManager._points_at_app_database() -- but
register_source() reports refusal as {"error": ...}, the route returned
that dict unchanged, and an HTTP 200 made the frontend toast
'Source "..." created.', close the modal, and refetch a list the row was
never in. From the user's chair that is indistinguishable from a list
bug. Third instance of "an error encoded as a success response" in this
codebase (GOTCHAS), after log_action's exception swallow and
is_revoked's fail-open.

Both refusal shapes register_source can produce are pinned here.
"""

import uuid

import pytest
from sqlalchemy import select

from models.all_models import DataSource
from modules.ingestion.connector_manager import _APP_DB_URL
from services.tenant_context import tenant_session

pytestmark = pytest.mark.asyncio


async def _owner(client):
    reg = (await client.post("/api/v1/auth/register", json={
        "email": f"srcref-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Src", "tenant_name": f"Src Corp {uuid.uuid4().hex[:6]}",
    })).json()
    return {"Authorization": f"Bearer {reg['access_token']}"}, reg["tenant_id"]


async def _rows_named(tenant_id, name):
    async with tenant_session(tenant_id) as db:
        return (await db.execute(select(DataSource).where(
            DataSource.tenant_id == tenant_id, DataSource.name == name))).scalars().all()


async def test_self_referential_source_is_a_400_and_no_row(client):
    """The exact config the self-test guide originally told testers to use."""
    h, tenant_id = await _owner(client)
    self_ref = {"host": _APP_DB_URL.hostname, "port": _APP_DB_URL.port or 5432,
                "database": (_APP_DB_URL.path or "").lstrip("/"),
                "username": "someuser", "password": "SuperSecret_Pa55word!"}
    assert self_ref["host"] and self_ref["database"], "app DSN must be parseable for this test to mean anything"
    r = await client.post("/api/v1/sources/", headers=h, json={
        "name": "Encryption Test", "source_type": "postgres", "connection_config": self_ref})
    assert r.status_code == 400, r.text
    assert "application's own internal database" in r.json()["detail"]
    assert await _rows_named(tenant_id, "Encryption Test") == []
    # and the list agrees: nothing was created
    listed = (await client.get("/api/v1/sources/", headers=h)).json()
    assert listed["count"] == 0


async def test_duplicate_name_is_a_400_and_no_second_row(client):
    h, tenant_id = await _owner(client)
    body = {"name": "Warehouse", "source_type": "postgres", "connection_config": {
        "host": "warehouse-test-host", "port": 5432, "database": "customers_prod",
        "username": "u", "password": "p"}}
    first = await client.post("/api/v1/sources/", headers=h, json=body)
    assert first.status_code == 200 and first.json()["status"] == "registered", first.text
    second = await client.post("/api/v1/sources/", headers=h, json=body)
    assert second.status_code == 400, second.text
    assert "already exists" in second.json()["detail"]
    assert len(await _rows_named(tenant_id, "Warehouse")) == 1


async def test_a_legitimate_source_still_creates_and_lists(client):
    """The other half: the refusal path must not have bent the happy path."""
    h, tenant_id = await _owner(client)
    r = await client.post("/api/v1/sources/", headers=h, json={
        "name": "Legit", "source_type": "postgres", "connection_config": {
            "host": "warehouse-test-host", "port": 5432, "database": "customers_prod",
            "username": "u", "password": "p"}})
    assert r.status_code == 200 and r.json()["status"] == "registered"
    listed = (await client.get("/api/v1/sources/", headers=h)).json()
    assert [s["name"] for s in listed["sources"]] == ["Legit"]
