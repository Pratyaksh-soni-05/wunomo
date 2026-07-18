"""add_transform_runs

Revision ID: 14a3b198ab68
Revises: 01b084fa094c
Create Date: 2026-07-18 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '14a3b198ab68'
down_revision: Union[str, None] = '01b084fa094c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('transform_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('source_id', sa.String(), nullable=True),
        sa.Column('transform_type', sa.String(length=20), nullable=False),
        sa.Column('origin', sa.String(length=20), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_preview', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transform_runs_tenant_id'), 'transform_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_transform_runs_source_id'), 'transform_runs', ['source_id'], unique=False)
    op.create_index(op.f('ix_transform_runs_created_at'), 'transform_runs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_transform_runs_created_at'), table_name='transform_runs')
    op.drop_index(op.f('ix_transform_runs_source_id'), table_name='transform_runs')
    op.drop_index(op.f('ix_transform_runs_tenant_id'), table_name='transform_runs')
    op.drop_table('transform_runs')
