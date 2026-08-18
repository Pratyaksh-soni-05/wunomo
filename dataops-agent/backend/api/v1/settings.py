from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, AnyHttpUrl
from typing import Optional
import httpx

from .auth import get_current_user, require_permission
from services.settings_service import get_tenant_settings, update_tenant_settings

router = APIRouter()


class SettingsUpdate(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    description: Optional[str] = None
    ai_model_override: Optional[str] = None
    notification_prefs: Optional[dict] = None


@router.get("/")
async def get_settings(user=Depends(get_current_user)):
    """Any authenticated tenant member can view settings (matches
    GET /team/members and GET /billing/usage - not sensitive within your
    own tenant)."""
    return {"settings": await get_tenant_settings(user["tenant_id"])}


@router.patch("/")
async def patch_settings(
    body: SettingsUpdate,
    user=Depends(require_permission("settings.manage")),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")
    result = await update_tenant_settings(user["tenant_id"], updates)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"settings": result}


class TestSlackWebhookRequest(BaseModel):
    webhook_url: AnyHttpUrl


@router.post("/test-slack-webhook")
async def test_slack_webhook(
    body: TestSlackWebhookRequest,
    user=Depends(require_permission("settings.manage")),
):
    """Item 25: the frontend gates Save on this actually succeeding first
    ("double verification" for a URL, since there's no ownership-proof
    concept the way an email code has one) - a typo'd or dead webhook
    should never silently look saved. Host is restricted to Slack's own
    domain rather than posting to whatever URL a caller supplies: this
    backend making a server-side POST to an arbitrary attacker-controlled
    URL is a textbook SSRF vector, and there's no legitimate reason a
    "Slack webhook" field needs to reach anywhere else."""
    url = str(body.webhook_url)
    if not url.startswith("https://hooks.slack.com/"):
        # A 200 with {ok: false}, not a raised HTTPException: the frontend's
        # generic request() helper throws on any non-2xx and displays a
        # blanket "couldn't reach the server" message for it, same as a
        # genuine network failure - it has no path to surface an
        # HTTPException's specific detail text here. Found live during
        # verification: a bad-domain URL showed the same generic error as
        # an actual dead connection, hiding the real reason. Every failure
        # this endpoint can produce must use this one shape so the specific
        # reason always reaches the user.
        return {"ok": False, "error": "Must be a real Slack webhook URL (https://hooks.slack.com/...)."}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json={
                "text": f"✅ AXIOM test notification — sent by {user['email']} to verify this webhook. "
                        "If you're seeing this, your Slack notifications are wired up correctly.",
            })
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Could not reach Slack: {exc}"}

    if r.status_code == 200 and r.text == "ok":
        return {"ok": True}
    return {"ok": False, "error": f"Slack rejected the request ({r.status_code}): {r.text[:200]}"}
