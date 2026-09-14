"""add_project_description

Revision ID: a3f7c982e410
Revises: d4e8a2f61c9b
Create Date: 2026-09-14 00:00:00.000000

Wunomo UI-rebuild, slice 4: the Home screen's "Recent" project cards (and
both design previews' own new-project modal) show a one-line description
per project. Nullable, optional at create time -- existing projects simply
have none, no backfill needed since there's no prior value to derive it
from.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a3f7c982e410'
down_revision: Union[str, None] = 'd4e8a2f61c9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'description')
