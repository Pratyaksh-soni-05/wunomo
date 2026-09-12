"""The daily audit-chain anchor (Item #9 follow-up).

The hash chain proves internal consistency. A superuser who disables the
append-only trigger can rewrite a row and recompute every later hash, and the
verifier will then call the re-forged chain intact. The only defence is a
record of the tail hash held outside the database, taken regularly, so that a
chain re-forged later cannot reproduce an already-recorded value.

These tests prove the job records the RIGHT value -- the same tail hash the
standalone verifier independently computes -- delivers it through the real
email path (mocked at the SMTP boundary, never sent), writes the convenience
file, and skips tenants with no chain instead of failing the whole run.
"""

import json
import uuid

import pytest
from sqlalchemy import create_engine, text

import scripts.verify_audit_chain as vac
from config import settings
from modules.governance.audit_trail import AuditTrail
from services import audit_anchor
from services.audit_anchor import (
    anchor_audit_chains,
    append_anchor_file,
    compute_anchors,
    format_anchor_email,
)


async def _register(client) -> str:
    r = await client.post("/api/v1/auth/register", json={
        "email": f"anchor-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Anchor", "tenant_name": "Anchor Corp",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["tenant_id"]


async def _log(tenant_id, n):
    trail = AuditTrail(tenant_id)
    for i in range(n):
        out = await trail.log_action(actor="t", action=f"anchor.step_{i}",
                                     resource_type="probe", resource_id=str(i), payload={"i": i})
        assert out.get("logged") is True, out


def _tail_from_db(tenant_id):
    with create_engine(settings.ADMIN_DATABASE_URL).connect() as c:
        return c.execute(text("""
            SELECT chain_seq, row_hash FROM audit_logs
            WHERE tenant_id = :t ORDER BY chain_seq DESC LIMIT 1
        """), {"t": tenant_id}).one()


@pytest.mark.asyncio
async def test_anchor_matches_what_the_verifier_independently_computes(client):
    """The property that makes the anchor worth anything: the recorded hash
    is exactly the one a reviewer would get from the verifier, and exactly
    the one stored on the last row."""
    tenant_id = await _register(client)
    await _log(tenant_id, 4)

    record = next(r for r in compute_anchors() if r["tenant_id"] == tenant_id)

    with create_engine(settings.ADMIN_DATABASE_URL).connect() as c:
        verifier_report = vac.verify_tenant(c, tenant_id)
    seq, stored_tail = _tail_from_db(tenant_id)

    assert record["tail_hash"] == verifier_report["tail_hash"] == stored_tail
    assert record["chain_seq"] == seq
    assert record["rows"] == 4 and record["ok"] is True and record["breaks"] == 0
    assert len(record["tail_hash"]) == 64


@pytest.mark.asyncio
async def test_job_emails_the_records_and_appends_the_file(client, tmp_path, monkeypatch):
    tenant_id = await _register(client)
    await _log(tenant_id, 2)
    tail = _tail_from_db(tenant_id)[1]

    monkeypatch.setattr(settings, "ANCHOR_NOTIFICATION_EMAIL", "compliance@example.com")
    monkeypatch.setattr(settings, "AUDIT_ANCHOR_LOG_PATH", str(tmp_path / "anchors.log"))

    sent = {}

    async def fake_send(to, subject, body, html=True, cc=None):
        sent.update(to=to, subject=subject, body=body, html=html)
        return {"sent": True}

    summary = await anchor_audit_chains(send_email=fake_send)

    assert summary["emailed"] is True
    assert summary["tenants"] >= 1 and summary["broken"] == 0
    assert sent["to"] == "compliance@example.com"
    assert sent["html"] is False, "plain text, so the hash can be read back out of a mailbox"
    assert subject_has_date(sent["subject"])
    assert tail in sent["body"], "the tenant's tail hash must be in the email body"
    assert tenant_id in sent["body"]

    lines = (tmp_path / "anchors.log").read_text().splitlines()
    mine = [json.loads(l) for l in lines if tenant_id in l]
    assert len(mine) == 1 and mine[0]["tail_hash"] == tail


def subject_has_date(subject: str) -> bool:
    import re
    return bool(re.search(r"\d{4}-\d{2}-\d{2}", subject))


@pytest.mark.asyncio
async def test_email_body_round_trips_as_json_per_line(client):
    tenant_id = await _register(client)
    await _log(tenant_id, 1)
    records = [r for r in compute_anchors() if r["tenant_id"] == tenant_id]
    body = format_anchor_email(records)
    parsed = [json.loads(l) for l in body.splitlines() if l.startswith("{")]
    assert parsed == records, "a reviewer must be able to parse the hash straight back out"


@pytest.mark.asyncio
async def test_tenant_with_no_audit_rows_is_skipped_not_fatal(client):
    """A freshly registered tenant has a tenant row and zero audit rows. The
    job must skip it -- there is no chain to anchor -- and still anchor
    everyone else."""
    empty_tenant = await _register(client)
    full_tenant = await _register(client)
    await _log(full_tenant, 1)

    records = compute_anchors()
    ids = {r["tenant_id"] for r in records}
    assert full_tenant in ids
    assert empty_tenant not in ids


@pytest.mark.asyncio
async def test_missing_destination_still_writes_file_and_reports_not_emailed(
        client, tmp_path, monkeypatch):
    """Unconfigured is loud, not silent: the summary says it was not emailed
    and the ERROR log fires every run until ANCHOR_NOTIFICATION_EMAIL is set."""
    tenant_id = await _register(client)
    await _log(tenant_id, 1)
    monkeypatch.setattr(settings, "ANCHOR_NOTIFICATION_EMAIL", "")
    monkeypatch.setattr(settings, "AUDIT_ANCHOR_LOG_PATH", str(tmp_path / "anchors.log"))

    async def must_not_be_called(**kw):
        raise AssertionError("send_email called with no destination configured")

    summary = await anchor_audit_chains(send_email=must_not_be_called)
    assert summary["emailed"] is False
    assert (tmp_path / "anchors.log").exists()


@pytest.mark.asyncio
async def test_a_reforged_chain_cannot_reproduce_an_earlier_anchor(client):
    """The reason anchoring exists, demonstrated: anchor, then tamper and
    re-forge every hash so the verifier is fooled, then show the new tail
    differs from the anchored one."""
    from services.audit_chain import compute_row_hash

    tenant_id = await _register(client)
    await _log(tenant_id, 3)
    anchored = next(r for r in compute_anchors() if r["tenant_id"] == tenant_id)["tail_hash"]

    # Superuser re-forge: alter row 1, recompute rows 1..3 in order.
    eng = create_engine(settings.ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("SET session_replication_role = replica"))
        rows = [dict(r) for r in c.execute(text("""
            SELECT id, tenant_id, actor, action, resource_type, resource_id, payload,
                   ip_address, created_at, chain_seq, prev_hash, row_hash
            FROM audit_logs WHERE tenant_id = :t ORDER BY chain_seq"""), {"t": tenant_id}).mappings()]
        rows[0]["action"] = "forged"
        prev = rows[0]["prev_hash"]
        for r in rows:
            r["prev_hash"] = prev
            r["row_hash"] = compute_row_hash(r, prev)
            c.execute(text("UPDATE audit_logs SET action=:a, prev_hash=:p, row_hash=:h WHERE id=:id"),
                      {"a": r["action"], "p": r["prev_hash"], "h": r["row_hash"], "id": r["id"]})
            prev = r["row_hash"]
        c.execute(text("RESET session_replication_role"))

    # The verifier is fooled -- internally consistent...
    with create_engine(settings.ADMIN_DATABASE_URL).connect() as c:
        assert vac.verify_tenant(c, tenant_id)["ok"] is True
    # ...but the anchored tail hash is now unreproducible.
    reforged = next(r for r in compute_anchors() if r["tenant_id"] == tenant_id)["tail_hash"]
    assert reforged != anchored


def test_beat_schedule_runs_it_daily():
    from services.celery_app import celery_app
    entry = celery_app.conf.beat_schedule["anchor-audit-chains-24hr"]
    assert entry["task"] == "services.tasks.anchor_audit_chains"
    assert entry["schedule"] == 86400.0


def test_task_is_registered_with_celery():
    from services import tasks
    assert callable(tasks.anchor_audit_chains)
    assert tasks.anchor_audit_chains.name == "services.tasks.anchor_audit_chains"
