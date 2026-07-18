import uuid
import pytest
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import TransformRun, DataSource, SourceType
from modules.transformation.transform_run_log import log_transform_run
from agent.tools.transformation_tools import execute_sql_transform, run_python_transform


async def _register(client, name: str) -> dict:
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{name}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Transform Run Test", "tenant_name": f"{name} Corp",
    })
    return reg.json()


async def _create_source(tenant_id: str) -> str:
    """Insert a real DataSource directly (bypassing register_source/the REST
    endpoint) — the runner calls in these tests are monkeypatched, so the
    connection_config's contents don't matter, only that a real row with a
    real id exists to attach the TransformRun to. Registering a source that
    actually points at this app's own Postgres DB is deliberately blocked
    (modules/ingestion/connector_manager.py's internal-DB guard), so a fake
    csv path is used instead of trying to route around that guard."""
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="test-source.csv",
            source_type=SourceType.CSV, connection_config={"file_path": "/tmp/test.csv"},
        )
        db.add(source)
        await db.commit()
        return source.id


async def _runs_for_tenant(tenant_id: str) -> list[TransformRun]:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TransformRun).where(TransformRun.tenant_id == tenant_id))
        return r.scalars().all()


@pytest.mark.asyncio
async def test_log_transform_run_persists_success_row():
    tenant_id = str(uuid.uuid4())
    await log_transform_run(
        tenant_id=tenant_id, user_id="u1", session_id="s1", source_id="src1",
        transform_type="sql", origin="manual", code="SELECT 1;",
        result={"rows": [{"a": 1}], "row_count": 1, "duration_ms": 12.3},
    )
    runs = await _runs_for_tenant(tenant_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "success"
    assert run.row_count == 1
    assert run.code == "SELECT 1;"
    assert run.result_preview == [{"a": 1}]
    assert run.error_message is None


@pytest.mark.asyncio
async def test_log_transform_run_persists_error_row():
    tenant_id = str(uuid.uuid4())
    await log_transform_run(
        tenant_id=tenant_id, user_id="u1", session_id=None, source_id="src1",
        transform_type="pandas", origin="chat_agent", code="result_df = df",
        result={"error": "boom"},
    )
    runs = await _runs_for_tenant(tenant_id)
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert runs[0].error_message == "boom"
    assert runs[0].row_count is None
    assert runs[0].result_preview is None


@pytest.mark.asyncio
async def test_log_transform_run_caps_result_preview_to_20_rows():
    tenant_id = str(uuid.uuid4())
    rows = [{"n": i} for i in range(50)]
    await log_transform_run(
        tenant_id=tenant_id, user_id="u1", session_id=None, source_id="src1",
        transform_type="sql", origin="manual", code="SELECT * FROM big;",
        result={"rows": rows, "row_count": 50, "duration_ms": 1},
    )
    runs = await _runs_for_tenant(tenant_id)
    assert len(runs[0].result_preview) == 20


@pytest.mark.asyncio
async def test_run_sql_endpoint_persists_a_real_transform_run(client, monkeypatch):
    reg = await _register(client, "sqlrun")
    token = reg["access_token"]
    source_id = await _create_source(reg["tenant_id"])

    import modules.transformation.sql_runner as sql_runner_module
    async def fake_run_on_source(self, source_id, sql, **kwargs):
        return {"rows": [{"a": 1}], "columns": ["a"], "row_count": 1,
                "truncated": False, "duration_ms": 5.0, "source_id": source_id, "executed_sql": sql}
    monkeypatch.setattr(sql_runner_module.SqlRunner, "run_on_source", fake_run_on_source)

    res = await client.post(
        "/api/v1/transformations/run/sql",
        json={"source_id": source_id, "sql": "SELECT 1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200

    runs = await _runs_for_tenant(reg["tenant_id"])
    assert len(runs) == 1
    run = runs[0]
    assert run.transform_type == "sql"
    assert run.origin == "manual"
    assert run.status == "success"
    assert run.source_id == source_id
    assert run.user_id == reg["user_id"]
    assert run.session_id is None


@pytest.mark.asyncio
async def test_run_sql_dry_run_endpoint_does_not_persist(client, monkeypatch):
    """Dry-run/EXPLAIN calls must never create a TransformRun row — only real
    executions, per the approved Phase 13 scope."""
    reg = await _register(client, "dryrun")
    token = reg["access_token"]
    source_id = await _create_source(reg["tenant_id"])

    import modules.transformation.sql_runner as sql_runner_module
    async def fake_dry_run(self, source_id, sql):
        return {"plan": [{"step": "Seq Scan"}], "columns": ["step"], "source_id": source_id}
    monkeypatch.setattr(sql_runner_module.SqlRunner, "dry_run", fake_dry_run)

    await client.post(
        "/api/v1/transformations/run/sql/dry-run",
        json={"source_id": source_id, "sql": "SELECT 1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    runs = await _runs_for_tenant(reg["tenant_id"])
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_run_pandas_endpoint_persists_a_real_transform_run(client, monkeypatch):
    reg = await _register(client, "pandasrun")
    token = reg["access_token"]
    source_id = await _create_source(reg["tenant_id"])

    import modules.transformation.python_runner as python_runner_module
    async def fake_run_on_source(self, source_id, code, **kwargs):
        return {"rows": [{"a": 1}], "columns": ["a"], "row_count": 1,
                "truncated": False, "duration_ms": 5.0, "source_id": source_id, "warnings": []}
    monkeypatch.setattr(python_runner_module.PythonRunner, "run_on_source", fake_run_on_source)

    res = await client.post(
        "/api/v1/transformations/run/pandas",
        json={"source_id": source_id, "code": "result_df = df.head(1)"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200

    runs = await _runs_for_tenant(reg["tenant_id"])
    assert len(runs) == 1
    assert runs[0].transform_type == "pandas"
    assert runs[0].origin == "manual"
    assert runs[0].status == "success"


@pytest.mark.asyncio
async def test_execute_sql_transform_tool_persists_only_on_real_execution():
    """dry_run=True (the default) must not persist; dry_run=False must, with
    origin='chat_agent' and the real tenant/user/session forced in (as
    agent_node's existing generic force-override loop already does for any
    tool declaring these params — proven by
    test_agent_forces_real_user_id_and_session_id_too)."""
    tenant_id = str(uuid.uuid4())

    # dry_run defaults True -- no persistence expected regardless of outcome
    await execute_sql_transform.ainvoke({
        "tenant_id": tenant_id, "user_id": "u1", "session_id": "s1",
        "sql": "SELECT 1", "source_id": "nonexistent-source", "dry_run": True,
    })
    assert len(await _runs_for_tenant(tenant_id)) == 0

    # dry_run=False -- persists even though the source doesn't exist (status: error)
    await execute_sql_transform.ainvoke({
        "tenant_id": tenant_id, "user_id": "u1", "session_id": "s1",
        "sql": "SELECT 1", "source_id": "nonexistent-source", "dry_run": False,
    })
    runs = await _runs_for_tenant(tenant_id)
    assert len(runs) == 1
    assert runs[0].origin == "chat_agent"
    assert runs[0].status == "error"
    assert runs[0].user_id == "u1"
    assert runs[0].session_id == "s1"


@pytest.mark.asyncio
async def test_run_python_transform_tool_persists_with_chat_agent_origin():
    tenant_id = str(uuid.uuid4())
    await run_python_transform.ainvoke({
        "tenant_id": tenant_id, "user_id": "u2", "session_id": "s2",
        "source_id": "nonexistent-source", "script": "result_df = df",
    })
    runs = await _runs_for_tenant(tenant_id)
    assert len(runs) == 1
    assert runs[0].origin == "chat_agent"
    assert runs[0].transform_type == "pandas"
    assert runs[0].status == "error"  # source doesn't exist
