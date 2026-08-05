"""add_task_queued_status

Revision ID: 6056972787ad
Revises: 509a9b8715f2
Create Date: 2026-08-05 00:30:00.000000

Adds a distinct 'queued' value to the taskstatus enum -- the gap between
a plan being approved and the stage-3 executor actually picking it up is
permanent (queue depth, worker restarts, credit checks), not just a
stage-2-vs-3 build-window artifact, and collapsing it into 'running' would
hide the difference between "approved but never picked up" and "running
but stuck" exactly when that distinction matters most. See CLAUDE.md /
docs/PRODUCT_AUDIT.md section 1.9 for the full design.

Postgres cannot remove an enum value directly (no ALTER TYPE ... DROP
VALUE) -- downgrade() is an honest no-op with an explanation, matching
this codebase's established pattern of admitting a real limitation rather
than faking a rollback (see e.g. the billing endpoints' honest 501s).

Label is 'QUEUED' (uppercase, the Python member NAME), not 'queued' --
matches 509a9b8715f2's own correction and every other enum in this
codebase (SQLAlchemy's default Enum(PythonEnumClass) stores .name, not
.value; confirmed live against pg_enum for personalitymode/runstatus/etc.
before either migration was written this way).
"""
from typing import Sequence, Union
from alembic import op


revision: str = '6056972787ad'
down_revision: Union[str, None] = '509a9b8715f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE 'QUEUED' AFTER 'PLAN_REJECTED'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Removing 'queued' for "
        "real would require the full type-recreation dance (new type -> "
        "ALTER TABLE tasks to use it -> drop old type -> rename) and only "
        "makes sense if no row has ever used the value. Not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
