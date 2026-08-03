"""BillingService: the interface every payment/plan operation should go
through. Usage/quota methods are real today, backed by quota_service.py
(itself backed by real data - LlmUsageEvent, PipelineRun, DataSource,
User; see that module's docstring for the credit formula and tier-limit
rationale). Payment-provider methods are stubbed - Stripe drops in behind
this same interface later without changing what callers (API routes,
future frontend) see.

change_plan() is real today (a direct Tenant.plan write), not stubbed -
but as of the public-launch risk cluster session (2026-08-02), it is no
longer reachable from a client request at all: POST /change-plan
(api/v1/billing.py) now unconditionally returns a 501, since a real
paid LLM key behind an unmetered self-serve upgrade let any Owner/Admin
grant their own tenant unlimited AI-credit budget for free. This method
itself is the sanctioned way to provision a real customer's plan
manually before Stripe exists - call it directly (e.g. `docker exec
dataops_backend python -c "..."`, the same technique already used
throughout this project for direct-DB-write verification) or write
`Tenant.plan` via SQL; either way bypasses the disabled endpoint
entirely and is the intended path until Stripe webhooks call this
instead. Once create_checkout_session()/handle_webhook() are real,
change_plan() should only ever be invoked as a result of a confirmed
payment event, not directly from a client request or manually - flagged
here so that transition isn't missed.
"""
from typing import Optional

from database import AsyncSessionLocal
from models.all_models import Tenant
from services.quota_service import PLANS, get_all_quota_statuses, get_quota_status
from sqlalchemy import select


class BillingService:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ─── Real, usage-backed methods ────────────────────────────────────

    async def get_usage(self) -> dict:
        return await get_all_quota_statuses(self.tenant_id)

    async def check_quota(self, resource: str) -> dict:
        return await get_quota_status(self.tenant_id, resource)

    async def get_plan(self) -> dict:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Tenant.plan).where(Tenant.id == self.tenant_id))
            plan = r.scalar() or "starter"
        return {"plan": plan, "limits": PLANS.get(plan, PLANS["starter"])}

    async def change_plan(self, new_plan: str) -> dict:
        """Real today, but see the module docstring: this should become
        Stripe-webhook-triggered only once payment is real, not a direct
        client-callable plan switch."""
        if new_plan not in PLANS:
            return {"error": f"Unknown plan '{new_plan}'. Valid: {list(PLANS.keys())}"}
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Tenant).where(Tenant.id == self.tenant_id))
            tenant = r.scalars().first()
            if not tenant:
                return {"error": "Tenant not found"}
            tenant.plan = new_plan
            await db.commit()
        return {"plan": new_plan, "limits": PLANS[new_plan]}

    # ─── Stubbed payment-provider methods (Stripe lands here) ─────────

    async def create_checkout_session(self, target_plan: str, success_url: Optional[str] = None) -> dict:
        raise NotImplementedError("Stripe checkout not yet implemented - see BillingService.change_plan() for the current dev-mode plan switch")

    async def get_subscription_status(self) -> dict:
        raise NotImplementedError("No real subscription object exists yet - use get_plan() for the current plan")

    async def cancel_subscription(self) -> dict:
        raise NotImplementedError("Stripe subscription cancellation not yet implemented")

    async def handle_webhook(self, event: dict) -> dict:
        raise NotImplementedError("Stripe webhook handling not yet implemented")
