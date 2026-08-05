"""add_task_termination_reason

Revision ID: d3257ec7847e
Revises: 79797ae86f1c
Create Date: 2026-08-06 00:00:00.000000

Item 6 stage 6 (termination, Q4): a nullable text column recording why a
task stopped without a clean outcome -- which cap fired (step/wall-clock/
loop) for a FAILED task, or the cancellation circumstances for a
CANCELLED one. Unlike every other reason field this project added for
Task (pause_reason/completion_note/expiry_reason/approval_pending_reason),
none of those are derivable from a related step's own data for this
case, so this is a real persisted column, not a computed one.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd3257ec7847e'
down_revision: Union[str, None] = '79797ae86f1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('termination_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'termination_reason')
