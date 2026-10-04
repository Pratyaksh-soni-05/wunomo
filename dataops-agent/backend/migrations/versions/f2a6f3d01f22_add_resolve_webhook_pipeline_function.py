"""add_resolve_webhook_pipeline_function

Revision ID: f2a6f3d01f22
Revises: 41dec24849f9
Create Date: 2026-10-04 12:00:00.000000

Security Master Ranking Item #16 follow-up: resolve_pipeline_for_webhook()
previously opened a non-pooled sync connection as ADMIN_DATABASE_URL
(dataops_user -- superuser, BYPASSRLS) directly inside the webhook's
unauthenticated request path. That violates Item #2's own rule (no
BYPASSRLS role on any request-serving path) -- the admin role is
legitimately used elsewhere (services/audit_anchor.py), but that is a
once-daily beat job, not a request path a stranger can hit.

Same mechanism migration b7d419e3f2a8 already established for exactly this
"a stranger-reachable path legitimately needs to see across tenants, by
exactly two columns, before any tenant context exists" shape -- that
migration's tenant_registry view runs with its owner's (dataops_user)
privileges because it has no security_invoker, so dataops_app (granted
only SELECT on the view, nothing on the underlying tenants table) reads
past the tenants RLS policy without ever holding BYPASSRLS itself. A
function with SECURITY DEFINER is the same idea for a parameterized,
single-row lookup a view can't express cleanly.

dataops_app gets EXECUTE on this function and nothing else -- it still
cannot SELECT pipelines directly for a tenant_id that isn't its own
request's (RLS still applies to every ordinary query the webhook handler
runs afterward, through the normal pooled async session). PUBLIC gets
nothing.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f2a6f3d01f22'
down_revision: Union[str, None] = '41dec24849f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "dataops_app"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE FUNCTION resolve_webhook_pipeline(p_id VARCHAR)
        RETURNS TABLE(tenant_id VARCHAR, webhook_secret JSON)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT tenant_id, webhook_secret FROM pipelines WHERE id = p_id
        $$
    """))
    conn.execute(sa.text("REVOKE ALL ON FUNCTION resolve_webhook_pipeline(VARCHAR) FROM PUBLIC"))
    conn.execute(sa.text(f"GRANT EXECUTE ON FUNCTION resolve_webhook_pipeline(VARCHAR) TO {APP_ROLE}"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP FUNCTION IF EXISTS resolve_webhook_pipeline(VARCHAR)"))
