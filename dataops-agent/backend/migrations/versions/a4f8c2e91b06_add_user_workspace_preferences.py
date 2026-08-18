"""add_user_workspace_preferences

Revision ID: a4f8c2e91b06
Revises: d3257ec7847e
Create Date: 2026-08-19 00:00:00.000000

Item 1 (2026-08 walkthrough): "log straight into the last workspace used"
instead of always showing the choose-workspace picker on every login for
a multi-tenant email. Keyed by email (not user_id) since the same email
has a separate User row per tenant -- "which workspace did this person
use last" is a cross-tenant, per-person fact.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a4f8c2e91b06'
down_revision: Union[str, None] = 'd3257ec7847e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_workspace_preferences',
        sa.Column('email', sa.String(length=255), primary_key=True),
        sa.Column('tenant_id', sa.String(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('user_workspace_preferences')
