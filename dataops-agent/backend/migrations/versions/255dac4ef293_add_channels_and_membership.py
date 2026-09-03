"""add_channels_and_membership

Revision ID: 255dac4ef293
Revises: 5352d10a64ef
Create Date: 2026-09-03 00:00:00.000000

Wunomo Projects Phase 2, part one -- schema for the channel. channels is
a real, first-class table (name, project_id, created_at) rather than an
extension of the bare session_id grouping convention: the moment a
conversation has multiple participants, @mention routing and filtered
context both need to resolve against a real membership set, which a
bare string with nothing to join against structurally cannot express.

ChatMessage.session_id is deliberately NOT given a foreign key to
channels.id here -- correlation stays by value (a real channel's id is
simply used as the session_id for its messages), matching this table's
own established convention for agent_id/tenant_id (log-shaped tables
that must never fail an insert over a referential-integrity check).
This means zero backfill: every message that exists today, and every
future private 1:1 chat message, keeps using a bare session_id with no
matching channels row, exactly as before this migration.

channel_users/channel_agents are real join tables (not a JSON member
list), matching agent_sources/project_agents's own precedent.
mentioned_agent_id on chat_messages is a single nullable, FK-less
column -- singular because v1's @mention model is "the tagged agent
responds, nobody else," and FK-less for the same reason agent_id on
this table already is.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '255dac4ef293'
down_revision: Union[str, None] = '5352d10a64ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('channels',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_channels_tenant_id'), 'channels', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_channels_project_id'), 'channels', ['project_id'], unique=False)

    op.create_table('channel_users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'user_id', name='uq_channel_users_channel_user'),
    )
    op.create_index(op.f('ix_channel_users_channel_id'), 'channel_users', ['channel_id'], unique=False)
    op.create_index(op.f('ix_channel_users_user_id'), 'channel_users', ['user_id'], unique=False)

    op.create_table('channel_agents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_instances.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'agent_id', name='uq_channel_agents_channel_agent'),
    )
    op.create_index(op.f('ix_channel_agents_channel_id'), 'channel_agents', ['channel_id'], unique=False)
    op.create_index(op.f('ix_channel_agents_agent_id'), 'channel_agents', ['agent_id'], unique=False)

    op.add_column('chat_messages', sa.Column('mentioned_agent_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_messages', 'mentioned_agent_id')

    op.drop_index(op.f('ix_channel_agents_agent_id'), table_name='channel_agents')
    op.drop_index(op.f('ix_channel_agents_channel_id'), table_name='channel_agents')
    op.drop_table('channel_agents')

    op.drop_index(op.f('ix_channel_users_user_id'), table_name='channel_users')
    op.drop_index(op.f('ix_channel_users_channel_id'), table_name='channel_users')
    op.drop_table('channel_users')

    op.drop_index(op.f('ix_channels_project_id'), table_name='channels')
    op.drop_index(op.f('ix_channels_tenant_id'), table_name='channels')
    op.drop_table('channels')
