"""The audit log is append-only and hash-chained (Item #9).

Before this, audit_logs was a plain table: no constraint stopped an UPDATE or
DELETE, and nothing linked rows together, so a row could be altered or
removed with no trace. Measured first, then fixed:

  * A BEFORE UPDATE OR DELETE trigger raises for every role. Tested on a
    scratch table before touching the real one: the superuser dataops_user
    (SUPERUSER + BYPASSRLS) is blocked too -- a trigger is code that runs on
    the statement, and BYPASSRLS skips policies, not triggers. The only way
    past it is an explicit `SET session_replication_role = replica` or
    `ALTER TABLE ... DISABLE TRIGGER`, both denied to the app role.
  * Each tenant's rows form a hash chain: row_hash covers the row's content
    plus the previous row's row_hash. Altering row N invalidates every row
    after it, and the trigger stops the rewrite that would repair it.

These tests prove both at the level that matters: raw SQL against Postgres
for the trigger, and a real in-place tamper (using the superuser bypass a
determined attacker with database access would use) for the chain.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from config import settings
from modules.governance.audit_trail import AuditTrail
from services.audit_chain import GENESIS, compute_row_hash, verify_rows
from services.tenant_context import tenant_session


async def _register(client) -> str:
    r = await client.post("/api/v1/auth/register", json={
        "email": f"audit-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Audit", "tenant_name": "Audit Corp",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["tenant_id"]


def _admin():
    return create_engine(settings.ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")


def _rows(tenant_id):
    with _admin().connect() as c:
        return [dict(r) for r in c.execute(text("""
            SELECT id, tenant_id, actor, action, resource_type, resource_id, payload,
                   ip_address, created_at, chain_seq, prev_hash, row_hash
            FROM audit_logs WHERE tenant_id = :t ORDER BY chain_seq
        """), {"t": tenant_id}).mappings()]


async def _log(tenant_id, n=3):
    trail = AuditTrail(tenant_id)
    for i in range(n):
        out = await trail.log_action(actor="tester", action=f"test.step_{i}",
                                     resource_type="probe", resource_id=str(i),
                                     payload={"i": i, "nested": {"z": [1, 2]}})
        assert out.get("logged") is True, out


# ── Append-only, proven by Postgres itself ───────────────────────────────────

@pytest.mark.asyncio
async def test_raw_update_is_rejected_by_the_database(client):
    tenant_id = await _register(client)
    await _log(tenant_id, 1)
    # Selected by this test's own action, not position [0] -- registration
    # itself now writes a user.registered row ahead of it in the chain
    # (identity-audit PR, 2026-09-30).
    row_id = next(r for r in _rows(tenant_id) if r["action"] == "test.step_0")["id"]
    with _admin().connect() as c:
        with pytest.raises(Exception) as exc:
            c.execute(text("UPDATE audit_logs SET action = 'forged' WHERE id = :id"), {"id": row_id})
    assert "append-only" in str(exc.value)
    after = next(r for r in _rows(tenant_id) if r["id"] == row_id)
    assert after["action"] == "test.step_0"


@pytest.mark.asyncio
async def test_raw_delete_is_rejected_by_the_database(client):
    tenant_id = await _register(client)
    await _log(tenant_id, 1)
    rows_before = _rows(tenant_id)
    # Depends on _log() writing AFTER registration, so this test's own row
    # is always the chain's newest -- if a future change ever made _log()
    # (or the registration call above) run in the other order, this needs
    # to be picked by action instead, the way the update test just above
    # already is.
    row_id = rows_before[-1]["id"]
    before_count = len(rows_before)
    with _admin().connect() as c:
        with pytest.raises(Exception) as exc:
            c.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": row_id})
    assert "append-only" in str(exc.value)
    # Relative to what existed before the (rejected) delete, not an absolute
    # count -- registration may contribute 0 or more rows of its own ahead
    # of this test's single row.
    assert len(_rows(tenant_id)) == before_count


@pytest.mark.asyncio
async def test_trigger_blocks_the_superuser_not_just_the_app_role(client):
    """The test that would have been wrong to skip. ADMIN_DATABASE_URL is
    dataops_user: SUPERUSER, BYPASSRLS. If triggers behaved like RLS this
    would succeed. It does not."""
    tenant_id = await _register(client)
    await _log(tenant_id, 1)
    with _admin().connect() as c:
        who = c.execute(text("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")).one()
        assert who[1] is True, "precondition: this connection must be the superuser"
        with pytest.raises(Exception) as exc:
            c.execute(text("DELETE FROM audit_logs WHERE tenant_id = :t"), {"t": tenant_id})
    assert "append-only" in str(exc.value)


@pytest.mark.asyncio
async def test_app_role_cannot_disable_the_trigger(client):
    """The bypass exists but is a superuser privilege; the role the app runs
    as is denied both routes to it."""
    tenant_id = await _register(client)
    await _log(tenant_id, 1)
    app = create_engine(settings.SYNC_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with app.connect() as c:
        with pytest.raises(Exception) as e1:
            c.execute(text("SET session_replication_role = replica"))
        assert "permission denied" in str(e1.value)
        with pytest.raises(Exception) as e2:
            c.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_no_update_delete"))
        assert "must be owner" in str(e2.value)


# ── The chain ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_rows_chain_from_genesis_and_verify(client):
    """Runs over the WHOLE tenant chain, not just this test's own 3 rows --
    the registration row (user.registered, since the identity-audit PR,
    2026-09-30) is genuinely part of the chain, and genesis-linkage/
    sequential hashing are real properties of the chain as a whole, not of
    any one test's own contribution to it."""
    tenant_id = await _register(client)
    await _log(tenant_id, 3)
    rows = _rows(tenant_id)
    assert len(rows) >= 3  # this test's own 3, plus whatever registration wrote
    assert rows[0]["prev_hash"] == GENESIS, "a tenant's first row links to the sentinel"
    for i in range(len(rows) - 1):
        assert rows[i + 1]["prev_hash"] == rows[i]["row_hash"]
        assert rows[i]["chain_seq"] < rows[i + 1]["chain_seq"]
    report = verify_rows(rows)
    assert report["ok"], report["breaks"]
    assert report["rows"] == len(rows) and report["unchained"] == 0
    assert report["tail_hash"] == rows[-1]["row_hash"]


@pytest.mark.asyncio
async def test_stored_hash_is_exactly_what_the_documented_function_produces(client):
    """Pins the hash definition: if compute_row_hash ever changes, every
    stored hash becomes wrong and this fails immediately rather than the
    first time a reviewer runs the verifier. Checked over the whole chain
    (registration row included), not just this test's own 2 rows -- same
    reasoning as test_new_rows_chain_from_genesis_and_verify above."""
    tenant_id = await _register(client)
    await _log(tenant_id, 2)
    prev = GENESIS
    for row in _rows(tenant_id):
        assert compute_row_hash(row, prev) == row["row_hash"]
        prev = row["row_hash"]


def test_hash_is_deterministic_and_key_order_independent():
    base = {"id": "x", "tenant_id": "t", "actor": "a", "action": "act",
            "resource_type": None, "resource_id": None, "ip_address": None,
            "created_at": "2026-09-12T10:00:00.000001",
            "payload": {"b": 1, "a": {"z": [1, 2], "y": "q"}}}
    reordered = dict(reversed(list(base.items())))
    reordered["payload"] = {"a": {"y": "q", "z": [1, 2]}, "b": 1}
    assert compute_row_hash(base, GENESIS) == compute_row_hash(reordered, GENESIS)
    assert compute_row_hash(base, GENESIS) != compute_row_hash({**base, "action": "other"}, GENESIS)
    assert compute_row_hash(base, GENESIS) != compute_row_hash(base, "1" * 64)


def _tamper(sql, params):
    """What a determined attacker with superuser database access would do:
    disable triggers for the session, then write. This is the ONLY way past
    the trigger, and it is exactly the scenario the chain exists to catch."""
    with _admin().connect() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text(sql), params)


@pytest.mark.asyncio
async def test_in_place_content_tamper_is_detected(client):
    tenant_id = await _register(client)
    await _log(tenant_id, 3)
    victim = _rows(tenant_id)[1]
    _tamper("UPDATE audit_logs SET action = 'forged' WHERE id = :id", {"id": victim["id"]})

    report = verify_rows(_rows(tenant_id))
    assert not report["ok"]
    kinds = {(b.chain_seq, b.kind) for b in report["breaks"]}
    assert (victim["chain_seq"], "content") in kinds, report["breaks"]


@pytest.mark.asyncio
async def test_deleting_a_middle_row_is_detected(client):
    tenant_id = await _register(client)
    await _log(tenant_id, 3)
    rows = _rows(tenant_id)
    _tamper("DELETE FROM audit_logs WHERE id = :id", {"id": rows[1]["id"]})

    report = verify_rows(_rows(tenant_id))
    assert not report["ok"]
    # Row 3 now follows row 1 directly, but still points at the vanished row 2.
    assert any(b.kind == "link" and b.chain_seq == rows[2]["chain_seq"]
               for b in report["breaks"]), report["breaks"]


@pytest.mark.asyncio
async def test_tampering_the_last_row_is_detected(client):
    """With only prev_hash, the final row would be unprotected -- nothing
    chains after it. Storing row_hash is what makes this catchable."""
    tenant_id = await _register(client)
    await _log(tenant_id, 2)
    last = _rows(tenant_id)[-1]
    _tamper("UPDATE audit_logs SET payload = '{\"i\": 99}'::json WHERE id = :id", {"id": last["id"]})

    report = verify_rows(_rows(tenant_id))
    assert not report["ok"]
    assert any(b.kind == "content" and b.chain_seq == last["chain_seq"] for b in report["breaks"])


@pytest.mark.asyncio
async def test_forging_prev_hash_to_hide_a_tamper_still_fails(client):
    """An attacker who edits row N and then edits row N+1's prev_hash to
    match is caught by row N+1's CONTENT check, because prev_hash is inside
    N+1's own hash. Repairing that means recomputing every later row_hash --
    a full re-forge, which is what the anchored tail hash catches."""
    tenant_id = await _register(client)
    await _log(tenant_id, 3)
    # The last 3 rows, not the first 3 -- depends on _log() writing AFTER
    # registration, so this test's own rows are always the chain's tail
    # regardless of whatever registration wrote ahead of them. If a future
    # change ever made _log() (or the registration call above) run in the
    # other order, this needs to pick rows by action instead.
    r0, r1, r2 = _rows(tenant_id)[-3:]
    forged_r1 = compute_row_hash({**r1, "action": "forged"}, r1["prev_hash"])
    _tamper("UPDATE audit_logs SET action = 'forged', row_hash = :h WHERE id = :id",
            {"h": forged_r1, "id": r1["id"]})
    _tamper("UPDATE audit_logs SET prev_hash = :p WHERE id = :id",
            {"p": forged_r1, "id": r2["id"]})

    report = verify_rows(_rows(tenant_id))
    assert not report["ok"]
    assert any(b.kind == "content" and b.chain_seq == r2["chain_seq"] for b in report["breaks"])


@pytest.mark.asyncio
async def test_verifier_script_flags_a_break_and_exits_nonzero(client):
    """The standalone tool, end to end, since it is what a reviewer runs."""
    import scripts.verify_audit_chain as vac

    tenant_id = await _register(client)
    await _log(tenant_id, 2)
    assert vac.main([tenant_id]) == 0

    victim = _rows(tenant_id)[0]
    _tamper("UPDATE audit_logs SET actor = 'mallory' WHERE id = :id", {"id": victim["id"]})
    assert vac.main([tenant_id]) == 1
