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
from sqlalchemy import select
from sqlalchemy.engine.url import make_url

from config import settings
from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline, PipelineStatus, QualityRule, SourceType, Tenant
from modules.quality.rule_engine import QualityRuleEngine


def _real_postgres_connection_config() -> dict:
    """Points a DataSource at the exact same reachable Postgres server this
    test process already talks to -- needed so a legitimate custom_sql
    SELECT has something real to execute against. `table: "tenants"` is a
    real, always-present table, needed because _run_rule_logic() calls
    connector.preview() on this table BEFORE it ever reaches the
    custom_sql branch (see the column_name note below)."""
    url = make_url(settings.DATABASE_URL)
    return {
        "host": url.host, "port": url.port or 5432,
        "database": url.database, "username": url.username,
        "password": url.password, "table": "tenants",
    }


async def _register(client, prefix="sqlrule"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "SQL Rule Test",
        "tenant_name": f"SQL Rule Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()


async def _make_pipeline_with_source(tenant_id: str, source_type: SourceType, connection_config: dict) -> str:
    async with AsyncSessionLocal() as db:
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
    async with AsyncSessionLocal() as db:
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
    assert "drop" in rule_result["message"].lower()

    # The real proof: the tenants table was never actually touched.
    async with AsyncSessionLocal() as db:
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
    # A genuine no-op read: zero rows back, since no tenant has this id.
    await _make_custom_sql_rule(
        tenant_id, pipeline_id, "SELECT id FROM tenants WHERE id = 'nonexistent-marker'"
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
