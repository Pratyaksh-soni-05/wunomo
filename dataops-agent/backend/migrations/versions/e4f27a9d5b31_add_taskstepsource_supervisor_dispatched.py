"""add_taskstepsource_supervisor_dispatched

Revision ID: e4f27a9d5b31
Revises: d8a15f3c9e62
Create Date: 2026-09-20 05:15:00.000000

Stage 2 (multi-agent supervisor): the single TaskStep behind a
SUPERVISOR_INTENT task -- one free-form instruction run once through
run_agent(), never LLM-planned as a tool call (LLM_PLANNED) and never
appended to an existing plan (SYSTEM_INSERTED). Same "genuinely new
provenance" reasoning a1c9f3e7b2d4 already used for SCHEDULED. This
migration does ONLY the ALTER TYPE, same isolation as that precedent.

Label is 'SUPERVISOR_DISPATCHED' (uppercase, the Python member NAME).
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'e4f27a9d5b31'
down_revision: Union[str, None] = 'd8a15f3c9e62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstepsource ADD VALUE 'SUPERVISOR_DISPATCHED' AFTER 'SCHEDULED'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as 5f96a0b0df98's downgrade() -- not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
