from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user, require_permission
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
    user=Depends(require_permission("billing.manage")),
):
    """Disabled until Stripe billing is real (public-launch risk cluster,
    item (b)): self-serve upgrade against real paid LLM keys would let any
    Owner/Admin grant their own tenant unlimited AI-credit budget for free.
    require_permission still gates this first, so a non-Owner/Admin gets
    403 same as before - an Owner/Admin now gets an honest 501 instead of
    a real plan change, matching the checkout/webhook pattern below.
    BillingService.change_plan() itself is untouched and still real -
    see its docstring for the sanctioned manual-provisioning path this
    endpoint no longer exposes."""
    raise HTTPException(
        status_code=501,
        detail="Self-serve plan changes are disabled until Stripe billing is live. Contact the AXIOM team to change your plan.",
    )


@router.post("/checkout")
async def create_checkout(user=Depends(require_permission("billing.manage"))):
    raise HTTPException(status_code=501, detail="Stripe checkout not yet implemented - contact the AXIOM team for a manual plan change")


@router.post("/webhook")
async def stripe_webhook():
    raise HTTPException(status_code=501, detail="Stripe webhook handling not yet implemented")
