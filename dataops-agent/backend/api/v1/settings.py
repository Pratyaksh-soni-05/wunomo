from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user, require_role
from services.rbac import Role
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
    user=Depends(require_role(Role.OWNER, Role.ADMIN)),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")
    result = await update_tenant_settings(user["tenant_id"], updates)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"settings": result}
