"""add_user_theme

Revision ID: b7e2f4a91c33
Revises: a4f7c92b1d05
Create Date: 2026-07-18 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b7e2f4a91c33'
down_revision: Union[str, None] = 'a4f7c92b1d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('theme', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'theme')
