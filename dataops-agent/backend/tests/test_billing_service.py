import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import User, Tenant
from sqlalchemy import select
from services.auth_service import issue_token_for_user
from services.billing_service import BillingService


async def _register(client, prefix="billing"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Billing Test", "tenant_name": f"Billing Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


@pytest.mark.asyncio
async def test_get_usage_returns_all_four_resources(client):
    _, tenant_id, _ = await _register(client)
    usage = await BillingService(tenant_id).get_usage()
    assert set(usage.keys()) == {"ai_credits", "pipeline_runs", "data_sources", "team_members"}


@pytest.mark.asyncio
async def test_get_plan_defaults_to_starter(client):
    _, tenant_id, _ = await _register(client)
    plan = await BillingService(tenant_id).get_plan()
    assert plan["plan"] == "starter"
    assert plan["limits"]["max_data_sources"] == 3


@pytest.mark.asyncio
async def test_change_plan_updates_tenant_and_is_reflected_in_get_plan(client):
    _, tenant_id, _ = await _register(client)
    result = await BillingService(tenant_id).change_plan("growth")
    assert result["plan"] == "growth"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant.plan).where(Tenant.id == tenant_id))
        assert r.scalar() == "growth"

    plan = await BillingService(tenant_id).get_plan()
    assert plan["plan"] == "growth"
    assert plan["limits"]["max_data_sources"] == 15


@pytest.mark.asyncio
async def test_change_plan_rejects_unknown_plan(client):
    _, tenant_id, _ = await _register(client)
    result = await BillingService(tenant_id).change_plan("enterprise-deluxe")
    assert "error" in result


@pytest.mark.asyncio
async def test_owner_can_change_plan_via_endpoint_and_it_affects_quota(client):
    token, tenant_id, _ = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/billing/change-plan", json={"plan": "scale"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["plan"] == "scale"

    plan_check = await client.get("/api/v1/billing/plan", headers=headers)
    assert plan_check.json()["plan"] == "scale"

    usage = await client.get("/api/v1/billing/usage", headers=headers)
    assert usage.json()["usage"]["data_sources"]["limit"] is None  # scale = unlimited


@pytest.mark.asyncio
async def test_viewer_cannot_change_plan(client):
    from services.auth_service import hash_password
    _, tenant_id, user_id = await _register(client)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
        await db.refresh(user)
        viewer_token = issue_token_for_user(user, "password")

    r = await client.post(
        "/api/v1/billing/change-plan", json={"plan": "growth"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_change_plan_endpoint_rejects_unknown_plan(client):
    token, tenant_id, _ = await _register(client)
    r = await client.post(
        "/api/v1/billing/change-plan", json={"plan": "not-a-real-plan"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_checkout_and_webhook_endpoints_are_honest_stubs(client):
    token, tenant_id, _ = await _register(client)
    r = await client.post("/api/v1/billing/checkout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 501

    r2 = await client.post("/api/v1/billing/webhook")
    assert r2.status_code == 501


@pytest.mark.asyncio
async def test_billing_service_stubs_raise_not_implemented(client):
    _, tenant_id, _ = await _register(client)
    svc = BillingService(tenant_id)
    with pytest.raises(NotImplementedError):
        await svc.create_checkout_session("growth")
    with pytest.raises(NotImplementedError):
        await svc.get_subscription_status()
    with pytest.raises(NotImplementedError):
        await svc.cancel_subscription()
    with pytest.raises(NotImplementedError):
        await svc.handle_webhook({})
