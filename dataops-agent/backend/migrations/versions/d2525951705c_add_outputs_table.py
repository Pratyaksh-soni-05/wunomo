"""add_outputs_table

Revision ID: d2525951705c
Revises: dd460a06e6ce
Create Date: 2026-10-04 18:07:54.592428

Blueprint §11 (Outputs): the one model unblocking §11 itself,
LiveWorkPanel's Files tab, §7.3.D's output card (trust score), and
"How this was made" (provenance). Backend only this pass.

RLS (ENABLE + FORCE + tenant_isolation + GRANT) in this SAME migration,
not a follow-up one -- test_rls_coverage_guard.py requires it, and the
split-then-follow-up shape (handoffs' own b2e6f1a83c47, RLS added later
in aa4569de4785) is exactly the gap that guard test exists to close
going forward. Pattern copied from e5a9c3d7b2f1_add_sso.py (sso_domains),
the most recent single-migration table+RLS precedent: GRANT before
ENABLE (a new table with RLS on but no GRANT fails every query with
"permission denied", not an obviously-RLS-shaped error -- Items #2, #9,
#14 in docs/context/GOTCHAS.md all independently hit this).

tenant_id is a REAL FK here (see the model's own docstring,
models/all_models.py) -- matching Project/AgentInstance/Handoff's
already-established newer-table convention, not a deviation.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd2525951705c'
down_revision: Union[str, None] = 'dd460a06e6ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "dataops_app"


def upgrade() -> None:
    op.create_table('outputs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('task_id', sa.String(), nullable=False),
    sa.Column('agent_instance_id', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('content_type', sa.String(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('storage_ref', sa.String(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('supersedes_output_id', sa.String(), nullable=True),
    sa.Column('trust_score', sa.Float(), nullable=True),
    sa.Column('trust_checks', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_instance_id'], ['agent_instances.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['supersedes_output_id'], ['outputs.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outputs_agent_instance_id'), 'outputs', ['agent_instance_id'], unique=False)
    op.create_index(op.f('ix_outputs_project_id'), 'outputs', ['project_id'], unique=False)
    op.create_index(op.f('ix_outputs_task_id'), 'outputs', ['task_id'], unique=False)
    op.create_index(op.f('ix_outputs_tenant_id'), 'outputs', ['tenant_id'], unique=False)

    conn = op.get_bind()
    conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON outputs TO {APP_ROLE}"))
    conn.execute(sa.text("ALTER TABLE outputs ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE outputs FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text("""
        CREATE POLICY tenant_isolation ON outputs
            USING (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::varchar)
    """))


def downgrade() -> None:
    # DROP TABLE cascades away its indexes and policy on its own -- no
    # separate DROP POLICY/DROP INDEX needed first (same minimal shape
    # e5a9c3d7b2f1_add_sso.py's own downgrade uses for sso_domains).
    op.drop_table('outputs')
