"""Adversarial cross-tenant tests — the ones that prove Item #2 is real.

Everything here is deliberately structured to fail if Row-Level Security stops
working, **even when the application's own `WHERE tenant_id = ...` clauses are
perfectly correct**. That is the whole point: the app-layer filter was already
there before this work, and it was never the guarantee — it was a convention
that any new query could forget. These tests bypass it entirely and ask the
database directly.

Concretely, the reads below are raw SQL with **no tenant predicate at all**
(`SELECT ... WHERE id = :victim_id`). If RLS were disabled, dropped, or silently
bypassed, they would return the other tenant's row and these tests would fail.
Deleting the app's ORM filters would not make them pass.

They also depend on the suite running as `dataops_app` — a NOSUPERUSER,
NOBYPASSRLS role. `test_connection_role_is_not_privileged` asserts exactly that,
because every other assertion in this file is worthless if the connection role
can bypass RLS (which is precisely what `dataops_user` does, and why the role
split exists).
"""
import uuid

import pytest
from sqlalchemy import text

from database import AsyncSessionLocal, engine
from config import settings
from models.all_models import (
    DataSource, Incident, IncidentSeverity, IncidentStatus,
    Pipeline, PipelineStatus, SourceType, Tenant,
)
from services.tenant_context import tenant_session, async_tenant_context


async def _make_tenant_with_resources(label: str) -> dict:
    """Create a tenant plus one Source, Pipeline and Incident, in its own context."""
    tenant_id = str(uuid.uuid4())
    ids = {"tenant_id": tenant_id}
    async with async_tenant_context(tenant_id), AsyncSessionLocal() as db:
        db.add(Tenant(
            id=tenant_id, name=f"RLS {label} {tenant_id[:8]}",
            slug=f"rls-{label}-{tenant_id[:8]}",
        ))
        await db.flush()

        ids["source_id"] = str(uuid.uuid4())
        db.add(DataSource(
            id=ids["source_id"], tenant_id=tenant_id,
            name=f"{label} secret source",
            source_type=SourceType.POSTGRES,
            connection_config={"host": "postgres", "database": f"{label}_db",
                               "password": f"{label}-pw"},
            schema_snapshot={}, tags=[],
        ))
        ids["pipeline_id"] = str(uuid.uuid4())
        db.add(Pipeline(
            id=ids["pipeline_id"], tenant_id=tenant_id,
            name=f"{label} secret pipeline", status=PipelineStatus.ACTIVE,
        ))
        ids["incident_id"] = str(uuid.uuid4())
        db.add(Incident(
            id=ids["incident_id"], tenant_id=tenant_id,
            title=f"{label} secret incident",
            severity=IncidentSeverity.HIGH, status=IncidentStatus.OPEN,
        ))
        await db.commit()
    return ids


# ── The role this all rests on ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connection_role_is_not_privileged():
    """The app must not connect as a superuser or BYPASSRLS role.

    This is the single most important assertion in the file. RLS is bypassed
    entirely — policies still listed, still FORCEd, enforcing nothing — for any
    role with `rolsuper` or `rolbypassrls`. If DATABASE_URL is ever pointed back
    at `dataops_user`, every other test here would still pass while the
    protection was gone, so this one guards them.
    """
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT current_user, "
            "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
            "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
        ))).first()
    current_user, is_super, bypasses = row
    assert not is_super, (
        f"App connects as {current_user!r}, which is a SUPERUSER. RLS is "
        f"silently bypassed for superusers and FORCE does not change that."
    )
    assert not bypasses, (
        f"App connects as {current_user!r}, which has BYPASSRLS. Every policy "
        f"in migration b7d419e3f2a8 is inert for this role."
    )


def test_runtime_urls_never_point_at_the_privileged_role():
    """Static guard on config: request-serving and Celery URLs use the app role.

    Complements the live check above — this one fails at the configuration
    layer even if nobody ever opens a connection, and covers the sync URL too,
    which no request path currently uses but could.
    """
    for name in ("DATABASE_URL", "SYNC_DATABASE_URL"):
        url = getattr(settings, name)
        assert "dataops_app" in url, f"{name} must connect as dataops_app, got: {url.split('@')[-1]}"
        assert "dataops_user" not in url, (
            f"{name} points at the privileged role dataops_user. Migrations and "
            f"maintenance scripts use ADMIN_DATABASE_URL for that; a request or "
            f"Celery path must never bypass RLS."
        )
    # And the privileged URL must still exist and be distinct, or migrations break.
    assert "dataops_user" in settings.ADMIN_DATABASE_URL


# ── Task 6: cross-tenant access across 3 resource types ──────────────────────

@pytest.mark.asyncio
async def test_tenant_a_cannot_read_tenant_b_resources_by_known_id():
    """Tenant A, holding B's real IDs, can read none of them.

    The queries carry NO tenant predicate — they ask for a specific primary key
    the attacker already knows. Only RLS stands between A and B's rows here.
    """
    a = await _make_tenant_with_resources("alpha")
    b = await _make_tenant_with_resources("bravo")

    async with tenant_session(a["tenant_id"]) as db:
        for table, key in (("data_sources", "source_id"),
                           ("pipelines", "pipeline_id"),
                           ("incidents", "incident_id")):
            own = (await db.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :i"), {"i": a[key]}
            )).scalar()
            assert own == 1, f"tenant A cannot see its OWN {table} row — RLS too strict"

            leaked = (await db.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :i"), {"i": b[key]}
            )).scalar()
            assert leaked == 0, (
                f"CROSS-TENANT LEAK: tenant A read tenant B's {table} row by id "
                f"with no tenant filter in the query. RLS is not enforcing."
            )


@pytest.mark.asyncio
async def test_tenant_a_cannot_update_tenant_b_resources():
    """An UPDATE targeting B's row from A's context must affect zero rows.

    RLS makes the row invisible rather than raising, so the tell is the affected
    row count — and, more importantly, that B's data is unchanged afterwards.
    """
    a = await _make_tenant_with_resources("charlie")
    b = await _make_tenant_with_resources("delta")

    async with tenant_session(a["tenant_id"]) as db:
        for table, key, column, value in (
            ("data_sources", "source_id", "name", "pwned-source"),
            ("pipelines", "pipeline_id", "name", "pwned-pipeline"),
            ("incidents", "incident_id", "title", "pwned-incident"),
        ):
            result = await db.execute(
                text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),
                {"v": value, "i": b[key]},
            )
            assert result.rowcount == 0, (
                f"CROSS-TENANT WRITE: tenant A updated {result.rowcount} row(s) "
                f"of tenant B's {table}."
            )
        await db.commit()

    # Verify from B's own side that nothing was actually altered.
    async with tenant_session(b["tenant_id"]) as db:
        for table, key, column in (("data_sources", "source_id", "name"),
                                   ("pipelines", "pipeline_id", "name"),
                                   ("incidents", "incident_id", "title")):
            actual = (await db.execute(
                text(f"SELECT {column} FROM {table} WHERE id = :i"), {"i": b[key]}
            )).scalar()
            assert not actual.startswith("pwned-"), (
                f"tenant B's {table}.{column} was modified by tenant A: {actual!r}"
            )


@pytest.mark.asyncio
async def test_tenant_a_cannot_delete_tenant_b_resources():
    a = await _make_tenant_with_resources("echo")
    b = await _make_tenant_with_resources("foxtrot")

    async with tenant_session(a["tenant_id"]) as db:
        for table, key in (("incidents", "incident_id"),
                           ("pipelines", "pipeline_id"),
                           ("data_sources", "source_id")):
            result = await db.execute(
                text(f"DELETE FROM {table} WHERE id = :i"), {"i": b[key]}
            )
            assert result.rowcount == 0, (
                f"CROSS-TENANT DELETE: tenant A deleted {result.rowcount} row(s) "
                f"from tenant B's {table}."
            )
        await db.commit()

    async with tenant_session(b["tenant_id"]) as db:
        for table, key in (("data_sources", "source_id"),
                           ("pipelines", "pipeline_id"),
                           ("incidents", "incident_id")):
            still_there = (await db.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :i"), {"i": b[key]}
            )).scalar()
            assert still_there == 1, f"tenant B's {table} row was deleted by tenant A"


@pytest.mark.asyncio
async def test_tenant_a_cannot_insert_rows_owned_by_tenant_b():
    """Forging a row *into* another tenant is blocked by the policy's WITH CHECK.

    The USING clause hides other tenants' rows; only WITH CHECK stops A from
    manufacturing new ones attributed to B. Without it, an attacker could plant
    data in a victim tenant even while unable to read any.
    """
    a = await _make_tenant_with_resources("golf")
    b = await _make_tenant_with_resources("hotel")

    async with tenant_session(a["tenant_id"]) as db:
        with pytest.raises(Exception) as excinfo:
            await db.execute(
                text("INSERT INTO pipelines (id, tenant_id, name, status) "
                     "VALUES (:id, :tid, 'forged', 'ACTIVE')"),
                {"id": str(uuid.uuid4()), "tid": b["tenant_id"]},
            )
            await db.commit()
        assert "row-level security" in str(excinfo.value).lower()


# ── Task 7: the DB blocks it, not the application ────────────────────────────

@pytest.mark.asyncio
async def test_rls_blocks_even_a_query_with_no_tenant_filter_at_all():
    """The load-bearing proof that enforcement is in the database.

    An unfiltered `SELECT * FROM data_sources` is exactly the bug this whole
    item exists to defend against — a query where someone forgot the
    `WHERE tenant_id = ...` clause. Under the old convention it returned every
    tenant's rows. It must now return only the caller's, with no help from the
    application layer, because there is no application layer in this query.
    """
    a = await _make_tenant_with_resources("india")
    b = await _make_tenant_with_resources("juliet")

    async with tenant_session(a["tenant_id"]) as db:
        rows = (await db.execute(
            text("SELECT tenant_id FROM data_sources")
        )).fetchall()

    seen = {r[0] for r in rows}
    assert seen, "expected at least tenant A's own source to be visible"
    assert seen == {a["tenant_id"]}, (
        f"An unfiltered SELECT returned {len(seen)} distinct tenant_ids. RLS is "
        f"not confining this session; a forgotten WHERE clause would leak."
    )
    assert b["tenant_id"] not in seen


@pytest.mark.asyncio
async def test_session_without_any_tenant_context_sees_nothing():
    """Fail closed: no context means no rows, not all rows.

    `current_setting('app.current_tenant_id', true)` returns NULL when unset,
    which matches no row (tenant_id is NOT NULL everywhere). The alternative —
    erroring — would turn every unscoped query into a 500; the alternative that
    matters more — returning everything — is the bug itself.
    """
    await _make_tenant_with_resources("kilo")

    async with AsyncSessionLocal() as db:  # deliberately NOT tenant_session
        for table in ("data_sources", "pipelines", "incidents", "tasks", "users"):
            visible = (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            if table == "users":
                # users carries the deliberate pre_auth_read policy so that
                # login can find an account before a tenant is known — see
                # migration b7d419e3f2a8. Reads are open here BY DESIGN.
                continue
            assert visible == 0, (
                f"A session with no tenant context saw {visible} row(s) in "
                f"{table}. RLS must fail closed."
            )


@pytest.mark.asyncio
async def test_pre_auth_tables_allow_read_but_not_cross_tenant_write():
    """The users/team_invites exception is scoped to reads only.

    Login genuinely needs to read `users` across tenants. It must not follow
    that a session can *write* into another tenant's user list.
    """
    a = await _make_tenant_with_resources("lima")
    b = await _make_tenant_with_resources("mike")

    async with tenant_session(a["tenant_id"]) as db:
        with pytest.raises(Exception) as excinfo:
            await db.execute(
                text("INSERT INTO users (id, tenant_id, email, role, is_active) "
                     "VALUES (:id, :tid, :em, 'owner', true)"),
                {"id": str(uuid.uuid4()), "tid": b["tenant_id"],
                 "em": f"forged-{uuid.uuid4().hex[:8]}@example.com"},
            )
            await db.commit()
        assert "row-level security" in str(excinfo.value).lower()
