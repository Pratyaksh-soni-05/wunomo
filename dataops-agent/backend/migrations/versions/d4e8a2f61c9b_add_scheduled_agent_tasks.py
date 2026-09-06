"""add_scheduled_agent_tasks

Revision ID: d4e8a2f61c9b
Revises: a1c9f3e7b2d4
Create Date: 2026-09-06 00:05:00.000000

Wunomo Projects Phase 4, slice 14 (per-agent scheduled work). See
ScheduledAgentTask's own docstring (models/all_models.py) for the full
design -- fixed tool call, no replanning, real-user attribution, and
automatic deactivation-with-notification (never a silent stop) when the
owner loses access, the agent is offboarded, or a referenced source is
deleted.

task_shape reuses the *existing* taskshape Postgres enum type (created by
the original Task-table migration) via postgresql.ENUM(..., create_type=
False) -- the same precedent already established in this codebase
(b3f8a1d92c56's personality/operation_mode columns) for reusing an enum
type across tables rather than creating a duplicate.

tasks.originating_schedule_id is a real FK (unlike originating_session_id's
FK-less, log-shaped convention) -- ScheduledAgentTask is a real, joinable
row like AgentInstance, not a log-shaped table, and Task already uses real
FKs on every other identity column (tenant_id, user_id, agent_id).
Nullable and defaults to NULL for every existing row -- no historical
task was ever schedule-created.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd4e8a2f61c9b'
down_revision: Union[str, None] = 'a1c9f3e7b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scheduled_agent_tasks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('created_by_user_id', sa.String(), nullable=False),
        sa.Column('task_shape', postgresql.ENUM(
            'DIAGNOSE_PIPELINE_FAILURE', 'INVESTIGATE_INCIDENT', 'SYNC_PROFILE_QUALITY',
            name='taskshape', create_type=False), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('tool_name', sa.String(length=100), nullable=False),
        sa.Column('tool_args', sa.JSON(), nullable=False),
        sa.Column('schedule_cron', sa.String(length=100), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('deactivation_reason', sa.Text(), nullable=True),
        sa.Column('last_fired_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_instances.id'], ),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.alter_column('scheduled_agent_tasks', 'active', server_default=None)
    op.create_index(op.f('ix_scheduled_agent_tasks_tenant_id'), 'scheduled_agent_tasks', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_scheduled_agent_tasks_agent_id'), 'scheduled_agent_tasks', ['agent_id'], unique=False)
    # Matches ix_tasks_status_updated_at's own rationale -- the beat tick
    # will poll WHERE active = true every 60s; without this, that becomes
    # a full table scan as the table grows the same way tasks did (item 74).
    op.create_index(op.f('ix_scheduled_agent_tasks_active'), 'scheduled_agent_tasks', ['active'], unique=False)

    op.add_column('tasks', sa.Column('originating_schedule_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_originating_schedule_id', 'tasks', 'scheduled_agent_tasks',
        ['originating_schedule_id'], ['id'], ondelete='SET NULL',
    )
    # Matches Task.originating_schedule_id's own no-overlap check (skip
    # firing while a schedule's previous Task is still non-terminal) --
    # WHERE originating_schedule_id = ? AND status NOT IN (...) needs this
    # to stay an index scan, same reasoning as ix_tasks_status_updated_at.
    op.create_index(op.f('ix_tasks_originating_schedule_id'), 'tasks', ['originating_schedule_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tasks_originating_schedule_id'), table_name='tasks')
    op.drop_constraint('fk_tasks_originating_schedule_id', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'originating_schedule_id')

    op.drop_index(op.f('ix_scheduled_agent_tasks_active'), table_name='scheduled_agent_tasks')
    op.drop_index(op.f('ix_scheduled_agent_tasks_agent_id'), table_name='scheduled_agent_tasks')
    op.drop_index(op.f('ix_scheduled_agent_tasks_tenant_id'), table_name='scheduled_agent_tasks')
    op.drop_table('scheduled_agent_tasks')
