"""add_cicd_pipeline_tables

Revision ID: 609092d6978f
Revises: 7e3773979374
Create Date: 2026-05-15 00:00:00.000000

Fills a real gap found during the Phase 19 migration-drift verification
session: `pipeline_commits` and `pipeline_deployments` (models/cicd.py)
were never created by any Alembic migration at all -- only
`db3efa7d4d82` (add_cicd_incidents) existed, and it assumes both tables
(plus the cicdstatus/gatedecision/deploymentstatus enum types) already
exist, since it only creates `cicd_incidents` and ALTERs
`pipeline_deployments.pipeline_id`. On a real empty database this made
`alembic upgrade head` fail immediately at `db3efa7d4d82` with
`UndefinedTable: relation "pipeline_deployments" does not exist" --
confirmed live against a scratch Postgres 16 container before this fix
existed. This dev environment never hit that failure only because
`Base.metadata.create_all()` (main.py's startup hook, not Alembic) has
always been the real schema source here -- see CLAUDE.md's "This dev
DB's schema was never actually created by Alembic" Gotcha.

Column shapes below match models/cicd.py's current, live state exactly
(including pipeline_deployments.pipeline_id already NOT NULL from
creation) -- so db3efa7d4d82's own `alter_column(..., nullable=False)`
becomes a harmless no-op once this migration runs first, not a second
source of truth to keep in sync by hand.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '609092d6978f'
down_revision: Union[str, None] = '7e3773979374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pipeline_commits',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('pipeline_id', sa.String(), nullable=True),
        sa.Column('commit_sha', sa.String(length=64), nullable=False),
        sa.Column('branch', sa.String(length=255), nullable=False),
        sa.Column('author', sa.String(length=255), nullable=True),
        sa.Column('repo_url', sa.String(length=500), nullable=True),
        sa.Column('changed_files', sa.JSON(), nullable=True),
        sa.Column('commit_message', sa.Text(), nullable=True),
        sa.Column('trigger_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ci_status', sa.Enum('pending', 'running', 'passed', 'failed', 'skipped', name='cicdstatus'), nullable=True),
        sa.Column('gate_decision', sa.Enum('auto_approved', 'pending_approval', 'approved', 'rejected', name='gatedecision'), nullable=True),
        sa.Column('check_results', sa.JSON(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pipeline_commits_tenant_id'), 'pipeline_commits', ['tenant_id'], unique=False)

    op.create_table('pipeline_deployments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('pipeline_id', sa.String(), nullable=False),
        sa.Column('commit_id', sa.String(), nullable=False),
        sa.Column('commit_sha', sa.String(length=64), nullable=False),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('approval_type', sa.String(length=20), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('rollback_commit_sha', sa.String(length=64), nullable=True),
        sa.Column('status', sa.Enum('queued', 'deploying', 'active', 'rolled_back', 'failed', name='deploymentstatus'), nullable=True),
        sa.Column('monitoring_active', sa.Boolean(), nullable=True),
        sa.Column('post_deploy_run_count', sa.Integer(), nullable=True),
        sa.Column('post_deploy_failure_count', sa.Integer(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['commit_id'], ['pipeline_commits.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pipeline_deployments_tenant_id'), 'pipeline_deployments', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pipeline_deployments_tenant_id'), table_name='pipeline_deployments')
    op.drop_table('pipeline_deployments')
    op.drop_index(op.f('ix_pipeline_commits_tenant_id'), table_name='pipeline_commits')
    op.drop_table('pipeline_commits')
    op.execute("DROP TYPE IF EXISTS deploymentstatus")
    op.execute("DROP TYPE IF EXISTS gatedecision")
    op.execute("DROP TYPE IF EXISTS cicdstatus")
