import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import OnboardingProfile


async def _register(client, name):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"onboardtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Onboarding Test",
        "tenant_name": name,
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


@pytest.mark.asyncio
async def test_onboarding_not_completed_before_submission(client):
    token, tenant_id = await _register(client, "Onboarding Test Corp 1")
    r = await client.get("/api/v1/onboarding/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"completed": False}


@pytest.mark.asyncio
async def test_onboarding_submit_persists_and_is_retrievable(client):
    token, tenant_id = await _register(client, "Onboarding Test Corp 2")
    payload = {
        "role": "Data Engineer",
        "industry": "Fintech",
        "company_size": "11-50",
        "use_cases": ["Pipeline monitoring", "Data quality"],
        "data_stack": ["PostgreSQL", "Snowflake", "dbt"],
    }
    post = await client.post("/api/v1/onboarding/", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert post.status_code == 200
    assert post.json()["role"] == "Data Engineer"
    assert post.json()["data_stack"] == ["PostgreSQL", "Snowflake", "dbt"]

    get = await client.get("/api/v1/onboarding/", headers={"Authorization": f"Bearer {token}"})
    body = get.json()
    assert body["completed"] is True
    assert body["industry"] == "Fintech"
    assert body["use_cases"] == ["Pipeline monitoring", "Data quality"]

    async with AsyncSessionLocal() as db:
        row = await db.get(OnboardingProfile, post.json()["id"])
    assert row is not None
    assert row.tenant_id == tenant_id
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_onboarding_resubmit_upserts_instead_of_duplicating(client):
    token, tenant_id = await _register(client, "Onboarding Test Corp 3")
    first = await client.post("/api/v1/onboarding/", json={"role": "Data Engineer"}, headers={"Authorization": f"Bearer {token}"})
    second = await client.post("/api/v1/onboarding/", json={"role": "Analytics Lead"}, headers={"Authorization": f"Bearer {token}"})

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["role"] == "Analytics Lead"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        r = await db.execute(select(OnboardingProfile).where(OnboardingProfile.tenant_id == tenant_id))
        rows = r.scalars().all()
    assert len(rows) == 1
    assert rows[0].role == "Analytics Lead"


@pytest.mark.asyncio
async def test_onboarding_is_tenant_isolated(client):
    token_a, tenant_a = await _register(client, "Onboarding Test Corp 4a")
    token_b, tenant_b = await _register(client, "Onboarding Test Corp 4b")

    await client.post("/api/v1/onboarding/", json={"role": "Tenant A role"}, headers={"Authorization": f"Bearer {token_a}"})

    get_b = await client.get("/api/v1/onboarding/", headers={"Authorization": f"Bearer {token_b}"})
    assert get_b.json() == {"completed": False}


@pytest.mark.asyncio
async def test_register_and_login_unaffected_by_onboarding_table(client):
    """Regression test for Phase 4's explicit verification gate: adding
    OnboardingProfile must not change register()/login() behavior at all."""
    email = f"onboardtest-{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
        "full_name": "Unaffected Test", "tenant_name": "Unaffected Test Corp",
    })
    assert reg.status_code == 200
    assert "access_token" in reg.json()

    login = await client.post("/api/v1/auth/login", data={"username": email, "password": "test1234"})
    assert login.status_code == 200
    assert "access_token" in login.json()
