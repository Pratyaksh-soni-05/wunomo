import httpx
import structlog
from typing import Optional

log = structlog.get_logger()

async def send_slack_notification(webhook_url: str, event: str, payload: dict):
    """Send a CICD event notification to Slack."""
    messages = {
        "ci_started":         f"🔄 *CI Started* — commit `{payload.get('sha', '')[:8]}` on `{payload.get('branch', 'main')}`",
        "ci_passed":          f"✅ *CI Passed* — commit `{payload.get('sha', '')[:8]}` | Risk Score: `{payload.get('risk_score', 0):.0f}/100`",
        "ci_failed":          f"❌ *CI Failed* — commit `{payload.get('sha', '')[:8]}` | {payload.get('error', 'Check logs')}",
        "approval_required":  f"⚠️ *Approval Required* — commit `{payload.get('sha', '')[:8]}` | Risk Score: `{payload.get('risk_score', 0):.0f}/100`\n> {payload.get('message', '')}",
        "deployment_complete":f"🚀 *Deployment Complete* — commit `{payload.get('sha', '')[:8]}` deployed to production",
        "rollback_triggered": f"🔁 *Auto-Rollback Triggered* — deployment `{payload.get('deployment_id', '')[:8]}` rolled back after `{payload.get('failures', 0)}/{payload.get('runs', 0)}` failures",
    }

    text = messages.get(event, f"📢 CICD Event: `{event}`")

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(webhook_url, json={"text": text})
            resp.raise_for_status()
            log.info("cicd.slack_sent", notify_event=event)
    except Exception as e:
        log.warning("cicd.slack_failed", notify_event=event, error=str(e))


async def notify(event: str, payload: dict):
    """Send notification if Slack is configured."""
    try:
        from config import settings
        url = getattr(settings, "SLACK_WEBHOOK_URL", None)
        if url:
            await send_slack_notification(url, event, payload)
    except Exception as e:
        log.warning("cicd.notify_error", error=str(e))