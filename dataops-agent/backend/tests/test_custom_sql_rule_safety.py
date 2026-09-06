"""Regression test for the custom_sql quality-rule security fix.

Before this fix, `QualityRuleEngine._run_rule_logic()`'s `custom_sql` branch
called `connector.execute_sql(sql)` directly -- the raw, unsandboxed
connector method with zero keyword blocking and zero SELECT-only
restriction. Anyone with `quality.manage` (Owner/Admin/Data Engineer/Data
Analyst -- everyone except Viewer) could configure a "quality rule" whose
`rule_config.sql` was arbitrary DDL/DML, and it would re-execute
automatically on every real pipeline run via `_execute_run()`'s quality
check step -- no further human interaction needed after the rule was
created once.

Fixed by routing through `SqlRunner.run_on_source()`, the same
keyword-blocklisted, SELECT/WITH-only, row-capped, audit-logged safety
layer `execute_sql_transform` already uses.

These tests run against the real, live Postgres this test suite already
talks to (see the existing "test suite hits whatever DB APP_ENV=test
resolves to" Gotcha) -- safe here specifically because the whole point is
proving destructive SQL never reaches the connection at all, and the one
real SELECT executed is a genuine no-op read.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.engine.url import make_url

from config import settings
from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline, PipelineStatus, QualityRule, SourceType, Tenant
from modules.quality.rule_engine import QualityRuleEngine
from services.tenant_context import tenant_session


# A throwaway database standing in for a customer warehouse. Created once per
# session and left in place (a few KB); the app's own database is deliberately
# NOT used -- see _real_postgres_connection_config()'s docstring.
RULE_TEST_DB = "rule_safety_testdb"


@pytest_asyncio.fixture(autouse=True, scope="module")
async def _provision_rule_test_db():
    from sqlalchemy import create_engine, text as _text
    from sqlalchemy.engine import make_url as _mu
    admin_url = settings.ADMIN_DATABASE_URL
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(_text(
            "SELECT 1 FROM pg_database WHERE datname = :d"), {"d": RULE_TEST_DB}).first()
        if not exists:
            c.execute(_text(f'CREATE DATABASE "{RULE_TEST_DB}"'))
    target = _mu(admin_url).set(database=RULE_TEST_DB).render_as_string(hide_password=False)
    eng = create_engine(target)
    with eng.begin() as c:
        c.execute(_text("CREATE TABLE IF NOT EXISTS widgets "
                        "(id int primary key, name text)"))
        c.execute(_text("INSERT INTO widgets (id, name) VALUES (1,'alpha'),(2,'beta') "
                        "ON CONFLICT (id) DO NOTHING"))
        # The app role reads it through PostgresConnector's own connection.
        c.execute(_text("GRANT SELECT ON widgets TO dataops_app"))
    eng.dispose(); admin.dispose()
    yield


def _real_postgres_connection_config() -> dict:
    """Points a DataSource at a real, reachable Postgres database that is NOT
    the application's own.

    It used to point at the app database with `table: "tenants"`. That stopped
    working when Row-Level Security landed, for two independent reasons, and
    both are the correct behaviour rather than something to work around:

    1. `PostgresConnector` opens its OWN raw asyncpg connection (CLAUDE.md Hard
       Rule 1's documented pattern) rather than using the app's SQLAlchemy
       session, so it never carries `app.current_tenant_id`. Every app table is
       therefore invisible to it, and `preview("tenants")` returns zero rows,
       which `_run_rule_logic()` reports as "No data to check". Nothing is
       broken -- the connector is talking to what it thinks is a customer
       warehouse, where our policies rightly do not apply.
    2. Production forbids this configuration outright:
       `connector_manager._points_at_app_database()` rejects any source whose
       host+database match the app's own. This test only ever reached that
       state by inserting the DataSource row directly, bypassing the guard.

    So the fixture now provisions its own throwaway database with a real table
    and real rows -- an honest stand-in for a customer warehouse, which is what
    a Postgres DataSource actually is."""
    url = make_url(settings.DATABASE_URL)
    return {
        "host": url.host, "port": url.port or 5432,
        "database": RULE_TEST_DB, "username": url.username,
        "password": url.password, "table": "widgets",
    }


async def _register(client, prefix="sqlrule"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "SQL Rule Test",
        "tenant_name": f"SQL Rule Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()


async def _make_pipeline_with_source(tenant_id: str, source_type: SourceType, connection_config: dict) -> str:
    async with tenant_session(tenant_id) as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="test-source",
            source_type=source_type, connection_config=connection_config,
        )
        db.add(source)
        await db.flush()
        pipeline = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, source_id=source.id,
            name="test-pipeline", status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.commit()
        return pipeline.id


async def _make_custom_sql_rule(tenant_id: str, pipeline_id: str, sql: str) -> str:
    async with tenant_session(tenant_id) as db:
        rule = QualityRule(
            id=str(uuid.uuid4()), tenant_id=tenant_id, pipeline_id=pipeline_id,
            name="custom sql rule", rule_type="custom_sql",
            # column_name must be non-empty for _run_rule_logic() to reach
            # the custom_sql branch at all -- it's gated behind the same
            # `if not col: skip` guard every column-level check shares, even
            # though custom_sql itself never reads the column value. A real
            # attacker satisfies this trivially (any single character), so
            # it isn't a meaningful barrier -- just a structural code-order
            # quirk this test has to replicate to reach the real code path.
            column_name="id",
            rule_config={"sql": sql}, is_active=True,
        )
        db.add(rule)
        await db.commit()
        return rule.id


@pytest.mark.asyncio
async def test_destructive_custom_sql_is_rejected_not_executed(client):
    """The core security property: a DROP TABLE configured as a custom_sql
    rule must never actually run, and the target table must still exist
    afterward -- not just that the rule result says 'failed'."""
    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    pipeline_id = await _make_pipeline_with_source(
        tenant_id, SourceType.POSTGRES, _real_postgres_connection_config()
    )
    await _make_custom_sql_rule(tenant_id, pipeline_id, "DROP TABLE tenants; --")

    result = await QualityRuleEngine(tenant_id).run_checks(pipeline_id)
    rule_result = result["results"][0]

    assert rule_result["passed"] is False
    assert "rejected" in rule_result["message"].lower()
    # This used to assert `"drop" in message` -- that the rejection echoed the
    # offending keyword back. Item #5 deliberately stopped doing that: this
    # message is returned over the API and fed into the LLM's context, and a
    # rejection that names the token it tripped on hands an attacker the rule
    # set one probe at a time. So the assertion is inverted rather than
    # dropped. The security property this test exists for is untouched -- it
    # is the "tenants table still exists" check below, not the wording.
    assert "drop" not in rule_result["message"].lower(), (
        "rejection message should not echo the blocked construct: "
        f"{rule_result['message']!r}"
    )

    # The real proof: the tenants table was never actually touched.
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        assert r.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_legitimate_custom_sql_select_still_works(client):
    """A real, safe SELECT-based violation-counting query still executes
    and produces a real result -- the fix closes the hole without breaking
    the feature's legitimate use case."""
    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    pipeline_id = await _make_pipeline_with_source(
        tenant_id, SourceType.POSTGRES, _real_postgres_connection_config()
    )
    # A genuine no-op read against the stand-in warehouse: zero rows back,
    # since no widget has this id. (Was `FROM tenants` when this fixture
    # pointed at the app's own database - see _real_postgres_connection_config.)
    await _make_custom_sql_rule(
        tenant_id, pipeline_id, "SELECT id FROM widgets WHERE id = -12345"
    )

    result = await QualityRuleEngine(tenant_id).run_checks(pipeline_id)
    rule_result = result["results"][0]

    assert rule_result["passed"] is True
    assert "0 violation" in rule_result["message"]


@pytest.mark.asyncio
async def test_custom_sql_skips_harmlessly_for_non_sql_sources(client, tmp_path):
    """Preserves the pre-fix behavior for source types SqlRunner doesn't
    support (csv/file/etc) -- these should still no-op, not error. Needs a
    real, readable file so connector.preview() (called unconditionally
    before the custom_sql branch, same as every column-level check)
    succeeds rather than short-circuiting on a missing-file error first."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("id,name\n1,alice\n2,bob\n")

    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    pipeline_id = await _make_pipeline_with_source(
        tenant_id, SourceType.CSV, {"file_path": str(csv_path)}
    )
    await _make_custom_sql_rule(tenant_id, pipeline_id, "DROP TABLE tenants; --")

    result = await QualityRuleEngine(tenant_id).run_checks(pipeline_id)
    rule_result = result["results"][0]

    assert rule_result["passed"] is True
    assert "not a sql source" in rule_result["message"].lower()
