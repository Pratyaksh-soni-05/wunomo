"""add_task_updated_at_and_index

Revision ID: f8a5decd97df
Revises: 686068ceded1
Create Date: 2026-09-03 19:00:00.000000

Wunomo Projects Phase 3, item 71/slice 10: the auto-advance beat tick
selects the oldest-untouched runnable tasks every 60s (ORDER BY
updated_at ASC WHERE status IN (...) LIMIT N). Without updated_at, that
query has nothing honest to order by and no index to use -- a full scan
of a table that's already at 6,053 rows and growing (see
WALKTHROUGH_FINDINGS_2026-08.md item 74) on every single tick.

Backfilled from created_at for every existing row -- the honest value
for "last touched" on a row with no real update-tracking history before
this column existed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f8a5decd97df'
down_revision: Union[str, None] = '686068ceded1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.execute('UPDATE tasks SET updated_at = created_at WHERE updated_at IS NULL')
    op.alter_column('tasks', 'updated_at', nullable=False)
    op.create_index('ix_tasks_status_updated_at', 'tasks', ['status', 'updated_at'])


def downgrade() -> None:
    op.drop_index('ix_tasks_status_updated_at', table_name='tasks')
    op.drop_column('tasks', 'updated_at')
