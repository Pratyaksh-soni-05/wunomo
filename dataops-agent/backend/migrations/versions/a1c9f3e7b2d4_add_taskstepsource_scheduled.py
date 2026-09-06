"""add_taskstepsource_scheduled

Revision ID: a1c9f3e7b2d4
Revises: f8a5decd97df
Create Date: 2026-09-06 00:00:00.000000

Wunomo Projects Phase 4, slice 14 (per-agent scheduled work): a
ScheduledAgentTask's fixed step is created directly by the beat tick with
no LLM plan generated and no human editing it in the moment -- neither
LLM_PLANNED nor HUMAN_EDITED is honest, and SYSTEM_INSERTED already means
something different (a verify step appended to an EXISTING plan, not the
entire, only step of a task). A new value, not an overload of an existing
one.

Label is 'SCHEDULED' (uppercase, the Python member NAME), matching every
other enum in this codebase.

This migration does ONLY the ALTER TYPE, same isolation as
5f96a0b0df98's own precedent -- Postgres cannot use a value added by
ALTER TYPE ... ADD VALUE within the same transaction that added it, so
nothing else touches taskstepsource in this migration.
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'a1c9f3e7b2d4'
down_revision: Union[str, None] = 'f8a5decd97df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstepsource ADD VALUE 'SCHEDULED' AFTER 'SYSTEM_INSERTED'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as 5f96a0b0df98's downgrade() -- not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
