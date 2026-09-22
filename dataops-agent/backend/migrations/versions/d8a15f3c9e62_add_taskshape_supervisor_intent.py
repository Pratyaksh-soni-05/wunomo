"""add_taskshape_supervisor_intent

Revision ID: d8a15f3c9e62
Revises: c7d94e2b6a15
Create Date: 2026-09-20 05:10:00.000000

Stage 2 (multi-agent supervisor): a single free-form instruction parsed
from one @mention in a supervisor-orchestrated channel message, run once
through the existing per-agent graph (run_agent(), unchanged) -- never
through task_planner.py's LLM plan generation the three existing shapes
drive. This migration does ONLY the ALTER TYPE, same isolation as
5f96a0b0df98/a1c9f3e7b2d4's own precedent.

Label is 'SUPERVISOR_INTENT' (uppercase, the Python member NAME).
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'd8a15f3c9e62'
down_revision: Union[str, None] = 'c7d94e2b6a15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskshape ADD VALUE 'SUPERVISOR_INTENT' AFTER 'SYNC_PROFILE_QUALITY'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as 5f96a0b0df98's downgrade() -- not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
