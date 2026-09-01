"""Plan/quota enforcement (Phase 15).

Tier limits are a hardcoded config dict - same pattern this codebase
already uses for agent/personality.py's RISK_ACTIONS and
policy_engine.py's TOOL_REGISTRY - since plans are a fixed, small,
business-defined set with nothing user-editable about them yet. No new
usage-tracking table either: every resource here is a live aggregate
query against data that already exists (LlmUsageEvent, PipelineRun,
DataSource, User), not a separately-maintained counter that could drift
from reality.

QUOTA METRIC CHANGE (2026-08-31): the gated AI metric is now **turns**, not
ai_credits. Old formula: a flat per-tenant monthly credit pool
(input_tokens*1 + output_tokens*3, capped at 25k/100k/500k per tier). New
formula:

    monthly_turn_cap = turns_per_day_per_user * 30 * max(1, active_team_members)

recalculated live on every check, so adding or removing a team member changes
the effective cap immediately rather than at signup or plan-change time.

Two reasons for the switch. First, "turns" is the unit actually sold to
customers, so the gate now enforces the thing the pricing page promises rather
than a derived proxy. Second, the flat pool did not scale with team size at
all: a 1-person and a 10-person tenant on the same tier got the same budget.

A turn is one unit of user-initiated agent work:
    count(ChatMessage WHERE role='user') + count(TaskStep)
both for the current calendar month, both tenant-scoped.

**Do not count LlmUsageEvent rows as turns.** That was the obvious-looking
implementation and it is wrong by a large, variable factor: one row is written
per *LLM call*, and a single user turn costs one call per agent-graph iteration
(agent -> tools -> agent, up to MAX_AGENT_ITERATIONS) plus a second row whenever
the primary->fallback path fires. A tool-heavy turn can be 5-10 rows. Gating 25
turns/day against that count would block a real customer after roughly three
conversations.

credits_for_event() is kept below, but is now an internal cost/overage
calculation only — it no longer gates anything.

Historical note on the old metric: credits = input_tokens * 1 + output_tokens * 3. The
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
from models.all_models import (
    ChatMessage, DataSource, LlmUsageEvent, Pipeline, PipelineRun, Task, TaskStep,
    Tenant, User,
)
from services.tenant_context import with_tenant_context

WARNING_THRESHOLD = 0.8

# The turns/day rate is sold per user per day; the enforced pool is monthly.
# A flat 30 rather than the real length of the current month, deliberately: the
# cap should not silently shrink by ~10% in February, and a customer told "25
# turns/day" reading a monthly number expects 750, not 700.
DAYS_PER_BILLING_MONTH = 30

# DB plan keys are unchanged (starter/growth/scale) — the customer-facing names
# differ, but renaming these would be a data migration across every existing
# tenant row for no functional gain.
PLANS: dict[str, dict[str, Optional[int]]] = {
    # Standard + Starter Plus share one enforcement tier; the higher of the two
    # caps is used, so neither is under-served.
    "starter": {
        "turns_per_day_per_user": 25,
        "pipeline_runs_per_month": 100,
        "max_data_sources": 3,
        "max_team_members": 8,
    },
    "growth": {  # Premium
        "turns_per_day_per_user": 30,
        "pipeline_runs_per_month": 1_000,
        "max_data_sources": 15,
        "max_team_members": 15,
    },
    "scale": {  # Enterprise
        "turns_per_day_per_user": 35,
        "pipeline_runs_per_month": 10_000,
        "max_data_sources": None,  # unlimited
        # Unlimited on purpose. Enterprise scales *price* per seat beyond 25
        # (the per-extra-seat rate), it does not hard-block on team size — the
        # old cap of 25 directly contradicted that. Note the turn formula uses
        # the ACTUAL active member count, never this cap, so "unlimited" here
        # does not make the turn pool unbounded.
        "max_team_members": None,
    },
}

# Resources whose cap is a plain per-tier constant. `turns` is deliberately
# absent: its cap is a function of live team size, so it is computed in
# _resource_limit() rather than looked up here.
_STATIC_LIMIT_KEY = {
    "pipeline_runs": "pipeline_runs_per_month",
    "data_sources": "max_data_sources",
    "team_members": "max_team_members",
}

QUOTA_RESOURCES = ("turns", "pipeline_runs", "data_sources", "team_members")


def credits_for_event(input_tokens: Optional[int], output_tokens: Optional[int]) -> int:
    return (input_tokens or 0) * 1 + (output_tokens or 0) * 3


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


async def _current_usage(db, tenant_id: str, resource: str) -> int:
    if resource == "turns":
        # A turn is one unit of user-initiated agent work. Two sources, summed:
        # a chat message the user actually sent, and a task step (tasks are the
        # heaviest LLM consumer, so leaving them out would make them unmetered).
        # Assistant/system chat rows are excluded — the user did not spend those.
        month_start = _month_start()
        chat_turns = (await db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= month_start,
            )
        )).scalar() or 0
        # NOTE: TaskStep has no created_at column — only nullable started_at /
        # completed_at. So the step's age is taken from its parent Task, which
        # is accurate because steps are written in the same transaction as the
        # task that owns them (api/v1/tasks.py's create/edit paths). The one
        # skew is a SYSTEM_INSERTED verify step appended mid-execution, which
        # is attributed to the month the task started rather than the month the
        # step appeared — immaterial except for a task spanning a month
        # boundary, and it errs toward not double-charging.
        task_turns = (await db.execute(
            select(func.count(TaskStep.id))
            .join(Task, TaskStep.task_id == Task.id)
            .where(
                TaskStep.tenant_id == tenant_id,
                Task.created_at >= month_start,
            )
        )).scalar() or 0
        return chat_turns + task_turns

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


async def monthly_turn_cap(db, tenant_id: str) -> int:
    """turns_per_day_per_user * 30 * max(1, active_team_members).

    Computed live on every quota check rather than stored, which is the whole
    point: inviting a team member raises the tenant's ceiling immediately, and
    removing one lowers it immediately, with no plan change and nothing to
    re-provision.

    max(1, ...) is a real guard, not defensive noise. The member count is
    `User WHERE is_active` — a tenant whose only user was soft-removed, or one
    observed mid-signup before its first User row commits, counts 0. Without
    the floor that yields a cap of 0, which reads as "exceeded" and hard-blocks
    every AI action for a tenant that has done nothing wrong.

    Note it uses the ACTUAL member count, never the tier's max_team_members —
    so Enterprise's unlimited seat cap does not make its turn pool unbounded.
    """
    limits = await _plan_limits(db, tenant_id)
    members = await _current_usage(db, tenant_id, "team_members")
    return limits["turns_per_day_per_user"] * DAYS_PER_BILLING_MONTH * max(1, members)


async def _resource_limit(db, tenant_id: str, resource: str) -> Optional[int]:
    """The cap for one resource. None means unlimited."""
    if resource == "turns":
        return await monthly_turn_cap(db, tenant_id)
    if resource not in _STATIC_LIMIT_KEY:
        raise ValueError(f"Unknown quota resource '{resource}'")
    limits = await _plan_limits(db, tenant_id)
    return limits[_STATIC_LIMIT_KEY[resource]]


@with_tenant_context
async def get_quota_status(tenant_id: str, resource: str) -> dict:
    """Returns {resource, used, limit, percent, status}. status is
    "ok" | "warning" (>= 80%) | "exceeded" (>= 100%). limit is None for an
    unlimited tier (Scale's data_sources) - always "ok" in that case."""
    async with AsyncSessionLocal() as db:
        limit = await _resource_limit(db, tenant_id, resource)
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
    return {resource: await get_quota_status(tenant_id, resource) for resource in QUOTA_RESOURCES}
