import uuid
from datetime import datetime, timezone
import pytest

from database import AsyncSessionLocal
from models.all_models import DataSource, PipelineRun, LlmUsageEvent, SourceType, RunStatus, User
from services.quota_service import credits_for_event, get_quota_status, PLANS
from sqlalchemy import select


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _register(client, prefix="quota"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Quota Test", "tenant_name": f"Quota Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


async def _seed_sources(tenant_id: str, count: int):
    async with AsyncSessionLocal() as db:
        for _ in range(count):
            db.add(DataSource(
                id=str(uuid.uuid4()), tenant_id=tenant_id, name="seed",
                source_type=SourceType.CSV, connection_config={}, is_active=True,
            ))
        await db.commit()


async def _seed_llm_usage(tenant_id: str, credits: int):
    """Seeds a single event whose credits_for_event() output equals the
    requested amount exactly, via input_tokens only (1x weight, so no
    rounding - output_tokens' 3x weight would need a division that could
    undershoot the target on integer truncation)."""
    async with AsyncSessionLocal() as db:
        db.add(LlmUsageEvent(
            id=str(uuid.uuid4()), tenant_id=tenant_id, request_type="test",
            provider="test", model="test", used_fallback=False,
            input_tokens=credits, output_tokens=0, total_tokens=credits,
            success=True, created_at=utcnow(),
        ))
        await db.commit()


def test_credits_formula_weights_output_tokens_three_x_input():
    assert credits_for_event(100, 50) == 100 * 1 + 50 * 3
    assert credits_for_event(None, None) == 0


@pytest.mark.asyncio
async def test_data_sources_quota_ok_then_exceeded(client):
    _, tenant_id = await _register(client)
    limit = PLANS["starter"]["max_data_sources"]  # 3

    ok = await get_quota_status(tenant_id, "data_sources")
    assert ok["used"] == 0 and ok["status"] == "ok"

    await _seed_sources(tenant_id, limit)
    exceeded = await get_quota_status(tenant_id, "data_sources")
    assert exceeded["used"] == limit
    assert exceeded["status"] == "exceeded"


@pytest.mark.asyncio
async def test_data_sources_quota_warning_band(client):
    _, tenant_id = await _register(client)
    # 3-limit tier can't show a clean 80% band with small integers - seed
    # against team_members instead isn't cleaner either; verify the
    # boundary condition directly for a resource with limit=3: 3*0.8=2.4,
    # so used=3 is the first integer >= that boundary, and it's also the
    # limit itself (exceeded). Confirm 2/3 is still "ok" (below 2.4).
    await _seed_sources(tenant_id, 2)
    status = await get_quota_status(tenant_id, "data_sources")
    assert status["used"] == 2 and status["status"] == "ok"


@pytest.mark.asyncio
async def test_ai_credits_quota_exceeded_blocks_chat_before_any_llm_call(client):
    """Proves the block happens before spending money on a real LLM call -
    no LLM mocking needed since the dependency short-circuits first."""
    token, tenant_id = await _register(client)
    limit = PLANS["starter"]["ai_credits_per_month"]  # 25,000
    await _seed_llm_usage(tenant_id, limit)

    r = await client.post(
        "/api/v1/chat/", json={"message": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "quota_exceeded"
    assert r.json()["detail"]["resource"] == "ai_credits"


@pytest.mark.asyncio
async def test_pipeline_runs_quota_exceeded_blocks_trigger(client):
    token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    pipe = await client.post("/api/v1/pipelines/", json={"name": "Quota Pipeline"}, headers=headers)
    pipeline_id = pipe.json()["id"]

    limit = PLANS["starter"]["pipeline_runs_per_month"]  # 100
    async with AsyncSessionLocal() as db:
        for _ in range(limit):
            db.add(PipelineRun(
                id=str(uuid.uuid4()), pipeline_id=pipeline_id, tenant_id=tenant_id,
                status=RunStatus.SUCCESS, started_at=utcnow(),
            ))
        await db.commit()

    r = await client.post(f"/api/v1/pipelines/{pipeline_id}/trigger", headers=headers)
    assert r.status_code == 402
    assert r.json()["detail"]["resource"] == "pipeline_runs"


@pytest.mark.asyncio
async def test_data_sources_quota_exceeded_blocks_create(client):
    token, tenant_id = await _register(client)
    await _seed_sources(tenant_id, PLANS["starter"]["max_data_sources"])

    r = await client.post(
        "/api/v1/sources/", json={"name": "one too many", "source_type": "csv", "connection_config": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 402
    assert r.json()["detail"]["resource"] == "data_sources"


@pytest.mark.asyncio
async def test_team_members_quota_exceeded_blocks_invite(client):
    from services.auth_service import hash_password
    token, tenant_id = await _register(client)
    limit = PLANS["starter"]["max_team_members"]  # 3, owner counts as 1

    async with AsyncSessionLocal() as db:
        for _ in range(limit - 1):
            db.add(User(
                id=str(uuid.uuid4()), tenant_id=tenant_id,
                email=f"seed-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=hash_password("x"), role="viewer", is_active=True,
            ))
        await db.commit()

    r = await client.post(
        "/api/v1/team/invites", json={"email": "onemore@example.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 402
    assert r.json()["detail"]["resource"] == "team_members"


@pytest.mark.asyncio
async def test_billing_usage_endpoint_returns_all_four_resources(client):
    token, tenant_id = await _register(client)
    r = await client.get("/api/v1/billing/usage", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    usage = r.json()["usage"]
    assert set(usage.keys()) == {"ai_credits", "pipeline_runs", "data_sources", "team_members"}
    assert usage["team_members"]["used"] == 1  # the owner themself
    assert usage["team_members"]["status"] == "ok"


@pytest.mark.asyncio
async def test_billing_plans_endpoint_is_public(client):
    r = await client.get("/api/v1/billing/plans")
    assert r.status_code == 200
    assert set(r.json()["plans"].keys()) == {"starter", "growth", "scale"}


@pytest.mark.asyncio
async def test_scale_tier_has_unlimited_data_sources(client):
    token, tenant_id = await _register(client)
    async with AsyncSessionLocal() as db:
        from models.all_models import Tenant
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalar_one()
        tenant.plan = "scale"
        await db.commit()

    await _seed_sources(tenant_id, 50)  # way past starter's limit
    status = await get_quota_status(tenant_id, "data_sources")
    assert status["limit"] is None
    assert status["status"] == "ok"
