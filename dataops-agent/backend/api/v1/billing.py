from fastapi import APIRouter, Depends

from .auth import get_current_user
from services.quota_service import get_all_quota_statuses, PLANS

router = APIRouter()


@router.get("/usage")
async def get_usage(user=Depends(get_current_user)):
    """Any authenticated tenant member can view usage (matches GET
    /team/members - not sensitive within your own tenant). Feeds the
    Billing screen's 4 usage bars (Phase 17) - status is "ok" | "warning"
    (>= 80%) | "exceeded" (>= 100%, also hard-blocked at the point of use
    by enforce_quota() on the relevant mutation endpoints)."""
    return {"usage": await get_all_quota_statuses(user["tenant_id"])}


@router.get("/plans")
async def list_plans():
    """Public - no auth. Plan tier definitions for pricing/upgrade UI."""
    return {"plans": PLANS}
