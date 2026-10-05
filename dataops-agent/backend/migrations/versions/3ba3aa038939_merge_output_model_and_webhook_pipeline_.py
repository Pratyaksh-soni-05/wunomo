"""merge output model and webhook pipeline heads

Revision ID: 3ba3aa038939
Revises: d2525951705c, f2a6f3d01f22
Create Date: 2026-10-05 07:57:45.210359
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '3ba3aa038939'
down_revision: Union[str, None] = ('d2525951705c', 'f2a6f3d01f22')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
