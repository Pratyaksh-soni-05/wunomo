"""Plan/quota enforcement (Phase 15).

Tier limits are a hardcoded config dict - same pattern this codebase
already uses for agent/personality.py's RISK_ACTIONS and
policy_engine.py's TOOL_REGISTRY - since plans are a fixed, small,
business-defined set with nothing user-editable about them yet. No new
usage-tracking table either: every resource here is a live aggregate
query against data that already exists (LlmUsageEvent, PipelineRun,
DataSource, User), not a separately-maintained counter that could drift
from reality.

QUOTA MODEL (current, as of 2026-09-01)

The enforced metric is **ai_credits**, scaled by team size:

    monthly_credit_cap = credits_per_day_per_user * 30 * max(1, active_team_members)

recalculated live on every check, so adding or removing a team member changes
the effective cap immediately rather than at signup or plan-change time. The
team-size scaling is the durable part of the 2026-08-31 redesign; what changed
back is only *which unit* is counted.

    HISTORY, because the git log alone will read as thrashing:
    2026-08-31 switched the gate from ai_credits to **turns**, on the reasoning
    that turns are what customers are sold. 2026-09-01 reversed that: turns are
    now a customer-facing DISPLAY value derived from credits, and credits are
    the enforcement metric again. The reversal was not a change of mind about
    the pricing model — it is that deriving one from the other requires a
    credits-per-turn multiplier, and that multiplier cannot currently be
    measured (real sample size: 3 turns). Credits are directly measurable from
    LlmUsageEvent today; turns are not convertible to a cost without the
    missing factor. See GOTCHAS.md's "credits-per-turn conversion is two
    factors" entry for the full data.

    Consequence worth knowing: the customer-facing turns display is NOT
    implemented, because it needs the same missing multiplier. Shipping a
    turns number derived from an invented factor would look grounded while
    being fabricated.

**Do not count LlmUsageEvent rows as turns.** This still holds and is the
reason the display cannot be faked from existing data: one row is written per
*LLM call*, and a single user turn costs one call per agent-graph iteration
(agent -> tools -> agent, up to MAX_AGENT_ITERATIONS) plus a second row whenever
the primary->fallback path fires. Measured on real traffic, a chat turn averaged
4 LLM calls, but across only 3 turns.

The `turns` resource remains queryable via get_quota_status("turns") for
reporting, and _current_usage() still counts it correctly — it simply does not
gate anything.

The credit formula: credits = input_tokens * 1 + output_tokens * 3. The
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
from models.all_models import (
    AgentInstance, ChatMessage, DataSource, LlmUsageEvent, Pipeline, PipelineRun, Task, TaskStep,
    Tenant, User,
)
from services.tenant_context import with_tenant_context

WARNING_THRESHOLD = 0.8

# The per-user daily rate is what gets sold; the enforced pool is monthly.
# A flat 30 rather than the real length of the current month, deliberately: the
# cap should not silently shrink by ~10% in February.
DAYS_PER_BILLING_MONTH = 30

#   ⚠️  credits_per_day_per_user IS INTERIM-CALIBRATED (2026-09-17).
#       Better than the 2026-09-02 stopgap, still NOT FINAL.
#
# Derivation, so the numbers can be re-derived rather than guessed at:
#
#     credits_per_turn        = 5,108 x 3 = 15,324
#                               |          |
#                               |          +-- calls per turn: INTERIM. The first
#                               |              real measurement (2026-09-17, one
#                               |              user, 26 calls / 14 real turns)
#                               |              gave 1.86, median 2, max 3 -- but
#                               |              on a security-test script biased
#                               |              toward one-tool asks and refusals,
#                               |              so it is a floor, not a centre. 3
#                               |              sits above that floor and 25% below
#                               |              the old n=3 guess of 4. See GOTCHAS
#                               |              2026-09-17 for the recalibration
#                               |              threshold before this is "final".
#                               +------------- credits per real agent_chat LLM
#                                              call: GROUNDED, n=76 measured
#                                              events, RECONFIRMED 2026-09-17 at
#                                              5,114 on 19 fresh Gemini calls.
#
#     credits_per_day_per_user = turns_per_day_per_user x 15,324
#
# turns_per_day_per_user comes from the pricing model (25 / 25 / 30 / 35). The
# arithmetic is exact, not hand-rounded, and is self-consistent by construction:
# a single-seat Standard tenant's monthly pool divided by credits_per_turn comes
# back to exactly 750 turns, i.e. the 25/day it was sold.
#
# Margin note (2026-09-17, from Wunomo_Pricing_Costing_Strategy): that document
# costs a "turn" at 5,000 tokens, but its 235-event sample was per LLM CALL, and
# a real turn is ~1.9 calls -- so a customer who burns this whole credit cap
# consumes ~3x the tokens the pricing model costed per sold turn. On the
# document's own cost basis Premium goes negative at full-cap consumption
# (break-even is ~2.55 calls/turn); on today's measured input/output mix it
# stays positive. Recorded in GOTCHAS; a pricing decision, not a code one.
#
# This REPLACES the previous placeholders (each tier's old flat
# ai_credits_per_month / 30), which were wrong by 43-613x and left a Standard
# tenant able to afford roughly ONE chat turn per month. See GOTCHAS.md.
#
#   What "interim" means concretely: the magnitude is right and the multiplier
#   now has one real measurement behind it, from one person on one afternoon.
#   Do not treat these as final, do not quote them to a customer, and do not
#   derive anything else from them without re-reading the GOTCHAS entry first.
PLANS: dict[str, dict[str, Optional[int]]] = {
    "standard": {
        # interim 2026-09-17: 25 turns/day x 15,324 credits/turn. NOT FINAL.
        "credits_per_day_per_user": 383_100,
        "pipeline_runs_per_month": 100,
        "max_data_sources": 3,
        "max_team_members": 8,
    },
    # New sign-up-only tier: no existing tenant migrates into it (verified live —
    # 0 rows). Its rate deliberately matches `standard` for now rather than
    # inventing an intermediate number; it is the tier most in need of a real
    # figure once dogfooding data exists.
    "starter_plus": {
        # interim 2026-09-17: 25 turns/day x 15,324 credits/turn. NOT FINAL.
        # Matches standard by design — the pricing model sells both at 25/day.
        "credits_per_day_per_user": 383_100,
        "pipeline_runs_per_month": 100,
        "max_data_sources": 3,
        "max_team_members": 8,
    },
    "premium": {
        # interim 2026-09-17: 30 turns/day x 15,324 credits/turn. NOT FINAL.
        "credits_per_day_per_user": 459_720,
        "pipeline_runs_per_month": 1_000,
        "max_data_sources": 15,
        "max_team_members": 15,
    },
    "enterprise": {
        # interim 2026-09-17: 35 turns/day x 15,324 credits/turn (base rate;
        # per-seat scaling is unchanged and applies on top). NOT FINAL.
        "credits_per_day_per_user": 536_340,
        "pipeline_runs_per_month": 10_000,
        "max_data_sources": None,  # unlimited
        # Unlimited on purpose. Enterprise scales *price* per seat beyond 25,
        # it does not hard-block on team size. The credit formula uses the
        # ACTUAL active member count, never this cap, so "unlimited" here does
        # not make the credit pool unbounded.
        "max_team_members": None,
    },
}

# Maps every pre-2026-09 plan key to its replacement. Kept in code, not only in
# the migration, because `Tenant.plan` is a free-text VARCHAR with no FK or
# CHECK constraint — a row can still arrive carrying an old value (a restored
# backup, a manually-provisioned tenant, an unmigrated replica), and
# `_plan_limits` uses this to say so precisely instead of guessing.
LEGACY_PLAN_KEYS = {
    "starter": "standard",
    "growth": "premium",
    "scale": "enterprise",
}

# Resources whose cap is a plain per-tier constant. `ai_credits` is deliberately
# absent: its cap is a function of live team size, computed in _resource_limit().
_STATIC_LIMIT_KEY = {
    "pipeline_runs": "pipeline_runs_per_month",
    "data_sources": "max_data_sources",
    "team_members": "max_team_members",
}

QUOTA_RESOURCES = ("ai_credits", "pipeline_runs", "data_sources", "team_members")


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


class UnknownPlanError(RuntimeError):
    """A tenant carries a plan key this service has no limits for."""


async def _plan_limits(db, tenant_id: str) -> dict:
    """Fails loudly on an unrecognised plan rather than silently applying the
    cheapest tier's limits.

    This used to be `PLANS.get(plan, PLANS["starter"])` with an `or "starter"`
    fallback. After the 2026-09 rename (starter/growth/scale ->
    standard/starter_plus/premium/enterprise) that default became actively
    dangerous: an Enterprise tenant whose row had not been migrated would have
    been silently downgraded to Standard's limits and started getting 402s,
    with nothing anywhere saying why. `Tenant.plan` is free-text VARCHAR with no
    FK or CHECK, so an unmigrated value is a real possibility (restored backup,
    manual provisioning, a replica that missed the migration) — it must surface
    as an error naming the tenant, not as a quiet cap change.
    """
    r = await db.execute(select(Tenant.plan).where(Tenant.id == tenant_id))
    plan = r.scalar()
    if plan in PLANS:
        return PLANS[plan]
    if plan in LEGACY_PLAN_KEYS:
        raise UnknownPlanError(
            f"Tenant {tenant_id} still has the pre-2026-09 plan key {plan!r}; "
            f"it should have been migrated to {LEGACY_PLAN_KEYS[plan]!r}. Run "
            f"the tier-rename migration (c4e91a7d2f38) against this database."
        )
    raise UnknownPlanError(
        f"Tenant {tenant_id} has unknown plan {plan!r}. Known plans: "
        f"{sorted(PLANS)}. Refusing to guess a quota tier."
    )


async def monthly_credit_cap(db, tenant_id: str) -> int:
    """credits_per_day_per_user * 30 * max(1, active_team_members).

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
    so Enterprise's unlimited seat cap does not make its credit pool unbounded.

    The per-day rate is a documented placeholder (see PLANS above); the
    *shape* of this formula is the calibrated part, the magnitude is not.
    """
    limits = await _plan_limits(db, tenant_id)
    members = await _current_usage(db, tenant_id, "team_members")
    return limits["credits_per_day_per_user"] * DAYS_PER_BILLING_MONTH * max(1, members)


async def _resource_limit(db, tenant_id: str, resource: str) -> Optional[int]:
    """The cap for one resource. None means unlimited."""
    if resource == "ai_credits":
        return await monthly_credit_cap(db, tenant_id)
    if resource == "turns":
        # Informational only: None means "no limit", so status is always "ok"
        # and `used` carries the real turn count. Turns are not gated — see the
        # module docstring — but the count stays queryable so the eventual
        # customer-facing display has a real number to render, and so the
        # turn-counting logic keeps its test coverage rather than rotting.
        return None
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
