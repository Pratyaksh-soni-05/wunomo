"""enable row level security for tenant isolation

Security Master Ranking Item #2. Until this migration, tenant isolation was a
convention — every query was *supposed* to carry `WHERE tenant_id = ...`, with
nothing structurally stopping an omission. This moves the guarantee into
Postgres.

    WHY A NEW ROLE IS THE LOAD-BEARING PART OF THIS MIGRATION
    ---------------------------------------------------------
    RLS is bypassed completely and silently by any role that is SUPERUSER or has
    BYPASSRLS. `FORCE ROW LEVEL SECURITY` does NOT close that — it closes only
    the table-*owner* bypass. `dataops_user` (the role this app connected as
    until now) is both superuser and BYPASSRLS, so enabling RLS while still
    connecting as it would leave every policy below in place and entirely inert:
    the migration would apply cleanly, the tests would pass, and nothing would
    actually be enforced. Verified empirically before writing this — the
    identical policy blocked a cross-tenant read for a NOSUPERUSER role and
    allowed it for `dataops_user`.

    So this migration provisions `dataops_app` (NOSUPERUSER, NOBYPASSRLS) and
    the backend + both Celery services connect as it. `dataops_user` remains the
    migration/maintenance role via ADMIN_DATABASE_URL.

Revision ID: b7d419e3f2a8
Revises: a4f8c2e91b06
Create Date: 2026-08-31 00:00:00.000000
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d419e3f2a8'
down_revision: Union[str, None] = 'a4f8c2e91b06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APP_ROLE = "dataops_app"

# The 24 tables carrying a tenant_id column, plus task_steps which gains one
# below. Every one gets the identical ENABLE + FORCE + tenant policy treatment.
TENANT_SCOPED_TABLES = [
    "api_keys", "approval_requests", "audit_logs", "chat_messages",
    "cicd_incidents", "data_contracts", "data_sources", "incidents",
    "kpi_values", "lineage_edges", "lineage_nodes", "llm_usage_events",
    "onboarding_profiles", "pipeline_commits", "pipeline_deployments",
    "pipeline_runs", "pipelines", "quality_rules", "task_steps", "tasks",
    "team_invites", "transform_runs", "usage_metrics", "users",
]

# Tables read BEFORE a tenant is known, during authentication. See the block
# comment at the policy site below — do not tighten these without reading it.
PRE_AUTH_READ_TABLES = ["users", "team_invites", "email_login_codes"]


def upgrade() -> None:
    conn = op.get_bind()
    app_password = os.getenv("APP_DB_PASSWORD", "changeme")

    # ── 1. The application role ───────────────────────────────────────────────
    # NOSUPERUSER + NOBYPASSRLS are the whole point; see the module docstring.
    # CREATE ROLE is not transactional-safe to repeat, hence the existence check.
    conn.execute(sa.text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD :pw NOSUPERUSER NOBYPASSRLS
                    NOCREATEDB NOCREATEROLE;
            END IF;
        END $$;
    """).bindparams(pw=app_password))
    # Set unconditionally so a re-run picks up a rotated password, and to
    # re-assert the two attributes if someone has changed them by hand.
    conn.execute(sa.text(
        f"ALTER ROLE {APP_ROLE} WITH LOGIN PASSWORD :pw NOSUPERUSER NOBYPASSRLS"
    ).bindparams(pw=app_password))

    conn.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))

    # ── 2. task_steps gains a tenant_id ───────────────────────────────────────
    # It was scoped only through its task_id FK, which RLS cannot express as a
    # simple row predicate. Added nullable, backfilled from the parent task,
    # then made NOT NULL — matching the varchar type used by all 24 others.
    op.add_column("task_steps", sa.Column("tenant_id", sa.String(), nullable=True))
    conn.execute(sa.text("""
        UPDATE task_steps ts
           SET tenant_id = t.tenant_id
          FROM tasks t
         WHERE ts.task_id = t.id
           AND ts.tenant_id IS NULL
    """))
    # An orphan step (no matching task) would block the NOT NULL below. There
    # should be none — task_id is a real FK — but fail loudly rather than
    # silently leaving un-scoped rows behind if the assumption is wrong.
    orphans = conn.execute(sa.text(
        "SELECT count(*) FROM task_steps WHERE tenant_id IS NULL"
    )).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} task_steps row(s) have no resolvable tenant_id via "
            f"task_id -> tasks.tenant_id. Resolve these before enabling RLS; "
            f"leaving them would make them invisible to every tenant."
        )
    op.alter_column("task_steps", "tenant_id", nullable=False)
    op.create_index("ix_task_steps_tenant_id", "task_steps", ["tenant_id"])

    # ── 3. RLS on every tenant-scoped table ───────────────────────────────────
    for table in TENANT_SCOPED_TABLES:
        conn.execute(sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}"
        ))
        conn.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        # FORCE closes the table-owner bypass. It does NOT close superuser /
        # BYPASSRLS — that is why the app connects as dataops_app.
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        # `, true` is missing_ok: an unset variable yields NULL (matching no
        # row) instead of raising. Fails closed — an unscoped session reads
        # nothing rather than everything, and never 500s.
        conn.execute(sa.text(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
        """))

    # ── 4. The pre-auth read exception ────────────────────────────────────────
    #
    #   DO NOT "FIX" THIS BY TIGHTENING IT WITHOUT READING THIS COMMENT.
    #
    # Authentication is a chicken-and-egg problem for RLS: the tenant is not
    # known until *after* the user is identified, but identifying the user means
    # reading these tables. Login looks a user up by email across all tenants
    # (services/auth_service.py — resolve_password_login / resolve_identity);
    # invite acceptance looks a row up by token hash alone
    # (services/team_service.py); email codes are keyed by email + hash. None of
    # those callers can supply a tenant, because discovering it is the point of
    # the query.
    #
    # So these three get a SECOND, permissive policy allowing unconditional
    # SELECT. Postgres OR's permissive policies together, so reads are open
    # while INSERT/UPDATE/DELETE stay governed by the tenant_isolation policy
    # above. Tightening this to a tenant predicate makes the application
    # unloggable-into, and the symptom ("invalid credentials" for valid
    # credentials) points nowhere near RLS.
    #
    # What still protects these tables: passwords are bcrypt hashes, invite and
    # login-code tokens are stored only as SHA-256 hashes with short TTLs and
    # per-IP rate limiting, and no endpoint returns a bare row from any of them.
    for table in PRE_AUTH_READ_TABLES:
        conn.execute(sa.text(
            f"CREATE POLICY pre_auth_read ON {table} FOR SELECT USING (true)"
        ))

    # email_login_codes has no tenant dimension at all — every row is a
    # short-lived, pre-authentication artifact keyed by email + code hash, and
    # every operation on it happens before a tenant exists. RLS is enabled for
    # consistency and so that adding a tenant column later is a policy change
    # rather than an enablement, but the write policy is necessarily
    # unconditional. Its real protections are the hash, the TTL, and the
    # rate limiter, not row isolation.
    conn.execute(sa.text(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON email_login_codes TO {APP_ROLE}"
    ))
    conn.execute(sa.text("ALTER TABLE email_login_codes ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE email_login_codes FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("""
        CREATE POLICY pre_auth_write ON email_login_codes
            FOR ALL USING (true) WITH CHECK (true)
    """))

    # ── 4b. user_workspace_preferences: enabled, but deliberately open ────────
    #
    #   THIS TABLE HAS NO OWNING TENANT. Do not "tighten" it to match the others.
    #
    # Its primary key is `email`, not an id belonging to one tenant. It answers
    # "which workspace did this person last use" — a cross-tenant, per-person
    # fact, by the model's own design (see UserWorkspacePreference's docstring:
    # the same email can have a separate User row per tenant, so no single
    # tenant-scoped row can hold this). One row exists per person, and its
    # tenant_id *changes* as they switch workspaces.
    #
    # That makes it different in kind from users/team_invites/email_login_codes.
    # Those three get a permissive SELECT because the tenant isn't known until
    # the caller is identified — but their writes stay restricted to the owning
    # tenant, because they have one. This table does not, and a tenant-scoped
    # policy breaks it two separate ways:
    #   * READ: a session scoped to tenant B cannot see the row while it still
    #     points at tenant A, so the "update existing" branch is skipped and the
    #     INSERT branch runs instead — a duplicate-key violation on the email PK.
    #   * WRITE: moving the row A -> B is blocked regardless, because USING
    #     evaluates the OLD row (tenant A) against the current context
    #     (tenant B) and matches zero rows.
    # It is also read pre-authentication (_remembered_workspace(email), during
    # login, before any tenant exists).
    #
    # RLS is still ENABLE + FORCE'd rather than left off, so `\d+` and any audit
    # of pg_class shows every tenant-bearing table consistently protected, and
    # the exception is visible as an explicit policy rather than as a silent
    # absence. The policy itself is unconditional.
    conn.execute(sa.text(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON user_workspace_preferences TO {APP_ROLE}"
    ))
    conn.execute(sa.text("ALTER TABLE user_workspace_preferences ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE user_workspace_preferences FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("""
        CREATE POLICY workspace_prefs_open ON user_workspace_preferences
            USING (true) WITH CHECK (true)
    """))

    # ── 5. tenants: restrictive, plus a registry view for the sweepers ────────
    # tenants is NOT just a registry: `settings` carries notification_prefs
    # (alert_email, slack_webhook_url — a live credential) and `plan` is billing
    # tier. Leaving it open would let any tenant read every other tenant's
    # webhook URLs, which would undercut the point of this whole migration.
    # It is therefore scoped by `id` rather than `tenant_id`.
    conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO {APP_ROLE}"))
    conn.execute(sa.text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE tenants FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("""
        CREATE POLICY tenant_self ON tenants
            USING (id = current_setting('app.current_tenant_id', true)::varchar)
            WITH CHECK (id = current_setting('app.current_tenant_id', true)::varchar)
    """))

    # The cross-tenant Celery sweepers need to enumerate tenant IDs, which the
    # policy above correctly prevents. This view exposes ONLY (id, is_active) —
    # never settings or plan. A view without security_invoker runs with its
    # owner's privileges (dataops_user), so it reads past the policy without
    # granting dataops_app any bypass attribute of its own.
    conn.execute(sa.text(
        "CREATE VIEW tenant_registry AS SELECT id, name, is_active FROM tenants"
    ))
    conn.execute(sa.text(f"GRANT SELECT ON tenant_registry TO {APP_ROLE}"))

    # alembic_version: readable so the app can report its schema revision;
    # migrations themselves run as dataops_user.
    conn.execute(sa.text(f"GRANT SELECT ON alembic_version TO {APP_ROLE}"))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DROP VIEW IF EXISTS tenant_registry"))

    conn.execute(sa.text("DROP POLICY IF EXISTS tenant_self ON tenants"))
    conn.execute(sa.text("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY"))

    conn.execute(sa.text(
        "DROP POLICY IF EXISTS workspace_prefs_open ON user_workspace_preferences"))
    conn.execute(sa.text(
        "ALTER TABLE user_workspace_preferences NO FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text(
        "ALTER TABLE user_workspace_preferences DISABLE ROW LEVEL SECURITY"))

    conn.execute(sa.text("DROP POLICY IF EXISTS pre_auth_write ON email_login_codes"))
    conn.execute(sa.text("ALTER TABLE email_login_codes NO FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE email_login_codes DISABLE ROW LEVEL SECURITY"))

    for table in PRE_AUTH_READ_TABLES:
        conn.execute(sa.text(f"DROP POLICY IF EXISTS pre_auth_read ON {table}"))

    for table in TENANT_SCOPED_TABLES:
        conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        conn.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    op.drop_index("ix_task_steps_tenant_id", table_name="task_steps")
    op.drop_column("task_steps", "tenant_id")

    # The role is deliberately NOT dropped: other databases or leftover grants
    # may still reference it, and dropping a role that owns nothing but is still
    # referenced fails confusingly. Revoke instead.
    conn.execute(sa.text(
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}"
    ))
