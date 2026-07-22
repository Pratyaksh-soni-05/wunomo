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
    return result
