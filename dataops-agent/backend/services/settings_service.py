"""Tenant-level settings (Phase 16): workspace config, notification prefs,
AI model override. `name` is the one field that lives on a real column
(Tenant.name, already existed pre-Phase-16, real workspace identity) -
everything else is stored in the existing Tenant.settings JSON column
(present since the original scaffold, never used until now) rather than
new dedicated columns - matches this codebase's established convention
for flexible/growing config (DataSource.connection_config,
Pipeline.pipeline_config) over adding a column per field.

get_tenant_settings()/update_tenant_settings() present a single unified
view merging both - callers (the /settings/ endpoint) don't need to know
which field lives where.

Shape (all keys optional, absence means "unset/use default"):
{
  "name": str,                     # -> Tenant.name (real column)
  "timezone": str,                 # -> Tenant.settings
  "description": str,              # -> Tenant.settings
  "ai_model_override": str | None, # -> Tenant.settings
  "notification_prefs": {          # -> Tenant.settings
    "slack_webhook_url": str | None,
    "alert_email": str | None,
    "notify_on": {"incident_created": bool, "pipeline_failed": bool,
                  "deployment_failed": bool, "approval_required": bool},
  },
}
"""
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import Tenant
from services.llm_service import SUPPORTED_MODEL_OVERRIDES

NOTIFY_ON_KEYS = ("incident_created", "pipeline_failed", "deployment_failed", "approval_required")
DEFAULT_NOTIFY_ON = {k: True for k in NOTIFY_ON_KEYS}


async def get_tenant_settings(tenant_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalars().first()
        if not tenant:
            return {}
        return {"name": tenant.name, **(tenant.settings or {})}


def _validate_notification_prefs(prefs) -> str | None:
    if not isinstance(prefs, dict):
        return "notification_prefs must be an object"
    for key in prefs:
        if key not in ("slack_webhook_url", "alert_email", "notify_on"):
            return f"Unknown notification_prefs key '{key}'"
    notify_on = prefs.get("notify_on")
    if notify_on is not None:
        if not isinstance(notify_on, dict):
            return "notify_on must be an object"
        for key, value in notify_on.items():
            if key not in NOTIFY_ON_KEYS:
                return f"Unknown notify_on key '{key}'. Valid: {list(NOTIFY_ON_KEYS)}"
            if not isinstance(value, bool):
                return f"notify_on['{key}'] must be a boolean"
    return None


async def update_tenant_settings(tenant_id: str, updates: dict) -> dict:
    """Shallow-merges top-level `updates` into the tenant's existing
    settings dict, except: `name` writes to the real Tenant.name column,
    and `notification_prefs` is deep-merged one level (a partial update
    like {"slack_webhook_url": "..."} doesn't wipe out an already-set
    notify_on). Validates ai_model_override against the allowlist, name
    against non-empty, and notification_prefs' shape. Returns
    {"error": ...} | the full updated unified settings dict."""
    if "ai_model_override" in updates:
        model = updates["ai_model_override"]
        if model is not None and model not in SUPPORTED_MODEL_OVERRIDES:
            return {"error": f"Unsupported model '{model}'. Allowed: {SUPPORTED_MODEL_OVERRIDES}"}

    if "name" in updates and not (updates["name"] or "").strip():
        return {"error": "Workspace name cannot be empty"}

    if "notification_prefs" in updates:
        err = _validate_notification_prefs(updates["notification_prefs"])
        if err:
            return {"error": err}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalars().first()
        if not tenant:
            return {"error": "Tenant not found"}

        updates = dict(updates)
        if "name" in updates:
            tenant.name = updates.pop("name").strip()

        merged = dict(tenant.settings or {})
        if "notification_prefs" in updates:
            incoming = updates.pop("notification_prefs")
            existing_prefs = dict(merged.get("notification_prefs") or {})
            if "notify_on" in incoming:
                existing_prefs["notify_on"] = {**existing_prefs.get("notify_on", {}), **incoming.pop("notify_on")}
            existing_prefs.update(incoming)
            merged["notification_prefs"] = existing_prefs

        merged.update(updates)
        tenant.settings = merged
        await db.commit()
        return {"name": tenant.name, **merged}


async def get_notification_prefs(tenant_id: str) -> dict:
    """Returns the tenant's notification prefs with defaults filled in for
    any unset field - callers never need to handle missing keys."""
    tenant_settings = await get_tenant_settings(tenant_id)
    prefs = tenant_settings.get("notification_prefs") or {}
    return {
        "slack_webhook_url": prefs.get("slack_webhook_url"),
        "alert_email": prefs.get("alert_email"),
        "notify_on": {**DEFAULT_NOTIFY_ON, **prefs.get("notify_on", {})},
    }


async def get_ai_model_override(tenant_id: str) -> str | None:
    """Returns the tenant's configured override, or None if unset - callers
    (run_agent()) fall back to the global settings.PRIMARY_LLM_MODEL in
    that case. Re-validates against the allowlist on *read*, not just on
    write, so a value that was valid when set but has since been removed
    from SUPPORTED_MODEL_OVERRIDES can't silently keep being used."""
    tenant_settings = await get_tenant_settings(tenant_id)
    model = tenant_settings.get("ai_model_override")
    if model and model not in SUPPORTED_MODEL_OVERRIDES:
        return None
    return model
