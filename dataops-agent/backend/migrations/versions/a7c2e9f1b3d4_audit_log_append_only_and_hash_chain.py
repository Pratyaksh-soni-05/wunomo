"""audit_logs: append-only trigger + per-tenant hash chain (Item #9)

Revision ID: a7c2e9f1b3d4
Revises: c4e91a7d2f38
Create Date: 2026-09-12

WHAT THIS ADDS

  1. Three columns: chain_seq (database sequence, the chain's order),
     prev_hash, row_hash. Nullable, because rows written before this
     migration exist and are backfilled in step 2.

  2. A backfill of every existing row, per tenant, in created_at order,
     using services.audit_chain.compute_row_hash -- the SAME function the
     writer and the verifier use. This is the "chain the history" choice;
     see the tradeoff below.

  3. A trigger that raises on UPDATE or DELETE. Measured before writing it
     (see the Item #9 GOTCHAS entry): it fires for every role INCLUDING the
     superuser dataops_user -- triggers are not policies and BYPASSRLS does
     not skip them. A superuser can still disable it, but only by an
     explicit `SET session_replication_role = replica` or `ALTER TABLE ...
     DISABLE TRIGGER`, both of which the app role (dataops_app) is denied.

HISTORICAL ROWS -- THE TRADEOFF, STATED

Backfilling links pre-migration rows into the chain so a reviewer sees one
unbroken sequence from a tenant's first action. The cost is honesty about
what that proves: the chain can only vouch that rows have not changed SINCE
they were chained. A row altered the day before this migration ran is
chained as-is, and the chain will say it is intact -- because from the
chain's point of view it is. The alternative (start fresh, mark old rows
"pre-chain") is more explicit about that boundary but leaves every reviewer
staring at an unverifiable prefix forever.

Backfill was chosen because the history is small (14 rows on the dev
database at migration time), the alternative buys no additional integrity
-- pre-migration rows are exactly as trustworthy either way -- and the
boundary is recorded here and in the verifier's output (it prints the
earliest chained created_at). The guarantee is "unchanged since
2026-09-12", not "unchanged since written". Say that in any compliance
context.

DOWNGRADE

Drops the trigger, the function, the columns and the sequence.
"""
import sys
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "a7c2e9f1b3d4"
down_revision = "c4e91a7d2f38"
branch_labels = None
depends_on = None

# The backfill must use the one real hash function. migrations/ is not on the
# import path when alembic runs from the repo root inside the container, so
# add the backend root explicitly rather than duplicating the algorithm here.
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


TRIGGER_FN = """
CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Raised, not silently ignored: the caller should know the write was
    -- refused, and a refused UPDATE against the audit log is itself worth
    -- noticing in the application log.
    RAISE EXCEPTION 'audit_logs is append-only: % is not permitted (row id %)',
        TG_OP, COALESCE(OLD.id, '?')
        USING ERRCODE = 'insufficient_privilege';
END
$$;
"""

TRIGGER = """
CREATE TRIGGER audit_logs_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
"""


def upgrade() -> None:
    from services.audit_chain import GENESIS, compute_row_hash

    conn = op.get_bind()

    # 1. Columns. The sequence is created explicitly so the ORM
    #    (Sequence("audit_logs_chain_seq")) and the backfill agree on its name.
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_logs_chain_seq")
    # The app role (Item #2's dataops_app, NOSUPERUSER) must be able to draw
    # from the sequence or every INSERT fails with "permission denied for
    # sequence". Caught by the first test run: without this grant,
    # log_action -- which swallows exceptions -- would have silently dropped
    # every audit entry the application ever wrote. Table privileges were
    # granted by b7d419e3f2a8; a new sequence needs its own grant.
    op.execute("GRANT USAGE, SELECT ON SEQUENCE audit_logs_chain_seq TO dataops_app")
    op.add_column("audit_logs", sa.Column("chain_seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("row_hash", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_audit_logs_chain_seq", "audit_logs", ["chain_seq"])

    # 2. Backfill, per tenant, in the order the rows were written. This runs
    #    as the migration role (superuser), which sees every tenant's rows
    #    regardless of RLS -- required here, and the only place it is.
    rows = conn.execute(sa.text("""
        SELECT id, tenant_id, actor, action, resource_type, resource_id,
               payload, ip_address, created_at
        FROM audit_logs
        ORDER BY tenant_id, created_at, id
    """)).mappings().all()

    prev_by_tenant: dict = {}
    for r in rows:
        prev = prev_by_tenant.get(r["tenant_id"], GENESIS)
        row_hash = compute_row_hash(dict(r), prev)
        conn.execute(sa.text("""
            UPDATE audit_logs
               SET chain_seq = nextval('audit_logs_chain_seq'),
                   prev_hash = :prev, row_hash = :h
             WHERE id = :id
        """), {"prev": prev, "h": row_hash, "id": r["id"]})
        prev_by_tenant[r["tenant_id"]] = row_hash

    # 3. Append-only, AFTER the backfill's UPDATEs -- order matters.
    op.execute(TRIGGER_FN)
    op.execute(TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.drop_constraint("uq_audit_logs_chain_seq", "audit_logs", type_="unique")
    op.drop_column("audit_logs", "row_hash")
    op.drop_column("audit_logs", "prev_hash")
    op.drop_column("audit_logs", "chain_seq")
    op.execute("DROP SEQUENCE IF EXISTS audit_logs_chain_seq")
