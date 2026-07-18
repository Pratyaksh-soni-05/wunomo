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


async def get_tenant_settings(tenant_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalars().first()
        if not tenant:
            return {}
        return {"name": tenant.name, **(tenant.settings or {})}


async def update_tenant_settings(tenant_id: str, updates: dict) -> dict:
    """Shallow-merges `updates` into the tenant's existing settings dict
    (top-level keys only - notification_prefs' own nested shape is merged
    by its own dedicated update path once that lands, not here), except
    `name` which writes to the real Tenant.name column. Validates
    ai_model_override against the allowlist and name against non-empty.
    Returns {"error": ...} | the full updated unified settings dict."""
    if "ai_model_override" in updates:
        model = updates["ai_model_override"]
        if model is not None and model not in SUPPORTED_MODEL_OVERRIDES:
            return {"error": f"Unsupported model '{model}'. Allowed: {SUPPORTED_MODEL_OVERRIDES}"}

    if "name" in updates and not (updates["name"] or "").strip():
        return {"error": "Workspace name cannot be empty"}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalars().first()
        if not tenant:
            return {"error": "Tenant not found"}

        updates = dict(updates)
        if "name" in updates:
            tenant.name = updates.pop("name").strip()

        merged = dict(tenant.settings or {})
        merged.update(updates)
        tenant.settings = merged
        await db.commit()
        return {"name": tenant.name, **merged}


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
