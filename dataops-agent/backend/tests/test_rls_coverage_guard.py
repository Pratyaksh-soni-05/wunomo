"""Standing guard test (Integration Phase 5, per GOTCHAS' own overdue note):
every table carrying a `tenant_id` column must have Row-Level Security
ENABLEd, FORCEd, and at least one real policy attached.

This is a structural safety net, not a substitute for the live,
adversarial verification this whole integration pass has relied on
(Phase 3's tests, C4, the Celery sweep) -- it catches the shape of the
mistake (RLS never turned on for a table that needs it) instantly and
cheaply, on every test run, rather than only when someone happens to
seed real cross-tenant data and notice a leak. It cannot tell a correct
policy from a wrong one; live verification is still what proves the
predicate itself is right.

Introspects pg_catalog directly via ADMIN_DATABASE_URL (metadata reads,
same convention test_schema_drift.py already uses for schema
introspection) -- not the app role, and not because RLS would block it
(pg_catalog is never RLS-protected), just consistency with how this
codebase does cross-cutting introspection.
"""
from sqlalchemy import create_engine, text

from config import settings

# Tables that legitimately carry a tenant_id column but are NOT scoped by
# the standard `tenant_id = current_setting(...)` policy -- both are still
# ENABLE + FORCE + a real policy, just an intentionally open one, per
# migration b7d419e3f2a8's own extensive comment on each:
#   - user_workspace_preferences: keyed by email, not tenant; one row per
#     PERSON, and tenant_id changes as they switch workspaces, so no
#     single tenant-scoped predicate can hold it. Policy: unconditional.
#   - email_login_codes has no tenant_id column at all (never reaches this
#     guard's table set), left here only as a reminder it was considered.
# This guard only checks that a policy EXISTS, not what it says, so both
# pass without a special case -- named here for a human reading this file,
# not because the query needs the name.
KNOWN_INTENTIONALLY_OPEN_POLICY_TABLES = {"user_workspace_preferences"}


def test_every_tenant_id_table_has_rls_enabled_forced_and_policied():
    engine = create_engine(settings.ADMIN_DATABASE_URL)
    try:
        with engine.connect() as conn:
            tables_with_tenant_id = [
                row[0] for row in conn.execute(text("""
                    SELECT DISTINCT c.table_name
                    FROM information_schema.columns c
                    JOIN information_schema.tables t
                        ON t.table_name = c.table_name AND t.table_schema = c.table_schema
                    WHERE c.table_schema = 'public'
                      AND c.column_name = 'tenant_id'
                      AND t.table_type = 'BASE TABLE'
                    ORDER BY c.table_name
                """)).fetchall()
            ]
            assert len(tables_with_tenant_id) >= 25, (
                f"Expected at least 25 tenant_id-bearing tables (24 original + "
                f"the Wunomo Projects direct-tenant tables), found "
                f"{len(tables_with_tenant_id)}: {tables_with_tenant_id}. "
                f"A number this low means the introspection query itself is "
                f"broken, not that coverage improved -- check it before trusting "
                f"a 'pass' below."
            )

            violations = []
            for table in tables_with_tenant_id:
                rls_row = conn.execute(text("""
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = :table AND relnamespace = 'public'::regnamespace
                """), {"table": table}).fetchone()
                if rls_row is None:
                    violations.append(f"{table}: not found in pg_class (should be unreachable)")
                    continue
                enabled, forced = rls_row
                if not enabled:
                    violations.append(f"{table}: ROW LEVEL SECURITY not ENABLEd")
                if not forced:
                    violations.append(f"{table}: ROW LEVEL SECURITY not FORCEd (table-owner bypass open)")

                policy_count = conn.execute(text("""
                    SELECT count(*) FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = :table
                """), {"table": table}).scalar()
                if policy_count == 0:
                    violations.append(f"{table}: ENABLEd/FORCEd but zero policies attached -- blocks everything")

            assert not violations, (
                "Table(s) with a tenant_id column missing RLS coverage:\n  "
                + "\n  ".join(violations)
            )
    finally:
        engine.dispose()


def test_known_open_policy_tables_are_still_enabled_and_forced():
    """The one documented exception (user_workspace_preferences) must stay
    ENABLE + FORCE'd with a real (even if unconditional) policy -- this
    guard would otherwise treat "RLS quietly turned off" and "RLS
    correctly left open by design" as the same thing. Confirms the
    exception is deliberate and still in place, not the absence of a
    check."""
    engine = create_engine(settings.ADMIN_DATABASE_URL)
    try:
        with engine.connect() as conn:
            for table in KNOWN_INTENTIONALLY_OPEN_POLICY_TABLES:
                rls_row = conn.execute(text("""
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = :table AND relnamespace = 'public'::regnamespace
                """), {"table": table}).fetchone()
                assert rls_row is not None, f"{table} not found"
                assert rls_row[0] is True, f"{table}: RLS not enabled"
                assert rls_row[1] is True, f"{table}: RLS not forced"
                policy_count = conn.execute(text("""
                    SELECT count(*) FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = :table
                """), {"table": table}).scalar()
                assert policy_count > 0, f"{table}: no policy attached"
    finally:
        engine.dispose()
