"""add_llm_usage_events

Revision ID: fe6e4b941fce
Revises: db3efa7d4d82
Create Date: 2026-07-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'fe6e4b941fce'
down_revision: Union[str, None] = 'db3efa7d4d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('llm_usage_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('request_type', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('used_fallback', sa.Boolean(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_llm_usage_events_tenant_id'), 'llm_usage_events', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_llm_usage_events_created_at'), 'llm_usage_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_llm_usage_events_created_at'), table_name='llm_usage_events')
    op.drop_index(op.f('ix_llm_usage_events_tenant_id'), table_name='llm_usage_events')
    op.drop_table('llm_usage_events')
