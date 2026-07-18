import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import DataSource, SourceType
from modules.transformation.transform_generator import TransformGenerator


async def _make_profiled_source(tenant_id: str, schema_snapshot: dict) -> DataSource:
    """Insert a real DataSource with a real schema_snapshot shape, matching
    what SchemaProfiler._profile_file/_profile_postgres/_profile_mysql
    actually produce (table-name-keyed dict of {"columns": [...], "row_count": N},
    each column using "column_name"/"data_type"/"is_nullable") — not a
    hand-rolled shape that would silently agree with a wrong assumption."""
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name="orders.csv",
            source_type=SourceType.CSV,
            connection_config={"file_path": "/tmp/orders.csv"},
            schema_snapshot=schema_snapshot,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source


@pytest.mark.asyncio
async def test_resolve_schema_reads_real_profiler_shape_not_a_flat_assumption(client):
    """Regression test for a bug found while designing Phase 13: _resolve_schema
    read snapshot.get("columns", []) assuming a flat {"columns": [...]} shape,
    but SchemaProfiler always nests columns under a table-name key (e.g.
    {"main": {"columns": [...], "row_count": N}}), and each column dict uses
    "column_name"/"data_type"/"is_nullable" (SchemaProfiler's real field names),
    not "name"/"type"/"nullable". Before the fix, this meant every SQL/pandas
    generation call silently ran schema-blind for every already-profiled
    source, regardless of how much real profiling data existed — no crash, no
    error, just always None from _resolve_schema and 'schema_used': False in
    every response.
    """
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"tgtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Transform Gen Test", "tenant_name": "TG Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]
    real_snapshot = {
        "main": {
            "columns": [
                {"column_name": "order_id", "data_type": "int64", "is_nullable": "NO",
                 "null_count": 0, "unique_count": 500},
                {"column_name": "customer_email", "data_type": "object", "is_nullable": "YES",
                 "null_count": 3, "unique_count": 480},
            ],
            "row_count": 500,
        }
    }
    source = await _make_profiled_source(tenant_id, real_snapshot)

    gen = TransformGenerator(tenant_id)
    schema_str, resolved_id = await gen._resolve_schema(source_id=source.id, pipeline_id=None)

    assert resolved_id == source.id
    assert schema_str is not None, "schema_str must not be None for an already-profiled source"
    assert "order_id" in schema_str
    assert "int64" in schema_str
    assert "customer_email" in schema_str
    assert "(nullable)" in schema_str  # customer_email is nullable, order_id isn't
    assert "500" in schema_str  # row_count


@pytest.mark.asyncio
async def test_generate_sql_prompt_actually_contains_real_profiled_columns(client, monkeypatch):
    """End-to-end (within generate_sql) proof that the real column names reach
    the LLM prompt, not just that _resolve_schema returns a non-None string in
    isolation — captures the actual user_content passed to invoke_llm."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"tgtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Transform Gen Test", "tenant_name": "TG Test Corp 2",
    })
    tenant_id = reg.json()["tenant_id"]
    real_snapshot = {
        "main": {
            "columns": [
                {"column_name": "revenue_usd", "data_type": "float64", "is_nullable": "NO"},
            ],
            "row_count": 42,
        }
    }
    source = await _make_profiled_source(tenant_id, real_snapshot)

    captured = {}

    async def fake_invoke_llm(messages, tenant_id=None, request_type=None, **kwargs):
        captured["user_content"] = messages[-1].content
        return "SELECT revenue_usd FROM main LIMIT 10;"

    import modules.transformation.transform_generator as tg_module
    monkeypatch.setattr(tg_module, "invoke_llm", fake_invoke_llm)

    gen = TransformGenerator(tenant_id)
    result = await gen.generate_sql(request="sum revenue", source_id=source.id)

    assert result["schema_used"] is True
    assert "revenue_usd" in captured["user_content"]
    assert "float64" in captured["user_content"]
