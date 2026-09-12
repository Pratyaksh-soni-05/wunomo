"""Hash chain for the audit log (Item #9).

    THE ONE RULE OF THIS MODULE
    ---------------------------
    compute_row_hash() is the single definition of the hash. The writer
    (AuditTrail.log_action), the backfill in the migration, and the
    verification utility all call this exact function. There is no second
    implementation to drift from it, and there must never be one: a verifier
    that recomputes the hash differently from the writer reports every row as
    tampered, and a verifier that recomputes it more loosely misses tampering.

EXACT HASH DEFINITION

    row_hash = SHA-256( canonical_json(record) )

where `record` is a dict with EXACTLY these keys, in this order after
sort_keys (alphabetical, so the order below is the serialized order):

    action        str
    actor         str | null
    created_at    ISO-8601 with microseconds, naive UTC, e.g. "2026-09-12T10:15:30.123456"
    id            str (the row's own uuid)
    ip_address    str | null
    payload       the JSON payload, itself canonicalised recursively
    prev_hash     64 hex chars — the previous row's row_hash, or GENESIS
    resource_id   str | null
    resource_type str | null
    tenant_id     str

and canonical_json is json.dumps(record, sort_keys=True,
separators=(",", ":"), ensure_ascii=False, default=str). No whitespace,
keys sorted at every nesting level, UTF-8, no NaN/Infinity (json.dumps
rejects them by default once allow_nan=False — set explicitly below).

Excluded deliberately: chain_seq and row_hash. chain_seq is a database
sequence assigned at insert time and is ORDER metadata, not content — the
chain is walked in chain_seq order, so it does not also need to be inside
the hash. row_hash is the output.

WHY THE CHAIN IS PER TENANT

Every AuditLog row belongs to one tenant, and rows are RLS-scoped: the
application role can only ever see one tenant's rows. A single global chain
would be unverifiable from inside the app, and would be broken permanently
the first time any tenant's data was ever removed (offboarding, test
teardown). So each tenant has its own chain: its first row links to
GENESIS, every later row links to the tenant's previous row, and removing a
whole tenant removes a whole chain cleanly. A compliance reviewer verifies a
tenant, which is also the unit they are reviewing.

FIRST ROW

A tenant's first row has prev_hash = GENESIS, sixty-four zero characters.
That is a real, explicit value that is hashed like any other, so the first
row is as protected as every subsequent one — its row_hash covers the
sentinel, and a tampered first row fails verification the same way.

WHAT THIS DOES AND DOES NOT PROVE

The append-only trigger stops UPDATE and DELETE for every role except a
superuser who explicitly disables triggers. The chain makes tampering
DETECTABLE even where it cannot be prevented: altering row N changes its
row_hash, so row N+1's stored prev_hash no longer matches, and so on to the
end. Repairing that means rewriting every later row, which the trigger
blocks. What the chain does not do is authenticate against an attacker who
has superuser access AND the will to re-forge the whole chain after
disabling triggers — the algorithm is public, so they can. Closing that
needs the latest row_hash anchored somewhere that access cannot reach
(exported, signed, or written to a separate system). That is the next step,
not this one, and the verifier prints the tail hash so it can be anchored.
"""

import hashlib
import json
from datetime import datetime
from typing import Iterable, Optional

GENESIS = "0" * 64

# The content fields, and their order in the serialized record is fixed by
# sort_keys, not by this tuple — this exists so the writer and the backfill
# cannot accidentally include or omit a field.
HASHED_FIELDS = (
    "action", "actor", "created_at", "id", "ip_address",
    "payload", "prev_hash", "resource_id", "resource_type", "tenant_id",
)


def _canonical(value):
    """Make a payload byte-stable: JSON with sorted keys at every level."""
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        # Naive UTC throughout this codebase (Hard Rule 3). Microseconds are
        # always written so two timestamps never serialize differently for
        # the same instant.
        return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")
    return str(ts)


def compute_row_hash(row: dict, prev_hash: str) -> str:
    """The hash. `row` is a dict of the AuditLog columns (or an AuditLog
    object's attributes); `prev_hash` is the previous row's row_hash or
    GENESIS. See the module docstring for the exact definition."""
    record = {
        "action": row.get("action"),
        "actor": row.get("actor"),
        "created_at": _iso(row.get("created_at")),
        "id": row.get("id"),
        "ip_address": row.get("ip_address"),
        "payload": _canonical(row.get("payload") if row.get("payload") is not None else {}),
        "prev_hash": prev_hash,
        "resource_id": row.get("resource_id"),
        "resource_type": row.get("resource_type"),
        "tenant_id": row.get("tenant_id"),
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def row_to_dict(entry) -> dict:
    """AuditLog ORM object -> the dict compute_row_hash expects."""
    return {f: getattr(entry, f) for f in HASHED_FIELDS if f != "prev_hash"}


# ── Verification ─────────────────────────────────────────────────────────────

class ChainBreak:
    __slots__ = ("chain_seq", "row_id", "kind", "detail")

    def __init__(self, chain_seq, row_id, kind, detail):
        self.chain_seq, self.row_id, self.kind, self.detail = chain_seq, row_id, kind, detail

    def __repr__(self):
        return f"ChainBreak(seq={self.chain_seq}, id={self.row_id}, {self.kind}: {self.detail})"


def verify_rows(rows: Iterable) -> dict:
    """Walk one tenant's rows in chain_seq order and report every break.

    `rows` are AuditLog objects (or dicts with the same fields) ALREADY sorted
    by chain_seq ascending and all belonging to one tenant. Returns a report:

        {"rows": n, "ok": bool, "breaks": [ChainBreak, ...],
         "tail_hash": str | None, "unchained": n}

    Three kinds of break, each checked independently so a report says what
    is wrong rather than just that something is:

      content     the row's stored row_hash != recompute(row, stored prev_hash)
                  -> this row's content (or its prev_hash) was altered
      link        the row's stored prev_hash != the previous row's row_hash
                  -> a row was inserted, removed, or reordered before this one
      genesis     the first row's prev_hash is not GENESIS

    `unchained` counts rows with no row_hash at all — rows written before the
    chain existed and never backfilled. They are reported, not failed: the
    verifier's job is to say exactly what it can and cannot vouch for.
    """
    breaks = []
    expected_prev = GENESIS
    last_hash = None
    n = 0
    unchained = 0
    first = True

    for r in rows:
        get = (lambda k: r.get(k)) if isinstance(r, dict) else (lambda k: getattr(r, k))
        n += 1
        stored_prev, stored_hash, seq, rid = get("prev_hash"), get("row_hash"), get("chain_seq"), get("id")

        if stored_hash is None:
            unchained += 1
            first = False
            continue

        if first and stored_prev != GENESIS:
            breaks.append(ChainBreak(seq, rid, "genesis",
                                     f"first row prev_hash is {stored_prev!r}, expected GENESIS"))
        first = False

        if stored_prev != expected_prev:
            breaks.append(ChainBreak(seq, rid, "link",
                                     f"prev_hash {stored_prev[:12]}… does not match previous "
                                     f"row's hash {expected_prev[:12]}…"))

        rowdict = r if isinstance(r, dict) else row_to_dict(r)
        recomputed = compute_row_hash(rowdict, stored_prev)
        if recomputed != stored_hash:
            breaks.append(ChainBreak(seq, rid, "content",
                                     f"stored {stored_hash[:12]}… recomputed {recomputed[:12]}…"))

        expected_prev = stored_hash
        last_hash = stored_hash

    return {"rows": n, "ok": not breaks, "breaks": breaks,
            "tail_hash": last_hash, "unchained": unchained}
