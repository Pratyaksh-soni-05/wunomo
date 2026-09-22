"""add_agent_instances

Revision ID: b3f8a1d92c56
Revises: f1a29d6c8e47
Create Date: 2026-09-02 00:00:00.000000

Wunomo Projects Phase 0 (see docs/context/WUNOMO_PROJECTS_PROPOSAL_v2.md) --
schema only, nothing visible changes. agent_instances is the tenant-owned
record an agent becomes instead of a hardcoded singleton; agent_sources is
a real join table (not a JSON column) so scope is enforceable in SQL, not
just checked in Python after the fact. AXIOM's backfill into row one per
tenant is a separate migration (commit 3), not this one -- this migration
only adds the new tables/columns, empty/null until that backfill runs.

Enum labels are the Python member NAMES (uppercase), not .value -- matching
every other enum in this codebase (SQLAlchemy's default Enum(PythonEnumClass)
behavior, already documented in 509a9b8715f2's own migration).

personality/operation_mode reuse the *existing* personalitymode/
operationmode Postgres enum types (created by the original User-table
migration) via postgresql.ENUM(..., create_type=False) -- the same
create_type=False precedent already established in this codebase for the
CI/CD enums (db3efa7d4d82). employee_type/status are new types on this
migration, created normally (create_type defaults to True).

agent_id is nullable everywhere it's added (tasks, chat_messages,
llm_usage_events, audit_logs), since no row can have one until the next
migration's backfill runs. FK-vs-no-FK on each of the four follows that
specific table's own existing convention for its other identity columns,
not a blanket rule: tasks already uses real FKs (tenant_id, user_id), so
agent_id gets one too; chat_messages/llm_usage_events/audit_logs all use
bare, FK-less identity columns (tenant_id has no FK on any of the three)
because they're log/metering-style tables that must never fail an insert
over a referential-integrity check -- agent_id matches that on all three.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b3f8a1d92c56'
down_revision: Union[str, None] = 'f1a29d6c8e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_instances',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('employee_type', sa.Enum('DATAOPS', name='agentemployeetype'), nullable=False),
        sa.Column('personality', postgresql.ENUM(
            'ENGINEER', 'FOUNDER', 'ANALYST', 'AUDITOR', name='personalitymode', create_type=False), nullable=False),
        sa.Column('operation_mode', postgresql.ENUM(
            'ADVISORY', 'ASSISTED', 'AUTONOMOUS', 'AUDIT', name='operationmode', create_type=False), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('standing_instructions', sa.Text(), nullable=True),
        sa.Column('monthly_token_budget', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('ACTIVE', 'OFFBOARDED', name='agentinstancestatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_agent_instances_tenant_name'),
    )
    op.create_index(op.f('ix_agent_instances_tenant_id'), 'agent_instances', ['tenant_id'], unique=False)

    op.create_table('agent_sources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_instances.id'], ),
        sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'source_id', name='uq_agent_sources_agent_source'),
    )
    op.create_index(op.f('ix_agent_sources_agent_id'), 'agent_sources', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_sources_source_id'), 'agent_sources', ['source_id'], unique=False)

    op.add_column('tasks', sa.Column('agent_id', sa.String(), nullable=True))
    op.create_foreign_key('fk_tasks_agent_id_agent_instances', 'tasks', 'agent_instances', ['agent_id'], ['id'])

    op.add_column('chat_messages', sa.Column('agent_id', sa.String(), nullable=True))

    op.add_column('llm_usage_events', sa.Column('agent_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_llm_usage_events_agent_id'), 'llm_usage_events', ['agent_id'], unique=False)

    op.add_column('audit_logs', sa.Column('agent_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_logs', 'agent_id')

    op.drop_index(op.f('ix_llm_usage_events_agent_id'), table_name='llm_usage_events')
    op.drop_column('llm_usage_events', 'agent_id')

    op.drop_column('chat_messages', 'agent_id')

    op.drop_constraint('fk_tasks_agent_id_agent_instances', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'agent_id')

    op.drop_index(op.f('ix_agent_sources_source_id'), table_name='agent_sources')
    op.drop_index(op.f('ix_agent_sources_agent_id'), table_name='agent_sources')
    op.drop_table('agent_sources')

    op.drop_index(op.f('ix_agent_instances_tenant_id'), table_name='agent_instances')
    op.drop_table('agent_instances')
    op.execute('DROP TYPE IF EXISTS agentinstancestatus')
    op.execute('DROP TYPE IF EXISTS agentemployeetype')
