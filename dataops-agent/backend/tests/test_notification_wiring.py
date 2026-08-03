"""Regression tests for wiring NotificationService's 3 preset methods
(notify_incident/notify_stale_sources/notify_pipeline_failure) into real
trigger points. They existed but were never called from anywhere real --
see CLAUDE.md's "notification presets never fire automatically"
Known-broken row -- meaning a real incident, a real pipeline failure, or
a source going stale never proactively told anyone, only an explicit
chat "send an alert" request ever did.

Uses the same urlopen-spy technique already established in
test_notification_prefs.py -- trusting the HTTP status alone is a known
false signal (Slack redirects a bad webhook path to a 200 landing page).
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import modules.reporting.notification_service as notification_service_module
from database import AsyncSessionLocal
from models.all_models import DataSource, Incident, IncidentStatus, Pipeline, PipelineStatus, SourceType
from services.settings_service import update_tenant_settings


async def _register(client, prefix="notifywire"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Notification Wiring Test",
        "tenant_name": f"Notify Wire Corp {uuid.uuid4().hex[:6]}",
    })
    return reg.json()


def _spy_urlopen(monkeypatch, captured: list):
    def fake_urlopen(req, timeout=10):
        captured.append(req.full_url)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda self, *a: None
        return mock_resp
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", fake_urlopen)


@pytest.mark.asyncio
async def test_creating_an_incident_sends_a_real_notification(client, monkeypatch):
    reg = await _register(client)
    tenant_id, token = reg["tenant_id"], reg["access_token"]
    await update_tenant_settings(tenant_id, {
        "notification_prefs": {"slack_webhook_url": "https://hooks.slack.com/services/INCIDENT_TEST"}
    })

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    r = await client.post(
        "/api/v1/incidents/",
        json={"title": "A real logged incident", "severity": "high"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert captured == ["https://hooks.slack.com/services/INCIDENT_TEST"]


@pytest.mark.asyncio
async def test_incident_creation_still_succeeds_if_notification_fails(client, monkeypatch):
    """The notification wiring must never break the actual feature it's
    attached to."""
    reg = await _register(client)
    tenant_id, token = reg["tenant_id"], reg["access_token"]
    await update_tenant_settings(tenant_id, {
        "notification_prefs": {"slack_webhook_url": "https://hooks.slack.com/services/WILL_BLOW_UP"}
    })

    def broken_urlopen(req, timeout=10):
        raise RuntimeError("simulated network failure")
    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", broken_urlopen)

    r = await client.post(
        "/api/v1/incidents/",
        json={"title": "Still created despite notification failure", "severity": "low"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Still created despite notification failure"


@pytest.mark.asyncio
async def test_pipeline_failure_sends_a_real_notification(client, monkeypatch):
    from services.tasks import _execute_run

    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    await update_tenant_settings(tenant_id, {
        "notification_prefs": {"slack_webhook_url": "https://hooks.slack.com/services/PIPELINE_FAIL_TEST"}
    })

    async with AsyncSessionLocal() as db:
        # source_id points nowhere real -> ConnectorManager.sync() will
        # report an error, which _execute_run() already turns into a real
        # failure (see the pre-existing "pipeline-run false success" fix).
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="broken-source",
            source_type=SourceType.CSV, connection_config={"file_path": "/tmp/does-not-exist.csv"},
        )
        db.add(source)
        await db.flush()
        pipeline = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="doomed-pipeline",
            source_id=source.id, status=PipelineStatus.ACTIVE,
        )
        db.add(pipeline)
        await db.commit()
        pipeline_id, run_id = pipeline.id, str(uuid.uuid4())
        from models.all_models import PipelineRun, RunStatus
        db.add(PipelineRun(
            id=run_id, pipeline_id=pipeline_id, tenant_id=tenant_id,
            status=RunStatus.PENDING,
        ))
        await db.commit()

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    with pytest.raises(Exception):
        await _execute_run(run_id, pipeline_id, tenant_id)

    assert captured == ["https://hooks.slack.com/services/PIPELINE_FAIL_TEST"]


@pytest.mark.asyncio
async def test_freshness_check_notifies_once_per_newly_stale_source_not_every_tick(client, monkeypatch):
    """The real anti-spam guard: a source that's already known-stale (an
    open staleness Incident already exists for it) must not re-trigger a
    notification on a later tick -- only a source *newly* going stale
    should. This does not touch the separate, already-accepted
    duplicate-Incident-row gap (CLAUDE.md Known-broken) -- that behavior
    is unchanged; only the notification is guarded."""
    from services.tasks import _check_freshness

    reg = await _register(client)
    tenant_id = reg["tenant_id"]
    await update_tenant_settings(tenant_id, {
        "notification_prefs": {"slack_webhook_url": "https://hooks.slack.com/services/FRESHNESS_TEST"}
    })

    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="stale-source",
            source_type=SourceType.CSV, connection_config={"file_path": "/tmp/x.csv"},
            is_active=True, last_profiled_at=stale_time,
        )
        db.add(source)
        await db.commit()

    captured: list = []
    _spy_urlopen(monkeypatch, captured)

    # First tick: source is newly stale -> must notify.
    await _check_freshness()
    assert captured == ["https://hooks.slack.com/services/FRESHNESS_TEST"]

    # Second tick (simulating 15 min later, still stale): a real open
    # Incident for this source now exists from the first tick, so this
    # must NOT fire a second notification.
    captured.clear()
    await _check_freshness()
    assert captured == [], "must not re-notify for an already-known-stale source"

    # Confirm the pre-existing duplicate-incident behavior is genuinely
    # untouched -- two ticks really did create at least two Incident rows
    # (not exactly 2: this test shares its DB with the real, live
    # celery_beat/celery_worker containers, whose own independent
    # 15-minute freshness check can race in and create additional
    # duplicates for this same real stale source -- that's the
    # already-known, accepted duplicate-incident gap doing exactly what
    # it's documented to do, not a bug in this test).
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        r = await db.execute(select(Incident).where(
            Incident.tenant_id == tenant_id, Incident.status == IncidentStatus.OPEN,
        ))
        assert len(r.scalars().all()) >= 2
