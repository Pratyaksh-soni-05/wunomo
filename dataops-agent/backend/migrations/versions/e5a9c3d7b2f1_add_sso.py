"""Enterprise SSO (Security Master Ranking Item #14): users.sso_subject and
the pre-auth sso_domains lookup table.

Revision ID: e5a9c3d7b2f1
Revises: d4f8b2c6e1a9
Create Date: 2026-09-20

sso_domains gets the same RLS treatment as every tenant-scoped table
(ENABLE + FORCE + tenant_isolation) PLUS the pre_auth_read SELECT policy
that users/team_invites/email_login_codes carry, for the same reason: the
login page must resolve an email domain to a tenant before any tenant
context exists. Writes stay tenant-scoped.

And the trap Items #2 and #9 both fell into, stated so it is not fallen
into a third time: a new table needs its own GRANT to dataops_app. Without
it every read fails with "permission denied" -- and a pre-auth lookup that
fails reads as "no SSO for this domain", silently.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a9c3d7b2f1"
down_revision = "d4f8b2c6e1a9"
branch_labels = None
depends_on = None

APP_ROLE = "dataops_app"


def upgrade() -> None:
    op.add_column("users", sa.Column("sso_subject", sa.String(255), nullable=True))
    op.create_index("ix_users_sso_subject", "users", ["sso_subject"])

    op.create_table(
        "sso_domains",
        sa.Column("email_domain", sa.String(255), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connection_id", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sso_domains_tenant_id", "sso_domains", ["tenant_id"])

    conn = op.get_bind()
    conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON sso_domains TO {APP_ROLE}"))
    conn.execute(sa.text("ALTER TABLE sso_domains ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE sso_domains FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("""
        CREATE POLICY tenant_isolation ON sso_domains
            USING (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
    """))
    conn.execute(sa.text("CREATE POLICY pre_auth_read ON sso_domains FOR SELECT USING (true)"))


def downgrade() -> None:
    op.drop_table("sso_domains")
    op.drop_index("ix_users_sso_subject", table_name="users")
    op.drop_column("users", "sso_subject")
