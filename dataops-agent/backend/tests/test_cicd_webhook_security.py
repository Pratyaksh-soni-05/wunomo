"""Security Master Ranking Item #16: the GitHub CI/CD webhook had no
working signature verification (GITHUB_WEBHOOK_SECRET was referenced but
never declared on Settings, so the check that read it was permanently a
no-op -- confirmed via git log, present unchanged since the initial
commit) and derived "which tenant" from an unauthenticated X-Tenant-ID
header. See docs/context/GOTCHAS.md for the full writeup.

Fixed: per-pipeline secret, POST /cicd/webhook/{pipeline_id}, tenant
identity taken only from the resolved pipeline row, never a header.
"""
import hashlib
import hmac
import uuid

import pytest
from sqlalchemy import select

from models.all_models import Pipeline, PipelineStatus, User
from models.cicd import PipelineCommit
from services.auth_service import hash_password
from services.tenant_context import tenant_session

pytestmark = pytest.mark.asyncio


async def _register(client, prefix="webhooksec"):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    reg = (await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Owner", "tenant_name": f"Webhook Sec Corp {uuid.uuid4().hex[:6]}",
    })).json()
    return reg["access_token"], reg["tenant_id"], reg["user_id"]


async def _add_viewer(tenant_id: str) -> str:
    """A second member with the viewer role, for the permission-gate test
    -- matches test_privilege_audit_coverage.py's own _add_member helper."""
    email = f"viewer-{uuid.uuid4().hex[:8]}@example.com"
    async with tenant_session(tenant_id) as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=email,
            hashed_password=hash_password("viewerpass123"),
            full_name="Viewer", role="viewer",
        )
        db.add(user)
        await db.commit()
    from services.auth_service import issue_token_for_user
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(User).where(User.email == email))
        return issue_token_for_user(r.scalar_one(), "password")


async def _create_pipeline(client, token: str, name="webhook test pipeline") -> str:
    r = await client.post("/api/v1/pipelines/", json={"name": name}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    data = r.json()
    return data.get("id") or data.get("pipeline_id")


async def _generate_secret(client, token: str, pipeline_id: str) -> dict:
    r = await client.post(f"/api/v1/pipelines/{pipeline_id}/webhook-secret", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _push_body(repo_url="https://github.com/example/repo", sha=None) -> bytes:
    import json as _json
    payload = {
        "ref": "refs/heads/main",
        "after": sha or ("a" * 40),
        "commits": [{"id": "deadbeef", "message": "test push", "added": [], "modified": [], "removed": []}],
        "repository": {"clone_url": repo_url},
        "pusher": {"name": "tester"},
    }
    return _json.dumps(payload).encode("utf-8")


async def _commit_count(tenant_id: str, pipeline_id: str) -> int:
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(PipelineCommit).where(PipelineCommit.pipeline_id == pipeline_id))
        return len(r.scalars().all())


# ── 1. Valid signature ─────────────────────────────────────────────────────

async def test_valid_signature_returns_200_and_creates_commit_under_right_tenant(client):
    token, tenant_id, _ = await _register(client, "validsig")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret_info["webhook_secret"]),
            "X-GitHub-Event": "push", "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["commit_id"]

    async with tenant_session(tenant_id) as db:
        res = await db.execute(select(PipelineCommit).where(PipelineCommit.pipeline_id == pipeline_id))
        rows = res.scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_id


# ── 2. Tampered body ────────────────────────────────────────────────────────

async def test_tampered_body_is_rejected_with_401(client):
    token, tenant_id, _ = await _register(client, "tampered")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    real_body = _push_body()
    signature = _sign(real_body, secret_info["webhook_secret"])
    tampered_body = _push_body(sha="b" * 40)  # signed for a different body

    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=tampered_body,
        headers={
            "X-Hub-Signature-256": signature, "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    assert await _commit_count(tenant_id, pipeline_id) == 0


async def test_tamper_detection_depends_on_verify_signature_actually_running(client, monkeypatch):
    """Negative control: proves the 401 above comes from verify_signature
    doing real work, not from something else (routing, schema validation)
    coincidentally rejecting it. With verify_signature patched to a no-op,
    the identical tampered request that test 2 shows gets rejected today
    is instead ACCEPTED -- demonstrating this is exactly the check that
    would have let a tampered body through on code that never ran it
    (precisely the pre-fix shape: GITHUB_WEBHOOK_SECRET was referenced but
    never wired up, so this exact verification never executed)."""
    import api.v1.cicd as cicd_module

    token, tenant_id, _ = await _register(client, "negctrl")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    monkeypatch.setattr(cicd_module, "verify_signature", lambda *a, **k: None)

    real_body = _push_body()
    signature = _sign(real_body, secret_info["webhook_secret"])
    tampered_body = _push_body(sha="b" * 40)

    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=tampered_body,
        headers={
            "X-Hub-Signature-256": signature, "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, (
        "with verify_signature patched to a no-op, a tampered body should "
        f"be accepted -- got {r.status_code}, meaning something else is "
        "also gating this, which would make the real verify_signature "
        "redundant rather than load-bearing"
    )
    assert await _commit_count(tenant_id, pipeline_id) == 1


# ── 3. Missing signature header ─────────────────────────────────────────────

async def test_missing_signature_header_is_rejected(client):
    token, tenant_id, _ = await _register(client, "missingsig")
    pipeline_id = await _create_pipeline(client, token)
    await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    r = await client.post(f"/api/v1/cicd/webhook/{pipeline_id}", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401
    assert await _commit_count(tenant_id, pipeline_id) == 0


# ── 4. Wrong signature prefix ───────────────────────────────────────────────

async def test_wrong_signature_prefix_is_rejected(client):
    token, tenant_id, _ = await _register(client, "wrongprefix")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    sha1_style = "sha1=" + hmac.new(secret_info["webhook_secret"].encode(), body, hashlib.sha1).hexdigest()
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={"X-Hub-Signature-256": sha1_style, "Content-Type": "application/json"},
    )
    assert r.status_code == 401
    assert await _commit_count(tenant_id, pipeline_id) == 0


# ── 4b. Missing delivery id ─────────────────────────────────────────────────

async def test_missing_delivery_id_is_rejected_before_any_database_access(client, monkeypatch):
    """A well-formed, correctly-signed request with no X-GitHub-Delivery
    header at all is rejected outright -- GitHub always sends this header
    in practice, and accepting a request that omits it would mean replay
    protection could never apply to that caller, for free. Also proves
    this check runs before resolve_pipeline_for_webhook: patch it to
    raise if ever called, and confirm it never is."""
    import api.v1.cicd as cicd_module

    async def _fail_if_called(*a, **k):
        raise AssertionError("resolve_pipeline_for_webhook must not run before the cheap rejections")
    monkeypatch.setattr(cicd_module, "resolve_pipeline_for_webhook", _fail_if_called)

    body = _push_body()
    r = await client.post(
        f"/api/v1/cicd/webhook/{uuid.uuid4()}", content=body,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"},
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid webhook request."}


# ── 5. No secret configured ─────────────────────────────────────────────────

async def test_pipeline_with_no_secret_configured_is_refused(client):
    token, tenant_id, _ = await _register(client, "nosecret")
    pipeline_id = await _create_pipeline(client, token)
    # Deliberately never calls _generate_secret.

    body = _push_body()
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64, "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid webhook request."}, (
        "the response body must be identical to every other rejection "
        "reason -- it must not reveal that the real cause here was a "
        "missing secret rather than a bad signature"
    )


async def test_unknown_pipeline_id_gets_the_identical_401_body(client):
    r = await client.post(
        f"/api/v1/cicd/webhook/{uuid.uuid4()}", content=_push_body(),
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64, "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid webhook request."}


# ── 6. Replay ────────────────────────────────────────────────────────────────

async def test_replayed_delivery_id_is_rejected_on_the_second_call(client):
    token, tenant_id, _ = await _register(client, "replay")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    signature = _sign(body, secret_info["webhook_secret"])
    delivery_id = str(uuid.uuid4())

    r1 = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={"X-Hub-Signature-256": signature, "X-GitHub-Delivery": delivery_id, "Content-Type": "application/json"},
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={"X-Hub-Signature-256": signature, "X-GitHub-Delivery": delivery_id, "Content-Type": "application/json"},
    )
    assert r2.status_code == 401
    assert await _commit_count(tenant_id, pipeline_id) == 1, "the replay must not create a second commit"


# ── 6b. Redis down during the replay check: fails OPEN, signature is still the gate ──

async def test_redis_down_during_replay_check_still_accepts_a_valid_signature(client, monkeypatch):
    """check_replay fails OPEN on a Redis outage (RedisError/OSError only)
    -- by the time it runs, verify_signature has already succeeded, so a
    genuinely valid, correctly-signed delivery must still go through
    rather than being lost to an unrelated infrastructure outage."""
    import services.webhook_security as wh

    async def _raise_redis_error(*a, **k):
        from redis.exceptions import ConnectionError as RedisConnectionError
        raise RedisConnectionError("simulated Redis outage")
    monkeypatch.setattr(wh, "_redis", lambda: type("Fake", (), {"set": _raise_redis_error})())

    token, tenant_id, _ = await _register(client, "redisdown1")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret_info["webhook_secret"]),
            "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, (
        f"a valid signed delivery must still succeed during a Redis outage -- got {r.status_code}: {r.text}"
    )
    assert await _commit_count(tenant_id, pipeline_id) == 1


async def test_redis_down_during_replay_check_still_rejects_an_invalid_signature(client, monkeypatch):
    """The other half of the same control: Redis being down must never
    let an INVALID signature through -- fail-open applies only to the
    replay check, never to verify_signature itself."""
    import services.webhook_security as wh

    async def _raise_redis_error(*a, **k):
        from redis.exceptions import ConnectionError as RedisConnectionError
        raise RedisConnectionError("simulated Redis outage")
    monkeypatch.setattr(wh, "_redis", lambda: type("Fake", (), {"set": _raise_redis_error})())

    token, tenant_id, _ = await _register(client, "redisdown2")
    pipeline_id = await _create_pipeline(client, token)
    await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401, "an invalid signature must stay rejected even during a Redis outage"
    assert await _commit_count(tenant_id, pipeline_id) == 0


# ── 7. Cross-pipeline isolation ──────────────────────────────────────────────

async def test_valid_signature_for_one_pipeline_cannot_write_under_another(client):
    """Pipeline A's own secret, correctly signed, with a payload whose
    repository field claims to be Pipeline B's repo. Must still create the
    commit under Pipeline A's tenant/pipeline_id -- the URL's own pipeline
    is the trust boundary, never anything the payload claims."""
    token_a, tenant_a, _ = await _register(client, "crossa")
    token_b, tenant_b, _ = await _register(client, "crossb")
    pipeline_a = await _create_pipeline(client, token_a, "pipeline A")
    pipeline_b = await _create_pipeline(client, token_b, "pipeline B")
    secret_a = await _generate_secret(client, token_a, pipeline_a)
    await _generate_secret(client, token_b, pipeline_b)

    body = _push_body(repo_url="https://github.com/example/pipeline-b-repo")
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_a}", content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret_a["webhook_secret"]),
            "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text

    async with tenant_session(tenant_a) as db:
        res = await db.execute(select(PipelineCommit).where(PipelineCommit.pipeline_id == pipeline_a))
        rows_a = res.scalars().all()
    assert len(rows_a) == 1 and rows_a[0].tenant_id == tenant_a

    assert await _commit_count(tenant_b, pipeline_b) == 0, (
        "a payload merely claiming Pipeline B's repo must not create any "
        "row under Pipeline B/tenant B -- Pipeline A's secret signed it, "
        "so Pipeline A's tenant is the only one allowed to be touched"
    )


# ── 8. Old route retired ─────────────────────────────────────────────────────

async def test_old_global_webhook_route_returns_410(client):
    r = await client.post("/api/v1/cicd/webhook", content=_push_body(), headers={"Content-Type": "application/json"})
    assert r.status_code == 410
    assert "webhook/{pipeline_id}" in r.json()["detail"] or "pipeline_id" in r.json()["detail"]


# ── 9. Oversized body ────────────────────────────────────────────────────────

async def test_oversized_body_is_rejected_before_hashing(client):
    token, tenant_id, _ = await _register(client, "oversized")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    from services.webhook_security import MAX_WEBHOOK_BODY_BYTES
    oversized = b'{"pad":"' + (b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)) + b'"}'
    # Signed correctly -- proves the size cap rejects BEFORE the signature
    # would otherwise have passed, not as a side effect of a bad signature.
    signature = _sign(oversized, secret_info["webhook_secret"])

    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=oversized,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )
    assert r.status_code == 401
    assert await _commit_count(tenant_id, pipeline_id) == 0


# ── 10. Rate-limit bucket (item 6: recommendation is to keep the existing
#         bucket, not add a stricter one -- this test pins that decision) ──

async def test_webhook_path_falls_into_the_default_unauth_ip_backstop_not_preauth():
    from services.rate_limit import categorise, RateLimitCategory, PREAUTH_PATHS
    path = "/api/v1/cicd/webhook/some-pipeline-id"
    assert not any(path.startswith(p) for p in PREAUTH_PATHS), (
        "the webhook path must not be added to PREAUTH_PATHS -- a "
        "correctly-implemented HMAC-SHA256 signature isn't brute-forceable "
        "at any practical request rate, so a stricter per-IP bucket would "
        "protect against nothing additional while risking false positives "
        "against legitimate, shared-IP GitHub webhook traffic"
    )
    assert categorise(path) == RateLimitCategory.DEFAULT
    # No tenant-identifying JWT is ever sent by GitHub, so
    # RateLimitMiddleware's own tenant_id-is-None branch is what actually
    # applies regardless of category -- the unauthenticated per-IP backstop.


# ── Secret generation / rotation endpoint ───────────────────────────────────

async def test_viewer_cannot_generate_a_webhook_secret(client):
    token, tenant_id, _ = await _register(client, "viewerperm")
    pipeline_id = await _create_pipeline(client, token)
    viewer_token = await _add_viewer(tenant_id)

    r = await client.post(f"/api/v1/pipelines/{pipeline_id}/webhook-secret", headers={"Authorization": f"Bearer {viewer_token}"})
    assert r.status_code == 403


async def test_rotating_a_secret_invalidates_the_old_one_immediately(client):
    token, tenant_id, _ = await _register(client, "rotate")
    pipeline_id = await _create_pipeline(client, token)
    first = await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    r1 = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={"X-Hub-Signature-256": _sign(body, first["webhook_secret"]), "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json"},
    )
    assert r1.status_code == 200, r1.text

    second = await _generate_secret(client, token, pipeline_id)
    assert second["webhook_secret"] != first["webhook_secret"]

    r2 = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={"X-Hub-Signature-256": _sign(body, first["webhook_secret"]), "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json"},
    )
    assert r2.status_code == 401, "the OLD secret must stop working the instant rotation happens"

    r3 = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={"X-Hub-Signature-256": _sign(body, second["webhook_secret"]), "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json"},
    )
    assert r3.status_code == 200, r3.text


async def test_webhook_secret_never_appears_in_get_pipeline(client):
    token, tenant_id, _ = await _register(client, "noleak")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    r = await client.get(f"/api/v1/pipelines/{pipeline_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body_text = r.text
    assert "webhook_secret" not in body_text
    assert secret_info["webhook_secret"] not in body_text


async def test_rotation_audit_row_has_no_secret_in_its_payload(client):
    token, tenant_id, _ = await _register(client, "auditnoleak")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    from models.all_models import AuditLog
    async with tenant_session(tenant_id) as db:
        r = await db.execute(select(AuditLog).where(
            AuditLog.tenant_id == tenant_id, AuditLog.action == "pipeline.webhook_secret_rotated",
        ))
        rows = r.scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor != ""  # caller's email, not blank
    assert row.resource_type == "pipeline" and row.resource_id == pipeline_id
    payload_str = str(row.payload)
    assert secret_info["webhook_secret"] not in payload_str


# ── End-to-end argument seam (added per explicit instruction, overriding ────
#    the earlier "fast-follow" default): a correctly signed delivery goes
#    through the real handler; run_ci_pipeline.delay is never actually
#    reached by .delay() in a test (no task_always_eager is set anywhere
#    in this codebase, so .delay() only enqueues to the real broker) --
#    this test captures exactly the arguments the handler passed to it,
#    then runs the real task body with those same arguments directly,
#    bypassing the broker. Proves the handler-to-task seam itself, not
#    merely that each half works against its own hand-picked arguments. ──

async def test_signed_delivery_arguments_let_run_ci_pipeline_find_the_commit(client, monkeypatch):
    import asyncio
    from services import cicd_tasks
    from models.cicd import CICDStatus

    captured = {}

    def _capture_delay(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(cicd_tasks.run_ci_pipeline, "delay", _capture_delay)

    token, tenant_id, _ = await _register(client, "argseam")
    pipeline_id = await _create_pipeline(client, token)
    secret_info = await _generate_secret(client, token, pipeline_id)

    body = _push_body()
    r = await client.post(
        f"/api/v1/cicd/webhook/{pipeline_id}", content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret_info["webhook_secret"]),
            "X-GitHub-Delivery": str(uuid.uuid4()), "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert "args" in captured, "run_ci_pipeline.delay was never called by the handler"
    commit_id, task_tenant_id = captured["args"]
    assert task_tenant_id == tenant_id

    # The real task body, run with exactly the arguments the handler
    # actually passed -- bypassing the broker (asyncio.to_thread, same
    # reason test_celery_tenant_context_guard.py's own live test needs it:
    # the task calls asyncio.run() internally, which raises if invoked
    # from a loop that's already running).
    await asyncio.to_thread(cicd_tasks.run_ci_pipeline.run, commit_id, task_tenant_id)

    async with tenant_session(tenant_id) as db:
        result = await db.execute(select(PipelineCommit).where(PipelineCommit.id == commit_id))
        refreshed = result.scalar_one()
    assert refreshed.ci_status != CICDStatus.pending, (
        "run_ci_pipeline, called with exactly the arguments the webhook "
        "handler passed to .delay(), never found its own commit row -- "
        "the handler-to-task argument seam is broken even though each "
        "half passes its own isolated test"
    )
