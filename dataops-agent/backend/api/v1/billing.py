from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user, require_role
from services.rbac import Role
from services.billing_service import BillingService
from services.quota_service import PLANS

router = APIRouter()


class PlanChange(BaseModel):
    plan: str


@router.get("/usage")
async def get_usage(user=Depends(get_current_user)):
    """Any authenticated tenant member can view usage (matches GET
    /team/members - not sensitive within your own tenant). Feeds the
    Billing screen's 4 usage bars (Phase 17) - status is "ok" | "warning"
    (>= 80%) | "exceeded" (>= 100%, also hard-blocked at the point of use
    by enforce_quota() on the relevant mutation endpoints)."""
    return {"usage": await BillingService(user["tenant_id"]).get_usage()}


@router.get("/plans")
async def list_plans():
    """Public - no auth. Plan tier definitions for pricing/upgrade UI."""
    return {"plans": PLANS}


@router.get("/plan")
async def get_current_plan(user=Depends(get_current_user)):
    return await BillingService(user["tenant_id"]).get_plan()


@router.post("/change-plan")
async def change_plan(
    body: PlanChange,
    user=Depends(require_role(Role.OWNER, Role.ADMIN)),
):
    """Real today, immediate effect - no payment collection exists yet.
    See BillingService.change_plan()'s docstring: this is a deliberate
    dev-mode stand-in, not the final design - once Stripe checkout is
    real, plan changes should only happen via a confirmed webhook, and
    this endpoint (or its role) will need to change."""
    result = await BillingService(user["tenant_id"]).change_plan(body.plan)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/checkout")
async def create_checkout(user=Depends(require_role(Role.OWNER, Role.ADMIN))):
    raise HTTPException(status_code=501, detail="Stripe checkout not yet implemented - use POST /billing/change-plan for now")


@router.post("/webhook")
async def stripe_webhook():
    raise HTTPException(status_code=501, detail="Stripe webhook handling not yet implemented")
