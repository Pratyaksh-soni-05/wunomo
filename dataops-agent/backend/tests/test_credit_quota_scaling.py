"""The ai_credits quota scales with live team size.

The team-size scaling is the durable half of the 2026-08-31 quota redesign;
what reversed on 2026-09-01 is only *which unit* is enforced. The gate is
ai_credits again, because turns cannot be converted to a cost without a
credits-per-turn multiplier that has a real sample size of 3 (see GOTCHAS.md).

    monthly_credit_cap = credits_per_day_per_user * 30 * max(1, active_team_members)

recalculated on every check, so a team change moves the ceiling immediately
rather than at the next signup or plan change. These tests assert that
"immediately" literally — the cap is re-read after mutating the team, with no
plan change and nothing re-provisioned in between.

The per-day rates in PLANS are documented placeholders. These tests deliberately
assert against `PLANS[...]["credits_per_day_per_user"]` rather than hard-coded
numbers, so recalibrating a rate does not break the suite — the *formula* is
what is under test, not the magnitude.

Turn counting is still exercised here (it remains correct and is what the
eventual customer-facing display will read), but as an informational metric with
no cap rather than a gate.
"""
import uuid

import pytest
from sqlalchemy import func, select

from models.all_models import (
    ChatMessage, LlmUsageEvent, Task, TaskShape, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus, Tenant, User,
)
from services.quota_service import (
    DAYS_PER_BILLING_MONTH, PLANS, WARNING_THRESHOLD, credits_for_event,
    get_quota_status, monthly_credit_cap,
)
from services.tenant_context import async_tenant_context, tenant_session
from database import AsyncSessionLocal


def utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _make_tenant(plan: str = "standard", members: int = 1) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_tenant_context(tenant_id), AsyncSessionLocal() as db:
        db.add(Tenant(id=tenant_id, name=f"Turns {tenant_id[:8]}",
                      slug=f"turns-{tenant_id[:8]}", plan=plan))
        await db.flush()
        for i in range(members):
            db.add(User(
                id=str(uuid.uuid4()), tenant_id=tenant_id,
                email=f"m{i}-{uuid.uuid4().hex[:8]}@example.com",
                role="owner" if i == 0 else "member", is_active=True,
            ))
        await db.commit()
    return tenant_id


async def _add_member(tenant_id: str) -> str:
    user_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        db.add(User(id=user_id, tenant_id=tenant_id,
                    email=f"extra-{uuid.uuid4().hex[:8]}@example.com",
                    role="member", is_active=True))
        await db.commit()
    return user_id


async def _deactivate_member(tenant_id: str, user_id: str):
    async with tenant_session(tenant_id) as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        user.is_active = False
        await db.commit()


async def _seed_chat_turns(tenant_id: str, n: int):
    async with tenant_session(tenant_id) as db:
        for _ in range(n):
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id="seed",
                session_id=str(uuid.uuid4()), role="user", content="turn",
                created_at=utcnow(),
            ))
        await db.commit()


async def _seed_assistant_messages(tenant_id: str, n: int):
    async with tenant_session(tenant_id) as db:
        for _ in range(n):
            db.add(ChatMessage(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id="seed",
                session_id=str(uuid.uuid4()), role="assistant", content="reply",
                created_at=utcnow(),
            ))
        await db.commit()


async def _seed_task_steps(tenant_id: str, n: int):
    async with tenant_session(tenant_id) as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            user_id=(await db.execute(select(User.id).where(
                User.tenant_id == tenant_id))).scalars().first(),
            goal="seed", task_shape=TaskShape.INVESTIGATE_INCIDENT,
            status=TaskStatus.DRAFT_PLAN, step_budget_max=20, created_at=utcnow(),
        )
        db.add(task)
        await db.flush()
        for i in range(n):
            db.add(TaskStep(
                id=str(uuid.uuid4()), task_id=task.id, tenant_id=tenant_id,
                step_index=i, description="seed step",
                source=TaskStepSource.LLM_PLANNED, tool_name="get_system_health",
                tool_args={}, status=TaskStepStatus.PENDING,
            ))
        await db.commit()


async def _seed_credits(tenant_id: str, credits: int):
    """One LlmUsageEvent whose credits_for_event() output is exactly `credits`.

    input_tokens only: it carries a 1x weight, so no division is needed and the
    target is hit exactly. output_tokens' 3x weight would truncate.
    """
    async with tenant_session(tenant_id) as db:
        db.add(LlmUsageEvent(
            id=str(uuid.uuid4()), tenant_id=tenant_id, request_type="test",
            provider="test", model="test", used_fallback=False,
            input_tokens=credits, output_tokens=0, total_tokens=credits,
            success=True, created_at=utcnow(),
        ))
        await db.commit()


async def _cap(tenant_id: str) -> int:
    async with tenant_session(tenant_id) as db:
        return await monthly_credit_cap(db, tenant_id)


# ── The cap scales with team size, live ──────────────────────────────────────

@pytest.mark.asyncio
async def test_cap_is_credits_per_day_times_thirty_times_members():
    tenant_id = await _make_tenant("standard", members=1)
    rate = PLANS["standard"]["credits_per_day_per_user"]
    assert await _cap(tenant_id) == rate * DAYS_PER_BILLING_MONTH * 1


@pytest.mark.asyncio
async def test_adding_a_member_raises_the_cap_immediately():
    """No plan change, no re-provisioning — the next check sees the new ceiling."""
    tenant_id = await _make_tenant("standard", members=1)
    before = await _cap(tenant_id)

    await _add_member(tenant_id)
    after = await _cap(tenant_id)

    rate = PLANS["standard"]["credits_per_day_per_user"]
    assert before == rate * DAYS_PER_BILLING_MONTH
    assert after == rate * DAYS_PER_BILLING_MONTH * 2
    assert after > before


@pytest.mark.asyncio
async def test_removing_a_member_lowers_the_cap_immediately():
    tenant_id = await _make_tenant("standard", members=1)
    extra = await _add_member(tenant_id)
    raised = await _cap(tenant_id)

    await _deactivate_member(tenant_id, extra)
    lowered = await _cap(tenant_id)

    assert lowered < raised
    assert lowered == PLANS["standard"]["credits_per_day_per_user"] * DAYS_PER_BILLING_MONTH


@pytest.mark.asyncio
async def test_each_tier_uses_its_own_per_user_rate():
    for plan in ("standard", "starter_plus", "premium", "enterprise"):
        tenant_id = await _make_tenant(plan, members=2)
        rate = PLANS[plan]["credits_per_day_per_user"]
        assert await _cap(tenant_id) == rate * DAYS_PER_BILLING_MONTH * 2


@pytest.mark.asyncio
async def test_scale_tier_unlimited_team_members_does_not_break_the_formula():
    """Enterprise has max_team_members=None. The turn formula must use the
    ACTUAL member count, not the cap — otherwise `None * 30 * 35` raises, or an
    unlimited seat cap silently becomes an unlimited turn pool."""
    assert PLANS["enterprise"]["max_team_members"] is None
    tenant_id = await _make_tenant("enterprise", members=3)
    cap = await _cap(tenant_id)
    assert isinstance(cap, int)
    assert cap == PLANS["enterprise"]["credits_per_day_per_user"] * DAYS_PER_BILLING_MONTH * 3


@pytest.mark.asyncio
async def test_zero_active_members_floors_at_one_rather_than_blocking_everything():
    """A tenant whose only member was soft-removed counts 0 active users.
    Without max(1, ...) the cap is 0, which reads as 'exceeded' and hard-blocks
    a tenant that has done nothing wrong."""
    tenant_id = await _make_tenant("standard", members=1)
    async with tenant_session(tenant_id) as db:
        only = (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars().first()
        only.is_active = False
        await db.commit()

    async with tenant_session(tenant_id) as db:
        members = (await db.execute(select(func.count(User.id)).where(
            User.tenant_id == tenant_id, User.is_active.is_(True)))).scalar()
    assert members == 0, "precondition: the tenant really has no active members"

    cap = await _cap(tenant_id)
    assert cap == PLANS["standard"]["credits_per_day_per_user"] * DAYS_PER_BILLING_MONTH
    assert cap > 0


# ── What counts as a turn ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_messages_and_task_steps_both_count_toward_one_total():
    tenant_id = await _make_tenant("standard", members=1)
    await _seed_chat_turns(tenant_id, 5)
    await _seed_task_steps(tenant_id, 3)

    status = await get_quota_status(tenant_id, "turns")
    assert status["used"] == 8, (
        f"expected 5 chat turns + 3 task steps = 8, got {status['used']}"
    )


@pytest.mark.asyncio
async def test_assistant_replies_do_not_count_against_the_caller():
    """Every /chat call writes a user row AND an assistant row. Counting both
    would halve every customer's real allowance."""
    tenant_id = await _make_tenant("standard", members=1)
    await _seed_chat_turns(tenant_id, 4)
    await _seed_assistant_messages(tenant_id, 4)

    status = await get_quota_status(tenant_id, "turns")
    assert status["used"] == 4


# ── Thresholds under the dynamic formula ─────────────────────────────────────

@pytest.mark.asyncio
async def test_warning_fires_at_eighty_percent_of_the_scaled_cap():
    tenant_id = await _make_tenant("standard", members=2)
    cap = await _cap(tenant_id)                      # 25 * 30 * 2 = 1500
    await _seed_credits(tenant_id, int(cap * WARNING_THRESHOLD))

    status = await get_quota_status(tenant_id, "ai_credits")
    assert status["limit"] == cap
    assert status["status"] == "warning", status


@pytest.mark.asyncio
async def test_block_fires_at_one_hundred_percent_of_the_scaled_cap():
    tenant_id = await _make_tenant("standard", members=2)
    cap = await _cap(tenant_id)
    await _seed_credits(tenant_id, cap)

    status = await get_quota_status(tenant_id, "ai_credits")
    assert status["status"] == "exceeded"
    assert status["percent"] >= 100.0


@pytest.mark.asyncio
async def test_adding_a_member_can_lift_a_tenant_back_out_of_exceeded():
    """The direct consequence of a live cap: a blocked tenant that adds a seat
    is unblocked on the very next check, with no plan change."""
    tenant_id = await _make_tenant("standard", members=1)
    await _seed_credits(tenant_id, await _cap(tenant_id))
    assert (await get_quota_status(tenant_id, "ai_credits"))["status"] == "exceeded"

    await _add_member(tenant_id)

    after = await get_quota_status(tenant_id, "ai_credits")
    assert after["status"] != "exceeded", after
    assert after["limit"] == PLANS["standard"]["credits_per_day_per_user"] * DAYS_PER_BILLING_MONTH * 2


# ── Downgrade grandfathering ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_downgrade_does_not_delete_usage_it_only_blocks_new_usage():
    """Grandfathering: dropping to a smaller tier must not erase or retroactively
    invalidate existing usage — it only means the next action is refused."""
    tenant_id = await _make_tenant("enterprise", members=2)
    await _seed_credits(tenant_id, 400_000)

    before = await get_quota_status(tenant_id, "ai_credits")
    assert before["status"] == "ok"          # 400k of 16,667*30*2 = 1,000,020 -> 40%

    async with tenant_session(tenant_id) as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        tenant.plan = "standard"
        await db.commit()

    after = await get_quota_status(tenant_id, "ai_credits")
    assert after["used"] == 400_000, "existing usage must survive a downgrade untouched"
    assert after["limit"] == PLANS["standard"]["credits_per_day_per_user"] * DAYS_PER_BILLING_MONTH * 2
    assert after["status"] == "exceeded", (
        "400k credits against Standard's ~50k cap is genuinely over. The point "
        "of this test is that the usage record survives the downgrade intact, "
        "not that the tenant stays under the smaller cap."
    )

    # And a genuinely over-limit downgrade blocks new usage without destroying
    # the record of what was already spent.
    await _seed_credits(tenant_id, 700_000)  # now 1,100,000
    over = await get_quota_status(tenant_id, "ai_credits")
    assert over["used"] == 1_100_000
    assert over["status"] == "exceeded"
