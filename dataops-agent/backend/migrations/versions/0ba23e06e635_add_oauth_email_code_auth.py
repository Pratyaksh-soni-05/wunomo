"""add_oauth_email_code_auth

Revision ID: 0ba23e06e635
Revises: 3186398dc663
Create Date: 2026-07-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0ba23e06e635'
down_revision: Union[str, None] = '3186398dc663'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'hashed_password',
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column('users', sa.Column('google_id', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=True))
    op.create_index(op.f('ix_users_google_id'), 'users', ['google_id'], unique=False)

    op.create_table('email_login_codes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('intended_tenant_id', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts_used', sa.Integer(), nullable=True),
        sa.Column('consumed_at', sa.DateTime(), nullable=True),
        sa.Column('request_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['intended_tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_login_codes_email'), 'email_login_codes', ['email'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_login_codes_email'), table_name='email_login_codes')
    op.drop_table('email_login_codes')
    op.drop_index(op.f('ix_users_google_id'), table_name='users')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'google_id')
    op.alter_column('users', 'hashed_password',
        existing_type=sa.String(length=255),
        nullable=False,
    )
