import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline, SourceType, PipelineStatus


async def _register(client, prefix="lineage"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Lineage Test",
        "tenant_name": f"Lineage Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


@pytest.mark.asyncio
async def test_creating_source_via_api_registers_lineage_node(client):
    token, tenant_id = await _register(client, "lineagesrc")
    headers = {"Authorization": f"Bearer {token}"}

    src = await client.post("/api/v1/sources/", json={
        "name": "Sales CSV", "source_type": "csv", "connection_config": {"path": "sales.csv"},
    }, headers=headers)
    assert src.status_code == 200

    graph = await client.get("/api/v1/governance/graph", headers=headers)
    assert graph.status_code == 200
    nodes = graph.json()["nodes"]
    assert any(n["name"] == "Sales CSV" and n["node_type"] == "source" for n in nodes)


@pytest.mark.asyncio
async def test_creating_pipeline_with_source_registers_node_and_edge(client):
    token, tenant_id = await _register(client, "lineagepipe")
    headers = {"Authorization": f"Bearer {token}"}

    src = await client.post("/api/v1/sources/", json={
        "name": "Orders DB", "source_type": "csv", "connection_config": {"path": "orders.csv"},
    }, headers=headers)
    source_id = src.json()["id"]

    pipe = await client.post("/api/v1/pipelines/", json={
        "name": "Orders ETL", "source_id": source_id,
    }, headers=headers)
    assert pipe.status_code == 200

    graph = await client.get("/api/v1/governance/graph", headers=headers)
    body = graph.json()
    nodes_by_name = {n["name"]: n for n in body["nodes"]}
    assert "Orders DB" in nodes_by_name
    assert "Orders ETL" in nodes_by_name
    assert nodes_by_name["Orders ETL"]["node_type"] == "pipeline"

    source_node_id = nodes_by_name["Orders DB"]["id"]
    pipeline_node_id = nodes_by_name["Orders ETL"]["id"]
    assert any(
        e["upstream_id"] == source_node_id and e["downstream_id"] == pipeline_node_id
        for e in body["edges"]
    )


@pytest.mark.asyncio
async def test_pre_existing_source_and_pipeline_are_backfilled_on_read(client):
    """Simulates data that existed before lineage auto-population shipped —
    inserted directly via the DB, never touching register_source()/create_pipeline()."""
    token, tenant_id = await _register(client, "lineagebackfill")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="Legacy Source",
            source_type=SourceType.CSV, connection_config={},
        )
        db.add(source)
        pipeline = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, source_id=source.id,
            name="Legacy Pipeline", status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.commit()

    graph = await client.get("/api/v1/governance/graph", headers=headers)
    body = graph.json()
    nodes_by_name = {n["name"]: n for n in body["nodes"]}
    assert "Legacy Source" in nodes_by_name
    assert "Legacy Pipeline" in nodes_by_name
    assert any(
        e["upstream_id"] == nodes_by_name["Legacy Source"]["id"]
        and e["downstream_id"] == nodes_by_name["Legacy Pipeline"]["id"]
        for e in body["edges"]
    )


@pytest.mark.asyncio
async def test_lineage_sync_is_idempotent(client):
    token, tenant_id = await _register(client, "lineageidem")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/api/v1/sources/", json={
        "name": "Repeat Source", "source_type": "csv", "connection_config": {},
    }, headers=headers)

    first = await client.get("/api/v1/governance/graph", headers=headers)
    second = await client.get("/api/v1/governance/graph", headers=headers)
    assert first.json()["node_count"] == second.json()["node_count"]
    assert first.json()["edge_count"] == second.json()["edge_count"]


@pytest.mark.asyncio
async def test_lineage_sync_is_tenant_scoped(client):
    token_a, tenant_a = await _register(client, "lineagetena")
    token_b, tenant_b = await _register(client, "lineagetenb")

    await client.post("/api/v1/sources/", json={
        "name": "Tenant A Source", "source_type": "csv", "connection_config": {},
    }, headers={"Authorization": f"Bearer {token_a}"})
    await client.post("/api/v1/sources/", json={
        "name": "Tenant B Source", "source_type": "csv", "connection_config": {},
    }, headers={"Authorization": f"Bearer {token_b}"})

    graph_a = await client.get("/api/v1/governance/graph", headers={"Authorization": f"Bearer {token_a}"})
    graph_b = await client.get("/api/v1/governance/graph", headers={"Authorization": f"Bearer {token_b}"})

    names_a = {n["name"] for n in graph_a.json()["nodes"]}
    names_b = {n["name"] for n in graph_b.json()["nodes"]}
    assert "Tenant A Source" in names_a and "Tenant B Source" not in names_a
    assert "Tenant B Source" in names_b and "Tenant A Source" not in names_b
