"""add_tasks_and_task_steps

Revision ID: 509a9b8715f2
Revises: c8f3a7d52e19
Create Date: 2026-08-05 00:00:00.000000

Item 6 (long-running AXIOM tasks) stage 1: schema only, no behavior yet --
see CLAUDE.md's item-6 design decisions section for the full model
(failure semantics, structural verification, visibility, termination,
mid-task approvals, plan provenance, role-at-execution-time).

Column shapes match models/all_models.py's Task/TaskStep classes exactly.
Both `tenant_id` and `user_id` on `tasks` are real FKs (matching the
TeamInvite/ApiKey precedent of a real, first-class tenant-owned entity,
not the majority bare-String convention used by lower-stakes log-style
tables like transform_runs). `tasks.user_id` is the task's initiator only
-- role/is_active are deliberately NOT stored anywhere on this table and
are re-read fresh from the DB before every step executes (see the model
docstring); there is nothing here to keep in sync with a role change.

Enum labels are the Python member NAMES (uppercase: 'DRAFT_PLAN', not the
member .value 'draft_plan') -- SQLAlchemy's default Enum(PythonEnumClass)
behavior stores .name, not .value, and every other enum in this codebase
(confirmed live against the dev DB: personalitymode/runstatus/etc. all
store uppercase labels) already relies on this. An earlier draft of this
migration got this backwards (lowercase values) -- caught before it was
ever applied to anything but a throwaway scratch DB, by directly querying
pg_enum rather than trusting compare_metadata() alone, which doesn't diff
enum label content (a known, documented blind spot of that check).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '509a9b8715f2'
down_revision: Union[str, None] = 'c8f3a7d52e19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tasks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('originating_session_id', sa.String(), nullable=True),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('task_shape', sa.Enum(
            'DIAGNOSE_PIPELINE_FAILURE', 'INVESTIGATE_INCIDENT', 'SYNC_PROFILE_QUALITY',
            name='taskshape'), nullable=False),
        sa.Column('status', sa.Enum(
            'DRAFT_PLAN', 'PLAN_REJECTED', 'RUNNING', 'PAUSED_NEEDS_APPROVAL',
            'PAUSED_FAILED_STEP', 'PAUSED_PLAN_INVALID', 'PAUSED_QUOTA_EXCEEDED',
            'COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED',
            name='taskstatus'), nullable=False),
        sa.Column('plan_approved_by', sa.String(), nullable=True),
        sa.Column('plan_approved_at', sa.DateTime(), nullable=True),
        sa.Column('plan_edited', sa.Boolean(), nullable=True),
        sa.Column('step_budget_max', sa.Integer(), nullable=False),
        sa.Column('step_budget_used', sa.Integer(), nullable=True),
        sa.Column('credit_budget_max', sa.Integer(), nullable=True),
        sa.Column('credit_budget_used', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('paused_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['plan_approved_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('task_steps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('source', sa.Enum(
            'LLM_PLANNED', 'HUMAN_EDITED', 'SYSTEM_INSERTED',
            name='taskstepsource'), nullable=False),
        sa.Column('tool_name', sa.String(length=100), nullable=True),
        sa.Column('tool_args', sa.JSON(), nullable=True),
        sa.Column('depends_on_step_index', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum(
            'PENDING', 'RUNNING', 'VERIFYING', 'SUCCEEDED', 'FAILED', 'SKIPPED', 'BLOCKED_APPROVAL',
            name='taskstepstatus'), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=True),
        sa.Column('outcome_summary', sa.Text(), nullable=True),
        sa.Column('raw_result', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('approval_request_id', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_requests.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_task_steps_task_id'), 'task_steps', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_steps_task_id'), table_name='task_steps')
    op.drop_table('task_steps')
    op.drop_table('tasks')
    op.execute('DROP TYPE IF EXISTS taskstepstatus')
    op.execute('DROP TYPE IF EXISTS taskstepsource')
    op.execute('DROP TYPE IF EXISTS taskstatus')
    op.execute('DROP TYPE IF EXISTS taskshape')
