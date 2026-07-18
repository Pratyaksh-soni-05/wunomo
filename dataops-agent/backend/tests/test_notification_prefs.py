import uuid
import pytest
from unittest.mock import MagicMock

from services.settings_service import get_notification_prefs, update_tenant_settings
import modules.reporting.notification_service as notification_service_module
from modules.reporting.notification_service import NotificationService


async def _register(client, prefix="notifyprefs"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Notify Prefs Test", "tenant_name": f"Notify Prefs Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


@pytest.mark.asyncio
async def test_get_notification_prefs_returns_defaults_when_unset(client):
    _, tenant_id = await _register(client)
    prefs = await get_notification_prefs(tenant_id)
    assert prefs["slack_webhook_url"] is None
    assert prefs["alert_email"] is None
    assert all(prefs["notify_on"].values())  # all default True


@pytest.mark.asyncio
async def test_notification_prefs_deep_merge_preserves_notify_on(client):
    _, tenant_id = await _register(client)

    await update_tenant_settings(tenant_id, {
        "notification_prefs": {
            "slack_webhook_url": "https://hooks.slack.com/services/AAA",
            "notify_on": {"incident_created": False, "pipeline_failed": False},
        }
    })

    # Partial update: only touches alert_email, must NOT wipe out the
    # slack_webhook_url or the notify_on toggles set above.
    result = await update_tenant_settings(tenant_id, {
        "notification_prefs": {"alert_email": "ops@example.com"}
    })

    prefs = result["notification_prefs"]
    assert prefs["slack_webhook_url"] == "https://hooks.slack.com/services/AAA"
    assert prefs["alert_email"] == "ops@example.com"
    assert prefs["notify_on"]["incident_created"] is False
    assert prefs["notify_on"]["pipeline_failed"] is False


@pytest.mark.asyncio
async def test_notification_prefs_notify_on_partial_update_preserves_other_toggles(client):
    _, tenant_id = await _register(client)

    await update_tenant_settings(tenant_id, {
        "notification_prefs": {"notify_on": {"incident_created": False}}
    })
    result = await update_tenant_settings(tenant_id, {
        "notification_prefs": {"notify_on": {"pipeline_failed": False}}
    })

    notify_on = result["notification_prefs"]["notify_on"]
    assert notify_on["incident_created"] is False  # preserved from the first update
    assert notify_on["pipeline_failed"] is False   # set by the second update


@pytest.mark.asyncio
async def test_notification_prefs_rejects_bad_shape(client):
    _, tenant_id = await _register(client)
    assert "error" in await update_tenant_settings(tenant_id, {"notification_prefs": "not-a-dict"})
    assert "error" in await update_tenant_settings(tenant_id, {"notification_prefs": {"bogus_key": "x"}})
    assert "error" in await update_tenant_settings(tenant_id, {"notification_prefs": {"notify_on": {"incident_created": "yes"}}})
    assert "error" in await update_tenant_settings(tenant_id, {"notification_prefs": {"notify_on": {"unknown_event": True}}})


@pytest.mark.asyncio
async def test_settings_endpoint_accepts_notification_prefs(client):
    token, tenant_id = await _register(client)
    r = await client.patch(
        "/api/v1/settings/",
        json={"notification_prefs": {"slack_webhook_url": "https://hooks.slack.com/services/BBB"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["settings"]["notification_prefs"]["slack_webhook_url"] == "https://hooks.slack.com/services/BBB"


@pytest.mark.asyncio
async def test_notification_service_uses_tenant_slack_webhook_over_global(client, monkeypatch):
    """The real fix: self.tenant_id was stored but never used - confirms
    send_slack() now actually reads this tenant's own configured webhook
    URL rather than always hitting the shared global one."""
    _, tenant_id = await _register(client)
    await update_tenant_settings(tenant_id, {
        "notification_prefs": {"slack_webhook_url": "https://hooks.slack.com/services/TENANT_SPECIFIC"}
    })

    captured_requests = []

    def fake_urlopen(req, timeout=10):
        captured_requests.append(req.full_url)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda self, *a: None
        return mock_resp

    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(notification_service_module.settings, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/GLOBAL_FALLBACK")

    result = await NotificationService(tenant_id).send_slack(message="test", title="Test Alert")

    assert result.get("sent") is True
    assert captured_requests == ["https://hooks.slack.com/services/TENANT_SPECIFIC"]


@pytest.mark.asyncio
async def test_notification_service_falls_back_to_global_webhook_when_tenant_unset(client, monkeypatch):
    _, tenant_id = await _register(client)  # no notification_prefs set

    captured_requests = []

    def fake_urlopen(req, timeout=10):
        captured_requests.append(req.full_url)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda self, *a: None
        return mock_resp

    monkeypatch.setattr(notification_service_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(notification_service_module.settings, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/GLOBAL_FALLBACK")

    result = await NotificationService(tenant_id).send_slack(message="test", title="Test Alert")

    assert result.get("sent") is True
    assert captured_requests == ["https://hooks.slack.com/services/GLOBAL_FALLBACK"]
