"""add_agentemployeetype_analyst

Revision ID: a7c92f4e816d
Revises: e4f27a9d5b31
Create Date: 2026-09-21 09:00:00.000000

Second real AgentEmployeeType member (models/all_models.py's own docstring:
"extend this the day a second employee type actually ships, not before" --
that day is now). Isolated to just the ALTER TYPE, same reasoning as every
prior enum-value migration in this history (5f96a0b0df98, a1c9f3e7b2d4,
d8a15f3c9e62, etc.): Postgres can't use a freshly-added enum value in the
same transaction it was added in, so this must be its own migration, not
folded into whatever else touches AgentInstance next.

Label is 'ANALYST' (uppercase, the Python member NAME) -- SQLAlchemy's
SAEnum(AgentEmployeeType) with no `values_callable` stores the member name,
not `.value`, confirmed against the real column today (DATAOPS, not
"dataops").
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'a7c92f4e816d'
down_revision: Union[str, None] = 'e4f27a9d5b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE agentemployeetype ADD VALUE 'ANALYST' AFTER 'DATAOPS'")


def downgrade() -> None:
    raise NotImplementedError(
        "Postgres has no ALTER TYPE ... DROP VALUE. Same limitation and "
        "same rationale as every prior enum-value migration's downgrade() "
        "in this history -- not implemented; do this by hand if it's ever "
        "genuinely needed."
    )
