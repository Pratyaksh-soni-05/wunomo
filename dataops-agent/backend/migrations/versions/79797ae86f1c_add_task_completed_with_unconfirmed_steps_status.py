"""add_task_completed_with_unconfirmed_steps_status

Revision ID: 79797ae86f1c
Revises: 6056972787ad
Create Date: 2026-08-05 13:00:00.000000

Item 6 stage 4 (verification, Q2): a dispatched step whose verification
never reaches a terminal state within its window must not let the task
report plain COMPLETED -- that would be a false clean success. This adds
the honest, distinct terminal status. See CLAUDE.md / docs/PRODUCT_AUDIT.md
section 1.9 for the full design.

Label is 'COMPLETED_WITH_UNCONFIRMED_STEPS' (uppercase, the Python member
NAME), matching every other enum in this codebase -- see the Gotcha this
project already has on record for why (SQLAlchemy's default
Enum(PythonEnumClass) stores .name, not .value; caught for the original 4
Task enum types in 509a9b8715f2, not repeated here).
"""
from typing import Sequence, Union
from alembic import op


revision: str = '79797ae86f1c'
down_revision: Union[str, None] = '6056972787ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE 'COMPLETED_WITH_UNCONFIRMED_STEPS' AFTER 'COMPLETED'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as 6056972787ad's downgrade() -- not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
