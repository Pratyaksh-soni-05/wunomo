"""Add TOTP MFA columns to users (Security Master Ranking Item #13).

Revision ID: d4f8b2c6e1a9
Revises: a7c2e9f1b3d4
Create Date: 2026-09-18

Five nullable-or-defaulted columns; no data is rewritten except one
backfill: every existing owner/admin gets mfa_required_since = now(), which
starts their enrolment grace period at deploy time rather than at their
account's creation (an owner created in July must not be locked out the
moment this ships). New owners get the same stamp from the code path that
creates them.

mfa_secret is stored through the EncryptedJSON type at the ORM layer; at the
database it is a plain JSON column holding a Fernet token, exactly like
data_sources.connection_config.
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f8b2c6e1a9"
down_revision = "a7c2e9f1b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_secret", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False,
                                     server_default=sa.text("false")))
    op.add_column("users", sa.Column("mfa_enabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("mfa_backup_codes", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("mfa_required_since", sa.DateTime(), nullable=True))
    # Grace period for existing privileged users starts now, not at signup.
    op.execute(
        "UPDATE users SET mfa_required_since = (now() AT TIME ZONE 'utc') "
        "WHERE role IN ('owner', 'admin') AND mfa_required_since IS NULL"
    )


def downgrade() -> None:
    for col in ("mfa_required_since", "mfa_backup_codes", "mfa_enabled_at",
                "mfa_enabled", "mfa_secret"):
        op.drop_column("users", col)
