"""merge pratyaksh-workforce and security-baseline chains

Revision ID: d89011ced511
Revises: e5a9c3d7b2f1, a7c92f4e816d
Create Date: 2026-09-22 12:37:20.476079
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd89011ced511'
down_revision: Union[str, None] = ('e5a9c3d7b2f1', 'a7c92f4e816d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
