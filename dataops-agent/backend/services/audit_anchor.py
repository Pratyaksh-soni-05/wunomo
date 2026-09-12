"""External anchoring of the audit chain's tail hash (Item #9 follow-up).

    WHY THIS EXISTS
    ---------------
    The hash chain proves a tenant's audit rows are internally consistent.
    It cannot, by itself, prove they were not rewritten wholesale: the
    algorithm is public, and a superuser who disables the append-only
    trigger can alter row N and recompute every hash after it, at which
    point the verifier reports the re-forged chain as intact -- because,
    internally, it is.

    The only defence is a record of the tail hash held where the database
    has no power over it. Once yesterday's tail hash is sitting in an inbox,
    a chain re-forged today cannot produce it again: the old hash covered
    content that no longer exists. That is what this module records, once
    a day, for every tenant.

WHAT IS RECORDED

For each tenant: tenant_id, chain_seq of the last row, the tail row_hash,
the row count, the verifier's verdict for that chain, and the time. The
verdict is included deliberately -- an anchor email that says BROKEN is the
alert this whole item exists to produce, and a verifier run happens here
anyway because the tail hash of an unverified chain is not worth anchoring.

WHERE

  1. Email, to ANCHOR_NOTIFICATION_EMAIL, through the SMTP path
     NotificationService already uses for incident and staleness alerts.
     This is the real anchor: a mailbox is outside this database's reach.
  2. A local append-only file, as a convenience trail. This is NOT an
     anchor -- whoever controls the host controls the file -- and the
     docstring on append_anchor_file says so.

WHAT THIS DOES NOT DO

It does not retroactively prove anything about the chain before its first
run. Integrity against re-forging is proven from the first anchor forward.

The tail hash is read through the same code path the verifier uses
(audit_chain.verify_rows over the tenant's rows in chain_seq order), so the
anchored value is by construction what a reviewer running the verifier
would see. There is no second computation of the hash anywhere.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import create_engine, text

from config import settings
from services.audit_chain import verify_rows

log = structlog.get_logger()

ANCHOR_SUBJECT = "[AXIOM] audit chain anchors {date}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _tenant_rows(conn, tenant_id: str):
    return [dict(r) for r in conn.execute(text("""
        SELECT id, tenant_id, actor, action, resource_type, resource_id,
               payload, ip_address, created_at, chain_seq, prev_hash, row_hash
        FROM audit_logs
        WHERE tenant_id = :t
        ORDER BY chain_seq NULLS FIRST, created_at, id
    """), {"t": tenant_id}).mappings()]


def compute_anchors(conn=None) -> list[dict]:
    """One record per tenant that has at least one audit row.

    Tenants with no rows are skipped rather than recorded: there is no chain
    to anchor and a "tail hash" of nothing would be a lie. Reads as the
    maintenance role because the table is RLS-scoped and every tenant must
    be seen; read-only.
    """
    own = conn is None
    if own:
        engine = create_engine(settings.ADMIN_DATABASE_URL)
        conn = engine.connect()
    try:
        tenant_ids = [r[0] for r in conn.execute(
            text("SELECT DISTINCT tenant_id FROM audit_logs ORDER BY 1"))]
        records = []
        now = utcnow()
        for tid in tenant_ids:
            rows = _tenant_rows(conn, tid)
            if not rows:
                continue
            report = verify_rows(rows)
            if report["tail_hash"] is None:
                # Every row unchained -- nothing verifiable to anchor.
                log.warning("audit_anchor.tenant_unchained", tenant_id=tid, rows=len(rows))
                continue
            last = rows[-1]
            records.append({
                "tenant_id": tid,
                "chain_seq": last["chain_seq"],
                "tail_hash": report["tail_hash"],
                "rows": report["rows"],
                "ok": report["ok"],
                "breaks": len(report["breaks"]),
                "anchored_at": now.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            })
        return records
    finally:
        if own:
            conn.close()


def format_anchor_email(records: list[dict]) -> str:
    """Plain text on purpose: the whole point is that a human, or a script,
    can read the hash back out of a mailbox months later. No markup to
    strip, one record per line, JSON so it round-trips."""
    lines = [
        "AXIOM audit chain anchors.",
        "Each line is one tenant's chain tail at the time shown. Keep this",
        "message: a chain re-forged after this point cannot reproduce these",
        "hashes, and scripts/verify_audit_chain.py prints the current tail",
        "for comparison.",
        "",
    ]
    lines += [json.dumps(r, sort_keys=True) for r in records]
    broken = [r for r in records if not r["ok"]]
    if broken:
        lines += ["", f"ATTENTION: {len(broken)} chain(s) FAILED verification:"]
        lines += [f"  tenant {r['tenant_id']}  breaks={r['breaks']}" for r in broken]
    return "\n".join(lines)


def append_anchor_file(records: list[dict], path: str | None = None) -> Path:
    """Convenience trail only. This file lives on the same host as the
    database and is exactly as trustworthy as that host -- it is a second
    copy for a reviewer's convenience, not an anchor. The email is the
    anchor."""
    p = Path(path or settings.AUDIT_ANCHOR_LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return p


async def anchor_audit_chains(send_email=None) -> dict:
    """The daily job. Returns a summary so the task can log it.

    `send_email` is injectable so tests can capture the message instead of
    opening an SMTP connection; the default is NotificationService's real
    sender.
    """
    records = compute_anchors()
    summary = {"tenants": len(records), "broken": sum(1 for r in records if not r["ok"]),
               "emailed": False, "file": None}
    if not records:
        log.info("audit_anchor.nothing_to_anchor")
        return summary

    summary["file"] = str(append_anchor_file(records))

    to = (settings.ANCHOR_NOTIFICATION_EMAIL or "").strip()
    if not to:
        # Loud, every day, until it is configured: an unanchored chain is the
        # gap this task exists to close, and a silently skipped send would
        # hide that the gap is still open.
        log.error("audit_anchor.no_destination",
                  hint="set ANCHOR_NOTIFICATION_EMAIL; the local file is not an anchor")
        return summary

    if send_email is None:
        from modules.reporting.notification_service import NotificationService
        # The service is tenant-scoped for alert routing; anchoring is
        # platform-level, so any tenant id satisfies the constructor and no
        # per-tenant preference is consulted by send_email itself.
        send_email = NotificationService("platform").send_email

    result = await send_email(
        to=to,
        subject=ANCHOR_SUBJECT.format(date=records[0]["anchored_at"][:10]),
        body=format_anchor_email(records),
        html=False,
    )
    summary["emailed"] = not (isinstance(result, dict) and result.get("error"))
    if not summary["emailed"]:
        log.error("audit_anchor.email_failed", error=(result or {}).get("error"))
    return summary
