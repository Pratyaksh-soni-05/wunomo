import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import DataSource, SourceType


async def _register(client, name: str) -> dict:
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{name}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Catalog Test", "tenant_name": f"{name} Corp",
    })
    return reg.json()


async def _create_source(tenant_id: str, name: str, source_type: SourceType,
                          schema_snapshot: dict | None = None, tags=None, owner=None) -> DataSource:
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, source_type=source_type,
            connection_config={"file_path": "/tmp/x.csv"}, schema_snapshot=schema_snapshot,
            tags=tags or [], owner=owner,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source


@pytest.mark.asyncio
async def test_unprofiled_source_appears_with_profiled_false(client):
    reg = await _register(client, "cat-unprofiled")
    await _create_source(reg["tenant_id"], "raw.csv", SourceType.CSV, schema_snapshot=None)

    res = await client.get("/api/v1/catalog/", headers={"Authorization": f"Bearer {reg['access_token']}"})
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    entry = data["entries"][0]
    assert entry["profiled"] is False
    assert entry["columns"] == []
    assert entry["row_count"] is None
    assert entry["table_name"] is None


@pytest.mark.asyncio
async def test_single_table_file_source_flattens_to_one_entry_with_normalized_columns(client):
    reg = await _register(client, "cat-file")
    snapshot = {
        "main": {
            "columns": [
                {"column_name": "id", "data_type": "int64", "is_nullable": "NO", "null_count": 0, "unique_count": 3},
                {"column_name": "email", "data_type": "object", "is_nullable": "YES", "null_count": 1, "unique_count": 2},
            ],
            "row_count": 3,
        }
    }
    await _create_source(reg["tenant_id"], "people.csv", SourceType.CSV, schema_snapshot=snapshot,
                          tags=["pii"], owner="alice@example.com")

    res = await client.get("/api/v1/catalog/", headers={"Authorization": f"Bearer {reg['access_token']}"})
    data = res.json()
    assert data["count"] == 1
    entry = data["entries"][0]
    assert entry["profiled"] is True
    assert entry["table_name"] == "main"
    assert entry["row_count"] == 3
    assert entry["column_count"] == 2
    assert entry["tags"] == ["pii"]
    assert entry["owner"] == "alice@example.com"
    assert {"name": "id", "type": "int64", "nullable": False} in entry["columns"]
    assert {"name": "email", "type": "object", "nullable": True} in entry["columns"]


@pytest.mark.asyncio
async def test_multi_table_postgres_source_flattens_to_one_entry_per_table(client):
    reg = await _register(client, "cat-multitable")
    snapshot = {
        "orders": {"columns": [{"column_name": "order_id", "data_type": "integer", "is_nullable": "NO"}], "row_count": 100},
        "customers": {"columns": [{"column_name": "customer_id", "data_type": "integer", "is_nullable": "NO"}], "row_count": 50},
    }
    await _create_source(reg["tenant_id"], "warehouse", SourceType.POSTGRES, schema_snapshot=snapshot)

    res = await client.get("/api/v1/catalog/", headers={"Authorization": f"Bearer {reg['access_token']}"})
    data = res.json()
    assert data["count"] == 2
    table_names = {e["table_name"] for e in data["entries"]}
    assert table_names == {"orders", "customers"}
    row_counts = {e["table_name"]: e["row_count"] for e in data["entries"]}
    assert row_counts == {"orders": 100, "customers": 50}


@pytest.mark.asyncio
async def test_catalog_is_tenant_scoped(client):
    reg_a = await _register(client, "cat-tenant-a")
    reg_b = await _register(client, "cat-tenant-b")
    await _create_source(reg_a["tenant_id"], "a-source.csv", SourceType.CSV)
    await _create_source(reg_b["tenant_id"], "b-source.csv", SourceType.CSV)

    res_a = await client.get("/api/v1/catalog/", headers={"Authorization": f"Bearer {reg_a['access_token']}"})
    data_a = res_a.json()
    assert data_a["count"] == 1
    assert data_a["entries"][0]["source_name"] == "a-source.csv"


@pytest.mark.asyncio
async def test_catalog_source_id_filter(client):
    reg = await _register(client, "cat-filter")
    source1 = await _create_source(reg["tenant_id"], "one.csv", SourceType.CSV)
    await _create_source(reg["tenant_id"], "two.csv", SourceType.CSV)

    res = await client.get(
        f"/api/v1/catalog/?source_id={source1.id}",
        headers={"Authorization": f"Bearer {reg['access_token']}"},
    )
    data = res.json()
    assert data["count"] == 1
    assert data["entries"][0]["source_id"] == source1.id
