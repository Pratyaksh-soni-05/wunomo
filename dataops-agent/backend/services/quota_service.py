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

Tier limit calibration (2026-07-18) - CORRECTED 2026-09-03, read this
before this paragraph ends up in a pricing doc: the originally-proposed
Starter cap (2,000 credits/mo) was checked against usage from a handful
of this project's own actively-reused internal verification tenants
(a small number of hand-created accounts belonging to the team, used
for live Gemini/Groq testing) before any enforcement shipped, and found
badly miscalibrated - those tenants already showed 4,000-84,000
credits/mo from ordinary live-LLM-testing sessions under this exact
formula (a single afternoon of verification work, not abuse).
Recalibrated upward using that handful of internal accounts as the
signal (Starter 25,000 / Growth 100,000 / Scale 500,000), discounting
the extreme high end as accumulated-across-many-sessions reuse rather
than one real customer's single month. Sources/runs/members limits were
left as originally proposed on the same basis (max observed: 5 sources,
1 member, 6 runs/mo across ~2,900 tenant rows, at the time).

This was never customer data, and the "~2,900 tenant rows" figure is
now itself stale and misleading in the other direction: as of
2026-09-03 this table holds 23,589 tenant rows, of which a real audit
found 23,578 carry the pytest fixture's own @example.com email pattern
and the remaining ~14 are all traceable to the team's own accounts
(demo/QA/manual-verification tenants) - zero are an external signup.
The count keeps growing by thousands per day purely from running this
project's own test suite (4,987 new rows in a single day, 2026-09-02),
with no teardown. Every number in this docstring, and any per-tenant
aggregate computed against the `tenants` table today, reflects test-
suite volume, not usage calibration of any kind. Recalibrate all of
these against real customer usage once it exists - these remain
launch-time placeholders, now with a corrected basis, not carved in
stone.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func

from database import AsyncSessionLocal
from models.all_models import AgentInstance, LlmUsageEvent, PipelineRun, Pipeline, DataSource, User, Tenant

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


async def _agent_token_usage(db, agent_id: str) -> int:
    """Raw token count (input+output, unweighted), not the tenant-level
    "credits" formula (input*1 + output*3) - a human setting "Nova gets
    40k tokens a month" means tokens, not a cost-weighted proxy for
    tokens. Every llm_usage_events row already carries agent_id (Phase 0/
    1's own threading work), so this is a live aggregate, same pattern as
    _current_usage above, not a separately-maintained counter."""
    r = await db.execute(
        select(LlmUsageEvent.input_tokens, LlmUsageEvent.output_tokens).where(
            LlmUsageEvent.agent_id == agent_id,
            LlmUsageEvent.created_at >= _month_start(),
        )
    )
    return sum((inp or 0) + (out or 0) for inp, out in r.all())


async def get_agent_quota_status(agent_id: str) -> dict:
    """The second gate (Wunomo Projects Phase 1, part two) alongside
    get_quota_status("ai_credits") above - both must pass, this one
    never replaces that one. AgentInstance.monthly_token_budget is
    nullable: None means no agent-level ceiling, draw against the
    tenant's plan-level quota only (the Phase 0 column comment's own
    stated intent) - returned as an always-"ok", None-limit status,
    same shape get_quota_status uses for the Scale plan's unlimited
    data_sources, so callers can treat both the same way."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentInstance.monthly_token_budget).where(AgentInstance.id == agent_id))
        row = r.first()
        budget = row[0] if row else None
        if budget is None:
            return {"resource": "agent_tokens", "used": 0, "limit": None, "percent": 0.0, "status": "ok"}
        used = await _agent_token_usage(db, agent_id)

    percent = round((used / budget) * 100, 1) if budget else 100.0
    if used >= budget:
        status = "exceeded"
    elif used >= budget * WARNING_THRESHOLD:
        status = "warning"
    else:
        status = "ok"
    return {"resource": "agent_tokens", "used": used, "limit": budget, "percent": percent, "status": status}


async def get_task_cost(db, tenant_id: str, task_id: str) -> dict:
    """Wunomo Projects Phase 4, item 2: what a task actually spent, for
    the task detail screen -- an agent that works unattended (item 71's
    auto-advance loop) should show what it spent while nobody was
    watching, not just that it finished. Reuses credits_for_event's
    existing formula (the same "AI Credits" unit already shown on
    Billing) rather than inventing a second cost metric -- tenant-scoped
    for defense in depth even though task_id alone is already
    effectively unique, matching every other query in this module.
    Takes an already-open db session (called from within GET
    /tasks/{id}'s own session, not a second round trip)."""
    r = await db.execute(
        select(LlmUsageEvent.input_tokens, LlmUsageEvent.output_tokens, LlmUsageEvent.reasoning_tokens)
        .where(LlmUsageEvent.tenant_id == tenant_id, LlmUsageEvent.task_id == task_id)
    )
    rows = r.all()
    input_tokens = sum(inp or 0 for inp, _out, _reason in rows)
    output_tokens = sum(out or 0 for _inp, out, _reason in rows)
    reasoning_tokens = sum(reason or 0 for _inp, _out, reason in rows)
    credits = sum(credits_for_event(inp, out) for inp, out, _reason in rows)
    return {
        "llm_calls": len(rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": input_tokens + output_tokens,
        "credits": credits,
    }
