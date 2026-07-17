import uuid
import pytest

from modules.governance import contract_service


async def _register(client, prefix="contractsvc"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Contract Service Test",
        "tenant_name": f"Contract Service Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


@pytest.mark.asyncio
async def test_create_contract_rest_endpoint_unchanged_after_extraction(client):
    """The REST endpoint now delegates to contract_service.create_contract() —
    confirm it still returns the exact same response shape/content for the
    same request as before the extraction."""
    token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    src = await client.post("/api/v1/sources/", json={
        "name": "Contract Source", "source_type": "csv", "connection_config": {"path": "x.csv"},
    }, headers=headers)
    source_id = src.json()["id"]

    r = await client.post("/api/v1/governance/contracts", json={
        "name": "Test Contract", "producer_source_id": source_id,
        "consumer_description": "downstream team", "schema_expectations": {"columns": ["id"]},
        "quality_conditions": {"freshness_hours": 24}, "sla_hours": 12,
    }, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test Contract"
    assert body["producer_source_id"] == source_id
    assert body["validation_status"] == "pending"
    assert body["sla_hours"] == 12


@pytest.mark.asyncio
async def test_create_contract_rest_endpoint_404s_on_unknown_source(client):
    token, tenant_id = await _register(client, "contractsvc404")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/governance/contracts", json={
        "name": "Bad Contract", "producer_source_id": str(uuid.uuid4()),
    }, headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_validate_contract_rest_endpoint_unchanged_after_extraction(client):
    token, tenant_id = await _register(client, "contractsvcvalidate")
    headers = {"Authorization": f"Bearer {token}"}

    src = await client.post("/api/v1/sources/", json={
        "name": "Validate Source", "source_type": "csv", "connection_config": {"path": "x.csv"},
    }, headers=headers)
    source_id = src.json()["id"]

    created = await client.post("/api/v1/governance/contracts", json={
        "name": "Validate Contract", "producer_source_id": source_id,
        "schema_expectations": {"columns": ["id"]},
    }, headers=headers)
    contract_id = created.json()["contract_id"]

    r = await client.post(f"/api/v1/governance/contracts/{contract_id}/validate", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # No schema_snapshot on this source yet -> the "no snapshot" violation path.
    assert body["validation_status"] == "violated"
    assert any(v["check"] == "schema.no_snapshot" for v in body["violations"])


@pytest.mark.asyncio
async def test_contract_service_is_tenant_scoped(client):
    """Direct service-layer test (not just via REST) — a tenant can't create
    a contract against another tenant's source."""
    token_a, tenant_a = await _register(client, "contractsvctena")
    token_b, tenant_b = await _register(client, "contractsvctenb")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    src = await client.post("/api/v1/sources/", json={
        "name": "Tenant A Source", "source_type": "csv", "connection_config": {},
    }, headers=headers_a)
    source_id = src.json()["id"]

    result = await contract_service.create_contract(
        tenant_id=tenant_b, actor="test", name="Cross-tenant attempt",
        producer_source_id=source_id,
    )
    assert "error" in result
    assert "not found" in result["error"]
