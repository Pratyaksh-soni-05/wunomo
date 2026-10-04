"""add_pipeline_webhook_secret

Revision ID: 41dec24849f9
Revises: dd460a06e6ce
Create Date: 2026-10-04 00:00:00.000000

Security Master Ranking Item #16: the GitHub CI/CD webhook had no working
signature verification (GITHUB_WEBHOOK_SECRET was never declared on
Settings, so the check that referenced it was permanently a no-op) and
derived "which tenant" from an unauthenticated X-Tenant-ID header. Fixed
by moving to a per-pipeline secret rather than one global value -- a
global secret would let any tenant who has it forge another tenant's
deployment events, since every tenant configuring their own GitHub webhook
would need to be handed the same value.

Stored encrypted via the existing EncryptedJSON type (same mechanism as
DataSource.connection_config) as {"secret": "<raw>"}, nullable: a pipeline
with no secret generated yet has its webhook endpoint refused, same
generic 401 as a bad signature.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '41dec24849f9'
down_revision: Union[str, None] = 'dd460a06e6ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pipelines', sa.Column('webhook_secret', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('pipelines', 'webhook_secret')
