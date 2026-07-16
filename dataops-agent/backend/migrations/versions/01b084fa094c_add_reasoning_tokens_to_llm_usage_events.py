"""add_reasoning_tokens_to_llm_usage_events

Revision ID: 01b084fa094c
Revises: 0ba23e06e635
Create Date: 2026-07-16 09:50:04.573298
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '01b084fa094c'
down_revision: Union[str, None] = '0ba23e06e635'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('llm_usage_events', sa.Column('reasoning_tokens', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('llm_usage_events', 'reasoning_tokens')
