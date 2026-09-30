from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_permission
from services.api_key_service import create_api_key, list_api_keys, revoke_api_key

router = APIRouter()


class ApiKeyCreate(BaseModel):
    name: str


@router.post("/")
async def create_key(
    body: ApiKeyCreate,
    user=Depends(require_permission("api_keys.manage")),
):
    """Returns the raw key exactly once - it is never retrievable again
    after this response (only its hash is stored)."""
    result = await create_api_key(user["tenant_id"], body.name, user["sub"])
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    # Found 2026-10-01, privilege-events audit sweep. Called here, not from
    # create_api_key() itself -- that function only has tenant_id/name/
    # created_by_user_id, not the caller's email every other audit call
    # site uses as actor (mfa.py/approvals.py/governance.py all call from
    # their router for the same reason). name and id only -- never
    # key_prefix or any part of result["raw_key"], the one-time-only real
    # secret this response carries.
    from modules.governance.audit_trail import AuditTrail
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="api_key.created",
        resource_type="api_key", resource_id=result["id"],
        payload={"name": body.name},
    )
    return result


@router.get("/")
async def list_keys(user=Depends(require_permission("api_keys.manage"))):
    """Owner/Admin only - unlike team roster or usage, API keys are
    sensitive infrastructure credentials even in masked form (know which
    ones exist, when they were last used)."""
    return {"api_keys": await list_api_keys(user["tenant_id"])}


@router.delete("/{key_id}")
async def revoke_key(
    key_id: str,
    user=Depends(require_permission("api_keys.manage")),
):
    result = await revoke_api_key(user["tenant_id"], key_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    from modules.governance.audit_trail import AuditTrail
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="api_key.revoked",
        resource_type="api_key", resource_id=key_id,
        payload={},
    )
    return result
