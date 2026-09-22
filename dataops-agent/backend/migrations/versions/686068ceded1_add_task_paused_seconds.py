"""add_task_paused_seconds

Revision ID: 686068ceded1
Revises: 5f96a0b0df98
Create Date: 2026-09-03 18:00:00.000000

WALKTHROUGH_FINDINGS_2026-08.md item 72: _check_wall_clock_cap measured
raw calendar time since Task.started_at, with no awareness of time
spent in a paused status -- a task approved more than
MAX_TASK_WALL_CLOCK_HOURS (4) after it started was immediately marked
FAILED for wall-clock exhaustion, undoing the approval that had just
been granted. paused_seconds is the fix: a cumulative counter,
incremented at every transition out of PAUSED_NEEDS_APPROVAL /
PAUSED_QUOTA_EXCEEDED / PAUSED_SOURCE_LOCKED back to RUNNING, subtracted
from elapsed time before the wall-clock cap is checked.

Backfilled to 0 for every existing row -- no historical task has a
recoverable pause history to compute this from, and 0 is the correct,
honest value for "unknown, assume no paused time."
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '686068ceded1'
down_revision: Union[str, None] = '5f96a0b0df98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('paused_seconds', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('tasks', 'paused_seconds', server_default=None)


def downgrade() -> None:
    op.drop_column('tasks', 'paused_seconds')
