import os
os.environ["APP_ENV"] = "test"  # MUST be before all project imports

import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from contextlib import asynccontextmanager
from database import AsyncSessionLocal


@pytest_asyncio.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def client():
    from main import app  # imported AFTER env var is set
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# Item 47: services/auth_service.py's email-code rate limiter writes real,
# TTL'd Redis state (otp:hourly:{email}, otp:ip:{ip}, otp:cooldown:{email},
# otp:lockout:{email}, otp:exhausted_streak:{email}) that outlives any
# single test. Every test client request goes through the same source
# "IP" (the ASGI test transport), so otp:ip:{ip} in particular accumulates
# across every test in the run regardless of which file or email is
# involved - a sufficiently broad pytest selection can exhaust
# MAX_REQUESTS_PER_IP_PER_HOUR purely from the suite's own combined
# request volume, spuriously failing whichever email-code test happens to
# run once the shared budget is gone (this is exactly what made
# test_email_code_auth.py's rate-limit tests order/selection-dependent -
# see WALKTHROUGH_FINDINGS_2026-08.md item 47). Autouse + function-scoped:
# every test starts with a guaranteed-clean rate-limit slate, so the
# result no longer depends on what ran before it or how broad -k was.
@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limit_state():
    """Clears BOTH Redis-backed limiters before every test.

    `otp:*` is auth_service's email-code limiter (the original reason this
    fixture exists). `rl:*` is services/rate_limit.py's per-minute burst
    limiter, added 2026-09-01 — it has exactly the same problem and would
    otherwise reintroduce the exact order-dependence this fixture was written
    to remove: every test client shares one source "IP", so the per-IP buckets
    accumulate across every test in the run, and a later test fails with 429
    for reasons that have nothing to do with its own logic. Per-tenant buckets
    are keyed by a fresh uuid per test and would not collide, but they are
    cleared too rather than relying on that.
    """
    import services.auth_service as auth_service
    redis = auth_service._redis()
    for pattern in ("otp:*", "rl:*", "revoked:*"):
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
    yield

# ── RLS-aware test sessions ──────────────────────────────────────────────────
# Every tenant-scoped table is protected by Row-Level Security (migration
# b7d419e3f2a8), and the policy reads `app.current_tenant_id`, set per
# transaction from a ContextVar. In the running app that ContextVar is
# populated by TenantContextMiddleware (HTTP) or the Celery task wrappers
# (background) — neither of which exists when a test seeds rows directly.
#
# So a bare `AsyncSessionLocal()` in a test has no tenant, and RLS correctly
# refuses the write ("new row violates row-level security policy"). Use
# `services.tenant_context.tenant_session(tenant_id)` instead: it opens a
# session already inside that tenant's context, which is the same path
# production takes. It lives in services/ rather than here because conftest is
# a pytest plugin, not an importable module.
#
# Deliberately NOT solved by pointing the test suite at the superuser role.
# That would make everything pass while proving nothing — RLS would be bypassed
# in every test, and a regression dropping tenant context would go unnoticed.
# test_rls_cross_tenant.py depends on the suite genuinely running under RLS.


# ── Tenant teardown ──────────────────────────────────────────────────────────
# Until now this suite had NO database teardown at all: the fixtures above
# clear Redis and nothing clears Postgres. Every test that registers a tenant
# left it behind permanently, and the cost compounded — `tenants` went
# 4,086 → 6,499 → 10,689 across a few sessions, the freshness sweep is
# per-tenant by necessity under RLS, and the full suite went from 41 minutes
# to 2:38:43. See GOTCHAS #22.
#
# WHY NOT A ROLLBACK-PER-TEST FIXTURE, THE USUAL ANSWER
#
# Tests create tenants by calling the real `POST /auth/register` through the
# ASGI app. That handler opens its own `AsyncSessionLocal()` and commits, on
# its own connection — a transaction opened on the test's side cannot wrap it.
# Making that possible means routing every session through an overridable
# dependency, and the app instantiates `AsyncSessionLocal()` directly at 161
# call sites against 13 uses of `Depends(get_db)`. It would also break
# test_rls_cross_tenant.py, which genuinely needs committed cross-session data.
# So: explicit deletion, not rollback.
#
# WHAT IS DELETED, AND WHY IT IS SAFE
#
# Only tenants that did not exist when the session started. The id set is
# snapshotted up front and diffed at the end, so this deletes exactly what the
# run created — no name matching, no `created_at` window (which would depend on
# app/DB clock agreement), and no possibility of touching pre-existing data.
#
# Runs as ADMIN_DATABASE_URL. `tenants` is RLS-protected, so enumerating and
# deleting across many tenants from the app role would need a per-tenant
# context switch each time; this is maintenance work, which is exactly what
# CLAUDE.md designates that role for. It never runs inside a test.
# Deleting only by `tenant_id` is NOT sufficient, and assuming it was cost a
# failed first attempt at the backlog purge: `DELETE FROM pipelines` raised
# `pipeline_runs_pipeline_id_fkey` because a child row can reference a parent
# in the batch while carrying a tenant_id outside it. Every child is therefore
# deleted by its FK to the parent set AS WELL AS by tenant_id. The FK columns
# below were read out of information_schema, not guessed.
# Parent id sets, computed IN DEPENDENCY ORDER and with exactly the same
# predicates the deletes below use. Getting this wrong is the second bug this
# routine had: `pipelines` is deleted by `tenant_id OR source_id = ANY(:S)`,
# which reaches pipelines owned by a DIFFERENT tenant that happen to use one of
# our data sources — so computing :P as "pipelines of these tenants" left those
# pipelines' runs undeleted and `DELETE FROM pipelines` hit
# pipeline_runs_pipeline_id_fkey all over again. Each set must be as wide as
# the delete that consumes it, hence S before P, P before R/C, C before D.
_PARENT_QUERIES = [
    ("S", "SELECT id FROM data_sources WHERE tenant_id = ANY(:ids)"),
    ("P", "SELECT id FROM pipelines WHERE tenant_id = ANY(:ids) OR source_id = ANY(:S)"),
    ("R", "SELECT id FROM pipeline_runs WHERE tenant_id = ANY(:ids) OR pipeline_id = ANY(:P)"),
    ("C", "SELECT id FROM pipeline_commits WHERE tenant_id = ANY(:ids) OR pipeline_id = ANY(:P)"),
    ("D", "SELECT id FROM pipeline_deployments WHERE tenant_id = ANY(:ids)"
          " OR pipeline_id = ANY(:P) OR commit_id = ANY(:C)"),
    ("T", "SELECT id FROM tasks WHERE tenant_id = ANY(:ids)"),
    ("A", "SELECT id FROM approval_requests WHERE tenant_id = ANY(:ids)"),
    ("N", "SELECT id FROM lineage_nodes WHERE tenant_id = ANY(:ids)"),
]

# (table, extra WHERE clause using parent-id bind params). Children first;
# order derived from the live FK graph.
DELETION_PLAN = [
    ("lineage_edges", "upstream_id = ANY(:N) OR downstream_id = ANY(:N)"),
    ("lineage_nodes", None),
    ("data_contracts", "producer_source_id = ANY(:S)"),
    ("cicd_incidents", "pipeline_id = ANY(:P) OR deployment_id = ANY(:D)"),
    ("pipeline_deployments", "pipeline_id = ANY(:P) OR commit_id = ANY(:C)"),
    ("pipeline_commits", "pipeline_id = ANY(:P)"),
    ("incidents", "pipeline_id = ANY(:P) OR run_id = ANY(:R)"),
    ("pipeline_runs", "pipeline_id = ANY(:P)"),
    ("quality_rules", "pipeline_id = ANY(:P)"),
    ("task_steps", "task_id = ANY(:T) OR approval_request_id = ANY(:A)"),
    ("tasks", None),
    ("approval_requests", None),
    ("pipelines", "source_id = ANY(:S)"),
    ("data_sources", None),
    # No FK to tenants at all - a bare tenant_id column, so nothing would raise
    # if these were forgotten. They are why this covers 25 tables and not the 7
    # an earlier per-file precedent deleted: an omission leaves silent orphans
    # rather than an error. (160 stranded transform_runs rows already exist
    # from exactly that omission.)
    ("audit_logs", None),
    ("chat_messages", None),
    ("kpi_values", None),
    ("llm_usage_events", None),
    ("transform_runs", None),
    ("usage_metrics", None),
    ("api_keys", None),
    ("onboarding_profiles", None),
    ("team_invites", None),
    ("user_workspace_preferences", None),
    ("users", None),
]


def delete_tenants(conn, tenant_ids):
    """Delete these tenants and everything belonging to them. Returns per-table
    row counts. Caller supplies the transaction."""
    from sqlalchemy import text

    if not tenant_ids:
        return {}
    params = {"ids": list(tenant_ids)}
    for key, q in _PARENT_QUERIES:
        # `or [""]` keeps ANY() valid on an empty set without matching anything.
        params[key] = [r[0] for r in conn.execute(text(q), params)] or [""]

    deleted = {}
    # audit_logs is append-only at the database level (Item #9): a BEFORE
    # UPDATE OR DELETE trigger raises for every role, the superuser included
    # -- measured, not assumed. The ONLY way past it is to disable triggers
    # for the session, which Postgres restricts to superusers; the app role
    # cannot do this. This teardown runs as the maintenance role, deletes
    # whole tenants the run created, and each tenant's audit rows form their
    # own hash chain -- so removing a tenant removes a complete chain and
    # breaks nothing.
    #
    # Session-level SET with a RESET in finally, NOT `SET LOCAL`: the admin
    # engine is created with isolation_level="AUTOCOMMIT", under which
    # engine.begin() opens no real transaction block, and SET LOCAL outside
    # a transaction block is a silent no-op. The first version of this used
    # SET LOCAL and every teardown failed with the trigger's error while a
    # direct call on a transactional engine worked -- that difference was
    # the whole bug.
    conn.execute(text("SET session_replication_role = replica"))
    try:
        for table, extra in DELETION_PLAN:
            where = "tenant_id = ANY(:ids)" + (f" OR {extra}" if extra else "")
            r = conn.execute(text(f"DELETE FROM {table} WHERE {where}"), params)
            if r.rowcount:
                deleted[table] = r.rowcount
        # email_login_codes names the column differently, and tenants goes last.
        r = conn.execute(text("DELETE FROM email_login_codes WHERE intended_tenant_id = ANY(:ids)"), params)
        if r.rowcount:
            deleted["email_login_codes"] = r.rowcount
        r = conn.execute(text("DELETE FROM tenants WHERE id = ANY(:ids)"), params)
        if r.rowcount:
            deleted["tenants"] = r.rowcount
    finally:
        conn.execute(text("RESET session_replication_role"))
    return deleted


@pytest.fixture(scope="session", autouse=True)
def _delete_tenants_created_by_this_run():
    """Deletes every tenant this run created, and nothing else."""
    if os.environ.get("AXIOM_KEEP_TEST_DATA"):
        # Escape hatch for inspecting a failed run's data afterwards.
        yield
        return

    from sqlalchemy import create_engine, text
    from config import settings

    admin = create_engine(settings.ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        before = {r[0] for r in c.execute(text("SELECT id FROM tenants"))}

    try:
        yield
    finally:
        with admin.connect() as c:
            after = {r[0] for r in c.execute(text("SELECT id FROM tenants"))}
        created = list(after - before)
        if not created:
            admin.dispose()
            return

        # One transaction: a partial teardown would leave rows whose parent is
        # gone, which is worse than not running at all.
        #
        # Retried once, for a measured reason. celery_beat runs
        # check_scheduled_pipelines() every 60s, which INSERTs PipelineRun rows
        # for active scheduled pipelines. If it commits one referencing a
        # pipeline in this batch between our pipeline_runs DELETE and our
        # pipelines DELETE, the FK check on the latter sees the new row under
        # READ COMMITTED and raises pipeline_runs_pipeline_id_fkey. That is
        # exactly what made the backlog purge fail intermittently, and it is a
        # race rather than a data problem: the same tenant deletes cleanly on a
        # second attempt. Retrying once closes the window in practice; a
        # failure after that is logged rather than raised, because leaking a
        # few tenants is much better than failing an otherwise-green suite.
        deleted = {}
        for attempt in (1, 2):
            try:
                with admin.begin() as c:
                    deleted = delete_tenants(c, created)
                break
            except Exception as exc:
                if attempt == 2:
                    print(f"\n[teardown] WARNING: could not remove "
                          f"{len(created)} tenant(s): {type(exc).__name__}. "
                          f"They will be cleaned up by a later run.")
                    admin.dispose()
                    return
        admin.dispose()
        print(f"\n[teardown] removed {len(created)} tenant(s) created by this run: "
              f"{deleted if deleted else 'no rows'}")
