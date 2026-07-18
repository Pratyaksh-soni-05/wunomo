"""Plan/quota enforcement (Phase 15).

Tier limits are a hardcoded config dict - same pattern this codebase
already uses for agent/personality.py's RISK_ACTIONS and
policy_engine.py's TOOL_REGISTRY - since plans are a fixed, small,
business-defined set with nothing user-editable about them yet. No new
usage-tracking table either: every resource here is a live aggregate
query against data that already exists (LlmUsageEvent, PipelineRun,
DataSource, User), not a separately-maintained counter that could drift
from reality.

AI credits formula: credits = input_tokens * 1 + output_tokens * 3. The
x3 weight on output tokens approximates real provider cost skew
(completion tokens cost more than prompt tokens industry-wide across
Gemini/Groq/every major provider). Gemini's "thinking"/reasoning tokens
are already a SUBSET of output_tokens, not additive on top of it (see
LlmUsageEvent.reasoning_tokens's own column comment in models/
all_models.py) - this formula does not double-count them. This is a
deliberately simple placeholder, not a real-dollar-cost calculation - see
CLAUDE.md's Phase 15 Status Table row for the other options considered
(flat 1:1, real per-model $/token table, flat per-call) and why this one
was chosen for now. Expect it to be replaced by a real $/token table
once Stripe billing is genuinely live and per-model pricing needs to be
exact rather than approximate.

Tier limit calibration (2026-07-18): the originally-proposed Starter cap
(2,000 credits/mo) was checked against this project's own real dev/
verification-tenant usage before any enforcement shipped, and found badly
miscalibrated - several actively-reused verification tenants already
showed 4,000-84,000 credits/mo from ordinary live-LLM-testing sessions
under this exact formula (a single afternoon of Gemini/Groq
live-verification work, not abuse). Recalibrated upward using that real
usage data as the signal before shipping (Starter 25,000 / Growth
100,000 / Scale 500,000), discounting the extreme high end as
accumulated-across-many-sessions test-tenant reuse rather than one real
customer's single month. Sources/runs/members limits were left as
originally proposed - the same real-usage check found those already
realistic (max observed: 5 sources, 1 member, 6 runs/mo across ~2,900
dev/test tenants). Revisit all of these once real customer usage data
exists - these are launch-time placeholders with a documented basis, not
carved in stone.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func

from database import AsyncSessionLocal
from models.all_models import LlmUsageEvent, PipelineRun, Pipeline, DataSource, User, Tenant

WARNING_THRESHOLD = 0.8

PLANS: dict[str, dict[str, Optional[int]]] = {
    "starter": {
        "ai_credits_per_month": 25_000,
        "pipeline_runs_per_month": 100,
        "max_data_sources": 3,
        "max_team_members": 3,
    },
    "growth": {
        "ai_credits_per_month": 100_000,
        "pipeline_runs_per_month": 1_000,
        "max_data_sources": 15,
        "max_team_members": 10,
    },
    "scale": {
        "ai_credits_per_month": 500_000,
        "pipeline_runs_per_month": 10_000,
        "max_data_sources": None,  # unlimited
        "max_team_members": 25,
    },
}

_LIMIT_KEY = {
    "ai_credits": "ai_credits_per_month",
    "pipeline_runs": "pipeline_runs_per_month",
    "data_sources": "max_data_sources",
    "team_members": "max_team_members",
}


def credits_for_event(input_tokens: Optional[int], output_tokens: Optional[int]) -> int:
    return (input_tokens or 0) * 1 + (output_tokens or 0) * 3


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


async def _current_usage(db, tenant_id: str, resource: str) -> int:
    if resource == "ai_credits":
        r = await db.execute(
            select(LlmUsageEvent.input_tokens, LlmUsageEvent.output_tokens).where(
                LlmUsageEvent.tenant_id == tenant_id,
                LlmUsageEvent.created_at >= _month_start(),
            )
        )
        return sum(credits_for_event(inp, out) for inp, out in r.all())

    if resource == "pipeline_runs":
        r = await db.execute(
            select(func.count(PipelineRun.id))
            .join(Pipeline, PipelineRun.pipeline_id == Pipeline.id)
            .where(Pipeline.tenant_id == tenant_id, PipelineRun.started_at >= _month_start())
        )
        return r.scalar() or 0

    if resource == "data_sources":
        r = await db.execute(
            select(func.count(DataSource.id)).where(
                DataSource.tenant_id == tenant_id, DataSource.is_active.is_(True),
            )
        )
        return r.scalar() or 0

    if resource == "team_members":
        r = await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id, User.is_active.is_(True),
            )
        )
        return r.scalar() or 0

    raise ValueError(f"Unknown quota resource '{resource}'")


async def _plan_limits(db, tenant_id: str) -> dict:
    r = await db.execute(select(Tenant.plan).where(Tenant.id == tenant_id))
    plan = r.scalar() or "starter"
    return PLANS.get(plan, PLANS["starter"])


async def get_quota_status(tenant_id: str, resource: str) -> dict:
    """Returns {resource, used, limit, percent, status}. status is
    "ok" | "warning" (>= 80%) | "exceeded" (>= 100%). limit is None for an
    unlimited tier (Scale's data_sources) - always "ok" in that case."""
    async with AsyncSessionLocal() as db:
        limits = await _plan_limits(db, tenant_id)
        limit = limits[_LIMIT_KEY[resource]]
        used = await _current_usage(db, tenant_id, resource)

    if limit is None:
        return {"resource": resource, "used": used, "limit": None, "percent": 0.0, "status": "ok"}

    percent = round((used / limit) * 100, 1) if limit else 100.0
    if used >= limit:
        status = "exceeded"
    elif used >= limit * WARNING_THRESHOLD:
        status = "warning"
    else:
        status = "ok"
    return {"resource": resource, "used": used, "limit": limit, "percent": percent, "status": status}


async def get_all_quota_statuses(tenant_id: str) -> dict:
    return {resource: await get_quota_status(tenant_id, resource) for resource in _LIMIT_KEY}
