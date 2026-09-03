"""add_projects_and_project_agents

Revision ID: 5352d10a64ef
Revises: 480d5b8245f3
Create Date: 2026-09-03 00:00:00.000000

Wunomo Projects Phase 1, part two -- schema for projects and hiring.
project_agents is a real join table (agent<->project), not a project_id
column on agent_instances -- same reasoning agent_sources already
established for agent<->source scope, and it means every agent that
exists today (including every tenant's AXIOM row) needs no backfill: it
simply has no project_agents row, which is a valid, permanent state
("hired outside any project"), not a null placeholder waiting to be
filled in.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '5352d10a64ef'
down_revision: Union[str, None] = '480d5b8245f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('projects',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_projects_tenant_name'),
    )
    op.create_index(op.f('ix_projects_tenant_id'), 'projects', ['tenant_id'], unique=False)

    op.create_table('project_agents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_instances.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'agent_id', name='uq_project_agents_project_agent'),
    )
    op.create_index(op.f('ix_project_agents_project_id'), 'project_agents', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_agents_agent_id'), 'project_agents', ['agent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_project_agents_agent_id'), table_name='project_agents')
    op.drop_index(op.f('ix_project_agents_project_id'), table_name='project_agents')
    op.drop_table('project_agents')

    op.drop_index(op.f('ix_projects_tenant_id'), table_name='projects')
    op.drop_table('projects')
