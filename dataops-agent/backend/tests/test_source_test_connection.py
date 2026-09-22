"""Wunomo Projects Phase 2 frontend, slice 5: POST /api/v1/sources/test-connection.

Runs through the real connector classes (PostgresConnector/MySQLConnector)
used by a real sync -- never a second, ad-hoc asyncpg/pymysql connect (see
the endpoint's own docstring in api/v1/sources.py). Tested against the
real dev postgres container (the docker-compose 'postgres' service, same
credentials the backend itself uses) rather than mocked, since the whole
point of this endpoint is proving a real connection works or naming why
it doesn't.

No MySQL service exists in this docker-compose stack, so MySQL coverage
here is limited to what's deterministic without one (the localhost check,
the unsupported-type gate): a known, explicit gap, not an assumed one.

Real-success/auth/missing-field tests connect to a dedicated
`test_connection_target` database on the same real postgres container --
never the app's own `dataops` database. That's not incidental: this
endpoint's own `_points_at_app_database` guard (added in this same
change, alongside register_source()'s pre-existing one) correctly refuses
`dataops` itself, which is exactly what test_points_at_app_database_is_
refused_before_connecting below proves. Using the app's own DB as the
"real success" fixture would be testing against a target the endpoint is
specifically supposed to reject.
"""
import uuid

import asyncpg
import pytest
import pytest_asyncio

from config import settings

TEST_TARGET_DB = "test_connection_target"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _ensure_test_target_db():
    """Session-cheap, not torn down -- an empty extra database on the dev
    postgres container is harmless test scaffolding, unlike the row-based
    test-data accumulation already tracked elsewhere (item 74)."""
    dsn = settings.DATABASE_URL.replace("+asyncpg", "").replace("+psycopg2", "")
    conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_TARGET_DB)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_TARGET_DB}"')
    finally:
        await conn.close()
    yield


async def _register(client, prefix="testconn"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Test Connection Test",
        "tenant_name": f"Test Connection Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unsupported types report a clear gap, not a silent pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsupported_type_returns_422_not_a_silent_ok(client):
    token = await _register(client, "tcA")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "csv", "connection_config": {"file_path": "x.csv"},
    })
    assert resp.status_code == 422
    assert "csv" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Hard Rule 4: localhost is caught explicitly, before any connection attempt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_localhost_host_is_named_explicitly_for_postgres(client):
    token = await _register(client, "tcB")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {"host": "localhost", "database": "x", "user": "x", "password": "x"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "host_is_localhost"
    assert "container itself" in body["message"]


@pytest.mark.asyncio
async def test_localhost_host_is_named_explicitly_for_mysql(client):
    token = await _register(client, "tcC")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "mysql",
        "connection_config": {"host": "localhost", "database": "x", "user": "x", "password": "x"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "host_is_localhost"


# ---------------------------------------------------------------------------
# Real postgres, real dev container -- the actual connect-before-you-save proof
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_real_postgres_success(client):
    token = await _register(client, "tcD")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {
            "host": "postgres", "port": 5432, "database": TEST_TARGET_DB,
            "user": "dataops_user", "password": "changeme",
        },
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["tables_found"] == 0  # freshly created, genuinely empty


@pytest.mark.asyncio
async def test_real_postgres_wrong_password_names_auth_rejected(client):
    token = await _register(client, "tcE")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {
            "host": "postgres", "port": 5432, "database": TEST_TARGET_DB,
            "user": "dataops_user", "password": "definitely-wrong",
        },
    })
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "auth_rejected"
    assert "password" in body["message"].lower()


@pytest.mark.asyncio
async def test_points_at_app_database_is_refused_before_connecting(client):
    """The bug found live during this same slice's UI verification: testing
    a connection to the app's own control-plane database used to report a
    real "Connected" success (it genuinely can be reached), only for the
    actual Create to then be silently refused by register_source()'s own,
    older guard. Both now share the same check."""
    token = await _register(client, "tcI")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {
            "host": "postgres", "port": 5432, "database": "dataops",
            "user": "dataops_user", "password": "changeme",
        },
    })
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "points_at_app_database"
    assert "every tenant's data" in body["message"]


@pytest.mark.asyncio
async def test_real_postgres_unknown_database_is_named(client):
    token = await _register(client, "tcF")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {
            "host": "postgres", "port": 5432, "database": "definitely_not_a_real_db_xyz",
            "user": "dataops_user", "password": "changeme",
        },
    })
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "database_not_found"
    assert "definitely_not_a_real_db_xyz" in body["message"]


@pytest.mark.asyncio
async def test_real_postgres_unreachable_host_is_not_a_bare_connection_failed(client):
    token = await _register(client, "tcG")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {
            "host": "this-host-does-not-exist-xyz", "port": 5432, "database": "x",
            "user": "x", "password": "x",
        },
    })
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "connection_failed"
    assert body["message"] != "connection failed"
    assert len(body["message"]) > len("connection failed")


@pytest.mark.asyncio
async def test_missing_required_field_is_named_not_a_generic_failure(client):
    token = await _register(client, "tcH")
    resp = await client.post("/api/v1/sources/test-connection", headers=_auth(token), json={
        "source_type": "postgres",
        "connection_config": {"host": "postgres", "database": TEST_TARGET_DB, "user": "dataops_user"},
    })
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "missing_field"
    assert "password" in body["message"]
