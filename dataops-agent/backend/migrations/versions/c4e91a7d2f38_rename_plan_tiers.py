"""rename plan tiers to the real pricing keys

Renames `Tenant.plan` from the old 3-key internal set to the 4 keys the pricing
model actually sells:

    starter -> standard
    growth  -> premium
    scale   -> enterprise
    (starter_plus is new; no existing tenant migrates into it)

`starter_plus` is a sign-up-only tier. Verified against the live database before
writing this: 0 tenants would map into it, and the three source keys account for
every row (7,246 starter / 14 growth / 23 scale, with 0 NULL and 0 values
outside that set).

    WHY THIS IS A DATA MIGRATION AND NOT A CODE-ONLY RENAME
    ------------------------------------------------------
    `Tenant.plan` is a plain VARCHAR(50) with no ForeignKey, no CHECK
    constraint, and no enum backing it. Nothing in the schema prevents a row
    from carrying an arbitrary string, which means (a) the rename cannot be
    enforced by the database, and (b) a row that misses this migration will
    still read and write fine while silently not matching any key in
    quota_service.PLANS.

    That second point is why `_plan_limits()` was changed in the same commit to
    raise `UnknownPlanError` instead of falling back to the cheapest tier. The
    previous `PLANS.get(plan, PLANS["starter"])` would have turned an unmigrated
    Enterprise tenant into a Standard one — same API responses, quietly smaller
    quota, 402s with no explanation. A loud failure naming the tenant and the
    expected key is strictly better than a silent downgrade.

The upgrade is idempotent in the sense that matters: it only touches rows whose
plan is still one of the three legacy values, so re-running it is a no-op rather
than an error. It does not attempt to be reversible-safe against rows created
*after* it ran — downgrade maps the new keys back, which will also catch any
genuinely-new `starter_plus` tenant (there is no old key for it, so it collapses
to `starter`; see the downgrade note).

Revision ID: c4e91a7d2f38
Revises: b7d419e3f2a8
Create Date: 2026-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e91a7d2f38'
down_revision: Union[str, None] = 'b7d419e3f2a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLAN_RENAMES = [
    ("starter", "standard"),
    ("growth", "premium"),
    ("scale", "enterprise"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Fail before changing anything if the data does not look like what this
    # migration was written against. A plan value outside the known set means
    # someone has provisioned a tier by hand, and silently leaving it behind
    # would produce exactly the unmigrated-row problem described above.
    unexpected = conn.execute(sa.text(
        "SELECT DISTINCT plan FROM tenants "
        "WHERE plan IS NULL OR plan NOT IN ('starter','growth','scale',"
        "'standard','starter_plus','premium','enterprise')"
    )).scalars().all()
    if unexpected:
        raise RuntimeError(
            f"tenants.plan contains value(s) this migration does not know how "
            f"to map: {unexpected}. Resolve them before migrating — leaving "
            f"them would make those tenants fail quota checks with "
            f"UnknownPlanError."
        )

    for old, new in PLAN_RENAMES:
        result = conn.execute(
            sa.text("UPDATE tenants SET plan = :new WHERE plan = :old"),
            {"new": new, "old": old},
        )
        print(f"  tenants.plan {old!r} -> {new!r}: {result.rowcount} row(s)")

    remaining = conn.execute(sa.text(
        "SELECT count(*) FROM tenants WHERE plan IN ('starter','growth','scale')"
    )).scalar()
    if remaining:
        raise RuntimeError(
            f"{remaining} tenant(s) still carry a legacy plan key after the "
            f"rename — the UPDATEs did not fully apply."
        )


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in PLAN_RENAMES:
        conn.execute(
            sa.text("UPDATE tenants SET plan = :old WHERE plan = :new"),
            {"old": old, "new": new},
        )
    # `starter_plus` has no pre-rename equivalent — the old scheme had no tier
    # between Standard and Premium. Any tenant signed up on it after this
    # migration ran collapses to `starter`, which is the closest old tier and
    # the conservative direction (smaller quota, not larger). This is lossy and
    # deliberately so: the alternative is failing the downgrade outright, which
    # would leave an operator unable to roll back at all.
    conn.execute(sa.text(
        "UPDATE tenants SET plan = 'starter' WHERE plan = 'starter_plus'"
    ))
