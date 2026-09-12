"""Verify the audit log's hash chain. The tool a compliance reviewer runs.

    docker compose exec backend python scripts/verify_audit_chain.py             # every tenant
    docker compose exec backend python scripts/verify_audit_chain.py <tenant_id> # one tenant
    docker compose exec backend python scripts/verify_audit_chain.py --json      # machine-readable

Exit code 0 when every chain verifies, 1 when any break is found, 2 on a
usage or connection error -- so it can sit in a cron job or a CI step and
fail the build.

It connects as ADMIN_DATABASE_URL, because the audit table is RLS-scoped and
verifying every tenant means reading every tenant. That is a read-only use
of the maintenance role; the script issues no writes.

WHAT IT CHECKS, PER TENANT

Walks the rows in chain_seq order and, for each, recomputes the hash with the
exact function the writer used (services/audit_chain.py -- there is no second
implementation) and checks three things independently:

  content   stored row_hash == recompute(row content, stored prev_hash)
  link      stored prev_hash == the previous row's stored row_hash
  genesis   the first row's prev_hash is the GENESIS sentinel

Any mismatch is reported with the chain_seq and row id, and which check
failed, because "the chain is broken" is not actionable and "row 37's content
does not match its hash" is.

WHAT THE OUTPUT MEANS

  tail hash   the last row_hash in the chain. Record it somewhere this
              database cannot reach (a ticket, a signed file, another
              system). Next time, verify that the chain still ends in a row
              whose hash matches -- that is what catches a superuser who
              disables the trigger and re-forges the whole chain, which the
              chain alone cannot.
  unchained   rows with no hash at all. There should be none after the
              backfill migration; if there are, they were inserted by
              something that bypassed AuditTrail.log_action and they are
              reported as unverifiable rather than as intact.
  chained from  the earliest created_at in the chain. Integrity is proven
              from the moment each row was CHAINED, which for backfilled rows
              is the migration date, not the row date.
"""
import json
import os
import sys

# Runnable from the backend root or from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from config import settings  # noqa: E402
from services.audit_chain import verify_rows  # noqa: E402


def _fetch(conn, tenant_id):
    return conn.execute(text("""
        SELECT id, tenant_id, actor, action, resource_type, resource_id,
               payload, ip_address, created_at, chain_seq, prev_hash, row_hash
        FROM audit_logs
        WHERE tenant_id = :t
        ORDER BY chain_seq NULLS FIRST, created_at, id
    """), {"t": tenant_id}).mappings().all()


def verify_tenant(conn, tenant_id):
    rows = [dict(r) for r in _fetch(conn, tenant_id)]
    report = verify_rows(rows)
    report["tenant_id"] = tenant_id
    report["chained_from"] = min((r["created_at"] for r in rows if r["row_hash"]), default=None)
    return report


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]

    try:
        engine = create_engine(settings.ADMIN_DATABASE_URL)
        with engine.connect() as conn:
            if args:
                tenant_ids = args
            else:
                tenant_ids = [r[0] for r in conn.execute(
                    text("SELECT DISTINCT tenant_id FROM audit_logs ORDER BY 1"))]
            reports = [verify_tenant(conn, t) for t in tenant_ids]
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    any_break = any(not r["ok"] for r in reports)

    if as_json:
        out = [{**r, "breaks": [{"chain_seq": b.chain_seq, "row_id": b.row_id,
                                  "kind": b.kind, "detail": b.detail} for b in r["breaks"]],
                "chained_from": r["chained_from"].isoformat() if r["chained_from"] else None}
               for r in reports]
        print(json.dumps(out, indent=2, default=str))
        return 1 if any_break else 0

    for r in reports:
        status = "OK     " if r["ok"] else "BROKEN "
        print(f"{status} tenant {r['tenant_id']}  rows={r['rows']}  "
              f"unchained={r['unchained']}  chained from {r['chained_from']}")
        if r["tail_hash"]:
            print(f"        tail hash {r['tail_hash']}")
        for b in r["breaks"]:
            print(f"        !! seq {b.chain_seq} row {b.row_id}: {b.kind} -- {b.detail}")

    print()
    print(f"{len(reports)} tenant chain(s) checked: "
          f"{sum(1 for r in reports if r['ok'])} ok, "
          f"{sum(1 for r in reports if not r['ok'])} broken")
    return 1 if any_break else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
