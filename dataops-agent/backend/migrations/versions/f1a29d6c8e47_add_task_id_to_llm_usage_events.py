"""add_task_id_to_llm_usage_events

Revision ID: f1a29d6c8e47
Revises: a4f8c2e91b06
Create Date: 2026-08-29 16:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f1a29d6c8e47'
down_revision: Union[str, None] = 'a4f8c2e91b06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('llm_usage_events', sa.Column('task_id', sa.String(), nullable=True))
    op.create_index('ix_llm_usage_events_task_id', 'llm_usage_events', ['task_id'])


def downgrade() -> None:
    op.drop_index('ix_llm_usage_events_task_id', table_name='llm_usage_events')
    op.drop_column('llm_usage_events', 'task_id')
