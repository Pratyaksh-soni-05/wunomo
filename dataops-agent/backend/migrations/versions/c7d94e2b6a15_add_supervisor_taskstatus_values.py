"""add_supervisor_taskstatus_values

Revision ID: c7d94e2b6a15
Revises: b2e6f1a83c47
Create Date: 2026-09-20 05:05:00.000000

Stage 2 (multi-agent supervisor): three new taskstatus values.
SUPERVISOR_QUEUED/SUPERVISOR_RUNNING are deliberately excluded from
RUNNABLE_TASK_STATUSES (models/all_models.py) -- services/tasks.py's
advance_active_tasks beat tick, live in every environment, queries
Task.status.in_(RUNNABLE_TASK_STATUSES) with no task_shape filter; if a
supervisor-dispatched task ever held a status in that tuple, the beat
tick would hand it to task_executor.execute_next_step(), which expects
an LLM-planned tool-call step this task_shape never has. BLOCKED_ON_
DEPENDENCY is a genuinely new outcome (a dependency task failed) with no
existing equivalent -- COMPLETED/FAILED/PAUSED_NEEDS_APPROVAL already
cover a supervisor task's other outcomes and needed no new value.

Batched as three ADD VALUE statements in one migration (same enum type,
no data touched) rather than one file each -- 5f96a0b0df98/a1c9f3e7b2d4's
own isolation rule ("nothing else touches this migration") is about not
mixing an ADD VALUE with a statement that USES the new value in the same
transaction, not about one-value-per-file; three ADD VALUEs on the same
type with no inserts alongside them carries the same guarantee.

Labels are the uppercase Python member NAMEs, matching every other enum
in this codebase (CLAUDE.md's hard rule).
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'c7d94e2b6a15'
down_revision: Union[str, None] = 'b2e6f1a83c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE 'SUPERVISOR_QUEUED' AFTER 'EXPIRED'")
    op.execute("ALTER TYPE taskstatus ADD VALUE 'SUPERVISOR_RUNNING' AFTER 'SUPERVISOR_QUEUED'")
    op.execute("ALTER TYPE taskstatus ADD VALUE 'BLOCKED_ON_DEPENDENCY' AFTER 'SUPERVISOR_RUNNING'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as 5f96a0b0df98's downgrade() -- not implemented; "
        "do this by hand if it's ever genuinely needed."
    )
