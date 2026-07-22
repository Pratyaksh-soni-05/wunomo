import io
import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User
from services.auth_service import issue_token_for_user
from sqlalchemy import select


def _csv_bytes():
    return b"a,b\n1,2\n"


async def _register_user(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"uploadtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Upload Test",
        "tenant_name": "Upload Test Corp",
    })
    return reg.json()["access_token"]


@pytest.mark.asyncio
async def test_upload_register_uses_client_supplied_name(client):
    """Regression test: the `name` form field wasn't declared with Form(...),
    so a client-supplied name was silently ignored in favor of the raw
    filename. Confirm the client's chosen name is actually used now."""
    token = await _register_user(client)
    r = await client.post(
        "/api/v1/uploads/register",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("data.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"name": "My Chosen Source Name"},
    )
    assert r.status_code == 200, r.text

    token_headers = {"Authorization": f"Bearer {token}"}
    sources = await client.get("/api/v1/sources/", headers=token_headers)
    names = [s["name"] for s in sources.json()["sources"]]
    assert "My Chosen Source Name" in names
    assert "data.csv" not in names


@pytest.mark.asyncio
async def test_upload_register_name_collision_returns_409_not_crash(client):
    """Regression test: a second upload that resolves to the same source
    name previously crashed upload_and_register with an unhandled
    KeyError('id') when register_source() returned {"error": ...} instead
    of a dict with "id". Must now return a clean 409 with a clear message.
    """
    token = await _register_user(client)
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/api/v1/uploads/register",
        headers=headers,
        files={"file": ("first.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"name": "Duplicate Name"},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/v1/uploads/register",
        headers=headers,
        files={"file": ("second.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"name": "Duplicate Name"},
    )
    assert second.status_code == 409, second.text
    assert "already exists" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_register_requires_sources_create_permission(client):
    """Phase 19 gap found while building the upload UI: /uploads/register
    creates a real DataSource (the same action POST /sources/ gates behind
    sources.create) but was never migrated onto require_permission() in the
    original permission-spec pass. A Viewer must be denied with a real 403,
    not silently allowed to register a source via the upload path while
    blocked on the JSON path."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"uploadviewer-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Upload Viewer Test",
        "tenant_name": "Upload Viewer Corp",
    })
    user_id = reg.json()["user_id"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        viewer_token = issue_token_for_user(user, "password")

    r = await client.post(
        "/api/v1/uploads/register",
        headers={"Authorization": f"Bearer {viewer_token}"},
        files={"file": ("blocked.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"name": "Should Not Be Created"},
    )
    assert r.status_code == 403, r.text
