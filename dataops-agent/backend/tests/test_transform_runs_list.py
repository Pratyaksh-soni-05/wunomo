import uuid
import asyncio
import pytest

from database import AsyncSessionLocal
from models.all_models import TransformRun


async def _register(client, name: str) -> dict:
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{name}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Runs List Test", "tenant_name": f"{name} Corp",
    })
    return reg.json()


async def _insert_run(tenant_id: str, user_id: str, source_id: str = "src1",
                       code: str = "SELECT 1", status: str = "success") -> TransformRun:
    async with AsyncSessionLocal() as db:
        run = TransformRun(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, source_id=source_id,
            transform_type="sql", origin="manual", code=code, status=status, row_count=1,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run


@pytest.mark.asyncio
async def test_list_runs_is_tenant_scoped(client):
    reg_a = await _register(client, "runslist-a")
    reg_b = await _register(client, "runslist-b")
    await _insert_run(reg_a["tenant_id"], reg_a["user_id"])
    await _insert_run(reg_b["tenant_id"], reg_b["user_id"])

    res = await client.get(
        "/api/v1/transformations/runs",
        headers={"Authorization": f"Bearer {reg_a['access_token']}"},
    )
    data = res.json()
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_list_runs_newest_first(client):
    reg = await _register(client, "runslist-order")
    r1 = await _insert_run(reg["tenant_id"], reg["user_id"], code="SELECT 1")
    await asyncio.sleep(0.05)
    r2 = await _insert_run(reg["tenant_id"], reg["user_id"], code="SELECT 2")

    res = await client.get(
        "/api/v1/transformations/runs",
        headers={"Authorization": f"Bearer {reg['access_token']}"},
    )
    data = res.json()
    assert [r["id"] for r in data["runs"]] == [r2.id, r1.id]


@pytest.mark.asyncio
async def test_list_runs_limit_and_offset(client):
    reg = await _register(client, "runslist-page")
    for i in range(5):
        await _insert_run(reg["tenant_id"], reg["user_id"], code=f"SELECT {i}")
        await asyncio.sleep(0.01)

    res = await client.get(
        "/api/v1/transformations/runs?limit=2&offset=1",
        headers={"Authorization": f"Bearer {reg['access_token']}"},
    )
    data = res.json()
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_list_runs_source_id_filter(client):
    reg = await _register(client, "runslist-filter")
    await _insert_run(reg["tenant_id"], reg["user_id"], source_id="source-a")
    await _insert_run(reg["tenant_id"], reg["user_id"], source_id="source-b")

    res = await client.get(
        "/api/v1/transformations/runs?source_id=source-a",
        headers={"Authorization": f"Bearer {reg['access_token']}"},
    )
    data = res.json()
    assert data["count"] == 1
    assert data["runs"][0]["source_id"] == "source-a"


@pytest.mark.asyncio
async def test_list_runs_returns_replay_fields(client):
    reg = await _register(client, "runslist-shape")
    await _insert_run(reg["tenant_id"], reg["user_id"], source_id="src-x", code="SELECT * FROM x;")

    res = await client.get(
        "/api/v1/transformations/runs",
        headers={"Authorization": f"Bearer {reg['access_token']}"},
    )
    run = res.json()["runs"][0]
    assert run["code"] == "SELECT * FROM x;"
    assert run["source_id"] == "src-x"
    assert run["transform_type"] == "sql"
    assert run["origin"] == "manual"
    assert run["status"] == "success"
