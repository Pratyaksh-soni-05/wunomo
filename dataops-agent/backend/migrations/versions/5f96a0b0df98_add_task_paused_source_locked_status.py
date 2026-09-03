"""add_task_paused_source_locked_status

Revision ID: 5f96a0b0df98
Revises: 255dac4ef293
Create Date: 2026-09-03 14:00:00.000000

Wunomo Projects Phase 2, item 5 (per-source advisory locking): a task
step whose source is held by another caller must pause and resume once
the lock frees, the same shape PAUSED_QUOTA_EXCEEDED already uses for
credit exhaustion -- not fail the step outright.

Label is 'PAUSED_SOURCE_LOCKED' (uppercase, the Python member NAME),
matching every other enum in this codebase (see CLAUDE.md's hard rule
and 79797ae86f1c's own note on this).
"""
from typing import Sequence, Union
from alembic import op


revision: str = '5f96a0b0df98'
down_revision: Union[str, None] = '255dac4ef293'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE 'PAUSED_SOURCE_LOCKED' AFTER 'PAUSED_QUOTA_EXCEEDED'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as 6056972787ad's downgrade() -- not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
