"""add_handoffs_table

Revision ID: b2e6f1a83c47
Revises: a3f7c982e410
Create Date: 2026-09-20 05:00:00.000000

Stage 2 (multi-agent supervisor, modules/orchestration/supervisor.py):
the one new table the design calls for -- the durable record of one
agent's completed task feeding another agent's task in the same channel.

tenant_id is a REAL FK here (unlike this codebase's usual bare-tenant_id-
by-convention pattern for AuditLog/ChatMessage/ApprovalRequest/etc, all of
which skip the FK so a write can never fail on a referential-integrity
check) -- a Handoff is never write-critical the way an audit/metering row
is, it's read-path provenance for a UI always scoped to a real, live
tenant/channel, so the stronger guarantee costs nothing here.

Also adds tasks.depends_on_task_id (self-referential, nullable) in this
same migration -- a plain schema addition like d4e8a2f61c9b's own
precedent (new table + a new FK column on tasks, together), not an enum
value add, so it's safe to combine with the table creation in one
transaction.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b2e6f1a83c47'
down_revision: Union[str, None] = 'a3f7c982e410'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('handoffs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('from_agent_id', sa.String(), nullable=False),
        sa.Column('to_agent_id', sa.String(), nullable=False),
        sa.Column('from_task_id', sa.String(), nullable=False),
        sa.Column('to_task_id', sa.String(), nullable=False),
        sa.Column('payload_summary', sa.Text(), nullable=False),
        sa.Column('payload_ref', sa.String(), nullable=True),
        sa.Column('withheld', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['from_agent_id'], ['agent_instances.id'], ),
        sa.ForeignKeyConstraint(['to_agent_id'], ['agent_instances.id'], ),
        sa.ForeignKeyConstraint(['from_task_id'], ['tasks.id'], ),
        sa.ForeignKeyConstraint(['to_task_id'], ['tasks.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_handoffs_tenant_id'), 'handoffs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_handoffs_channel_id'), 'handoffs', ['channel_id'], unique=False)
    op.create_index(op.f('ix_handoffs_from_task_id'), 'handoffs', ['from_task_id'], unique=False)
    op.create_index(op.f('ix_handoffs_to_task_id'), 'handoffs', ['to_task_id'], unique=False)

    op.add_column('tasks', sa.Column('depends_on_task_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_depends_on_task_id', 'tasks', 'tasks', ['depends_on_task_id'], ['id'],
    )
    # The supervisor's own scheduler checks "is my dependency COMPLETED
    # yet" on every wave -- WHERE depends_on_task_id = ? needs this to stay
    # an index scan, same reasoning as ix_tasks_status_updated_at.
    op.create_index(op.f('ix_tasks_depends_on_task_id'), 'tasks', ['depends_on_task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tasks_depends_on_task_id'), table_name='tasks')
    op.drop_constraint('fk_tasks_depends_on_task_id', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'depends_on_task_id')

    op.drop_index(op.f('ix_handoffs_to_task_id'), table_name='handoffs')
    op.drop_index(op.f('ix_handoffs_from_task_id'), table_name='handoffs')
    op.drop_index(op.f('ix_handoffs_channel_id'), table_name='handoffs')
    op.drop_index(op.f('ix_handoffs_tenant_id'), table_name='handoffs')
    op.drop_table('handoffs')
