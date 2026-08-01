"""add_team_invites

Revision ID: a4f7c92b1d05
Revises: 14a3b198ab68
Create Date: 2026-07-18 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a4f7c92b1d05'
down_revision: Union[str, None] = '14a3b198ab68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('team_invites',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('invited_by_user_id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_team_invites_email'), 'team_invites', ['email'], unique=False)
    # Real index, matches models/all_models.py's TeamInvite.created_at
    # (index=True) -- missing here originally; found via the Phase 19
    # migration-drift session's create_all()-vs-alembic schema diff. See
    # CLAUDE.md's Gotcha on this column for the full history (a stray
    # duplicate line, invisible to a too-short Read near EOF, had silently
    # been declaring this same index directly in the model for a while
    # before anyone noticed the migration itself never created it).
    op.create_index(op.f('ix_team_invites_created_at'), 'team_invites', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_team_invites_created_at'), table_name='team_invites')
    op.drop_index(op.f('ix_team_invites_email'), table_name='team_invites')
    op.drop_table('team_invites')
