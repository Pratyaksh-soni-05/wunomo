"""Wunomo Projects Phase 2, item 5: ingest_file and register_data_source
become attach-only. An agent can target an existing upload, never invent
source_type or connection_config -- both chat tools funnel into
ConnectorManager methods that derive them from a real file already
sitting under UPLOAD_DIR (something a human put there via
POST /api/v1/uploads/), rejecting anything else, including a path-
traversal attempt at reading an arbitrary file elsewhere on disk.
"""
import io
import uuid

import pytest

from modules.ingestion.connector_manager import ConnectorManager, UPLOAD_DIR


def _csv_bytes():
    return b"a,b\n1,2\n"


async def _register_user(client, prefix="attach"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Attach Only Test",
        "tenant_name": f"Attach Only Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ingest_file_rejects_a_path_outside_the_upload_directory(client):
    """The core of attach-only: file_path is validated against UPLOAD_DIR,
    never trusted as an arbitrary filesystem path an LLM could hand in."""
    token, tenant_id = await _register_user(client, "ingestpath")
    result = await ConnectorManager(tenant_id).ingest_file("/etc/passwd")
    assert result["status"] == "error"
    assert "not an arbitrary path" in result["error"]


@pytest.mark.asyncio
async def test_ingest_file_rejects_a_nonexistent_path_under_the_upload_directory():
    """A path that resolves under UPLOAD_DIR but was never actually
    written by an upload must still be rejected, not silently attempted."""
    result = await ConnectorManager("some-tenant").ingest_file(f"{UPLOAD_DIR}/does-not-exist.csv")
    assert result["status"] == "error"
    assert "no uploaded file found" in result["error"].lower()


@pytest.mark.asyncio
async def test_ingest_file_parses_a_real_upload(client):
    """The happy path: a file a human actually uploaded via
    POST /api/v1/uploads/ can still be parsed for preview/schema."""
    token, tenant_id = await _register_user(client, "ingestreal")
    up = await client.post(
        "/api/v1/uploads/",
        headers=_auth(token),
        files={"file": ("data.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    assert up.status_code == 200, up.text
    real_path = up.json()["path"]

    result = await ConnectorManager(tenant_id).ingest_file(real_path)
    assert result["status"] == "ingested"
    assert result["columns"] == ["a", "b"]


@pytest.mark.asyncio
async def test_register_data_source_rejects_a_path_outside_the_upload_directory():
    """register_uploaded_file (register_data_source's chat-tool target)
    must never register a source pointing at an arbitrary filesystem
    path -- only a file a human actually uploaded."""
    result = await ConnectorManager("some-tenant").register_uploaded_file(
        name="Sneaky Source", file_path="/etc/passwd",
    )
    assert "error" in result
    assert result["status_code"] == 422
    assert "not an arbitrary path" in result["error"]


@pytest.mark.asyncio
async def test_register_data_source_derives_type_and_config_from_the_real_upload(client):
    """The core positive case: name is the only thing the caller supplies
    besides file_path -- source_type and connection_config come from the
    real file on disk, matching what upload_and_register would have
    derived, never something the caller asserts."""
    token, tenant_id = await _register_user(client, "attachreal")
    up = await client.post(
        "/api/v1/uploads/",
        headers=_auth(token),
        files={"file": ("data.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    real_path = up.json()["path"]

    result = await ConnectorManager(tenant_id).register_uploaded_file(
        name="Attached CSV Source", file_path=real_path,
    )
    assert result["status"] == "registered", result
    assert result["source_type"] == "csv"

    token_headers = _auth(token)
    sources = await client.get("/api/v1/sources/", headers=token_headers)
    names = [s["name"] for s in sources.json()["sources"]]
    assert "Attached CSV Source" in names


@pytest.mark.asyncio
async def test_register_data_source_still_rejects_pdf_even_for_a_real_upload(client):
    """item 1's PDF/DOCX rejection lives in register_source() itself, so
    register_uploaded_file inherits it for free -- a real uploaded PDF
    still can't become a source, since there's still no connector for it."""
    token, tenant_id = await _register_user(client, "attachpdf")
    up = await client.post(
        "/api/v1/uploads/",
        headers=_auth(token),
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    real_path = up.json()["path"]

    result = await ConnectorManager(tenant_id).register_uploaded_file(
        name="A PDF Source", file_path=real_path,
    )
    assert result["status_code"] == 422
    assert "no working connector" in result["error"].lower()
