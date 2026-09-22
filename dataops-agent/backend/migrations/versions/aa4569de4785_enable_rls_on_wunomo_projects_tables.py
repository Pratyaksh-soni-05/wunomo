"""enable RLS on Wunomo Projects tables

Revision ID: aa4569de4785
Revises: d89011ced511
Create Date: 2026-09-22 13:36:05.524177

Integration Phase 2, step 5. His branch's 9 new tenant-scoped tables
(agent_instances, agent_sources, projects, project_agents, channels,
channel_users, channel_agents, scheduled_agent_tasks, handoffs) all
postdate master's b7d419e3f2a8 (the migration that enabled RLS via a
hardcoded TENANT_SCOPED_TABLES list) and e5a9c3d7b2f1 (which added
sso_domains the same way) -- so none of them got any RLS coverage at all
until this migration. Never edit either of those two migrations to add
these tables retroactively; a new migration is the only safe way to close
this gap on a chain that's already shipped.

Two shapes, inspected from the real model columns before writing this
(not assumed):

  DIRECT_TENANT_TABLES carry their own tenant_id column and get the exact
  same ENABLE + FORCE + tenant_isolation policy pattern b7d419e3f2a8 uses
  for every other tenant-scoped table.

  JOIN_TABLES (agent_sources, project_agents, channel_users, channel_agents)
  have no tenant_id column at all -- pure FK-only join rows. Their policy
  instead checks that the row's own FK resolves to a parent row the caller
  can already see under ITS OWN tenant_isolation policy (a subquery against
  agent_instances/projects/channels, all three enabled by this same
  migration) -- equivalent to "belongs to my tenant" without a redundant
  tenant_id column to keep in sync.

Every one of the 9 also gets its own GRANT to dataops_app -- the trap
Items #2, #9, and #14 each independently hit and documented in GOTCHAS:
a new table with RLS enabled but no GRANT fails every query with
"permission denied", not an obviously-RLS-shaped error.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'aa4569de4785'
down_revision: Union[str, None] = 'd89011ced511'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "dataops_app"

# Tables with their own tenant_id column.
DIRECT_TENANT_TABLES = [
    "agent_instances", "projects", "channels", "scheduled_agent_tasks", "handoffs",
]

# (table, FK column, parent table) -- join tables scoped only via FK to a
# tenant-scoped parent, no tenant_id column of their own.
JOIN_TABLES = [
    ("agent_sources", "agent_id", "agent_instances"),
    ("project_agents", "project_id", "projects"),
    ("channel_users", "channel_id", "channels"),
    ("channel_agents", "channel_id", "channels"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for table in DIRECT_TENANT_TABLES:
        conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}"))
        conn.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
        """))

    for table, fk_column, parent in JOIN_TABLES:
        conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}"))
        conn.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        # The subquery is itself filtered by `parent`'s own tenant_isolation
        # policy (created above, since DIRECT_TENANT_TABLES runs first) --
        # so this reduces to "does fk_column point at a row I can already
        # see," which is exactly "belongs to my tenant" for a table with no
        # tenant_id column to check directly.
        conn.execute(sa.text(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING ({fk_column} IN (
                    SELECT id FROM {parent}
                    WHERE tenant_id = current_setting('app.current_tenant_id', true)::varchar
                ))
                WITH CHECK ({fk_column} IN (
                    SELECT id FROM {parent}
                    WHERE tenant_id = current_setting('app.current_tenant_id', true)::varchar
                ))
        """))


def downgrade() -> None:
    conn = op.get_bind()
    for table, _fk_column, _parent in reversed(JOIN_TABLES):
        conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        conn.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM {APP_ROLE}"))
    for table in reversed(DIRECT_TENANT_TABLES):
        conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        conn.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM {APP_ROLE}"))
