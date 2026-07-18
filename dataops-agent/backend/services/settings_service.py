"""Tenant-level settings (Phase 16): workspace config, notification prefs,
AI model override. All stored in the existing Tenant.settings JSON column
(present since the original scaffold, never used until now) rather than
new dedicated columns - matches this codebase's established convention
for flexible/growing config (DataSource.connection_config,
Pipeline.pipeline_config) over adding a column per field.

Shape (all keys optional, absence means "unset/use default"):
{
  "timezone": str,
  "description": str,
  "ai_model_override": str | None,
  "notification_prefs": {
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


async def get_tenant_settings(tenant_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
        return r.scalar() or {}


async def update_tenant_settings(tenant_id: str, updates: dict) -> dict:
    """Shallow-merges `updates` into the tenant's existing settings dict
    (top-level keys only - notification_prefs' own nested shape is merged
    by its own dedicated update path once that lands, not here). Validates
    ai_model_override against the allowlist if present in this update.
    Returns {"error": ...} | the full updated settings dict."""
    if "ai_model_override" in updates:
        model = updates["ai_model_override"]
        if model is not None and model not in SUPPORTED_MODEL_OVERRIDES:
            return {"error": f"Unsupported model '{model}'. Allowed: {SUPPORTED_MODEL_OVERRIDES}"}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalars().first()
        if not tenant:
            return {"error": "Tenant not found"}
        merged = dict(tenant.settings or {})
        merged.update(updates)
        tenant.settings = merged
        await db.commit()
        return merged


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
