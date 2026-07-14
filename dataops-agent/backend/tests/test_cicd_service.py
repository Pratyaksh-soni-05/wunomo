import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import Pipeline, PipelineStatus
from services.cicd_service import get_pipeline_for_repo


async def _make_pipeline(tenant_id: str, repo_url: str = None, status=PipelineStatus.ACTIVE) -> Pipeline:
    """Insert a real Pipeline row via the real model/columns — no mock,
    no hand-rolled schema — so this test would have caught the
    is_active/source_config column-name bug directly."""
    async with AsyncSessionLocal() as db:
        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name="test pipeline",
            status=status,
            pipeline_config={"repo_url": repo_url} if repo_url else {},
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)
        return pipeline


@pytest.mark.asyncio
async def test_get_pipeline_for_repo_matches_real_schema(client):
    """Regression test for get_pipeline_for_repo() referencing nonexistent
    columns (Pipeline.is_active, Pipeline.source_config) — the real Pipeline
    model has `status` (enum) and `pipeline_config` instead. This test hits
    the real Pipeline model/table directly (via AsyncSessionLocal), not a
    mock, so a wrong column name fails with a real AttributeError/
    ProgrammingError instead of silently passing against a fixture that
    happens to define whatever columns the code expects.
    """
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"cicdtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "CICD Test",
        "tenant_name": "CICD Test Corp",
    })
    tenant_id = reg.json()["tenant_id"]

    repo_url = f"https://github.com/example/repo-{uuid.uuid4().hex[:8]}"
    matching_pipeline = await _make_pipeline(tenant_id, repo_url=repo_url)
    await _make_pipeline(tenant_id, repo_url="https://github.com/example/other-repo")
    await _make_pipeline(tenant_id, repo_url=repo_url, status=PipelineStatus.PAUSED)

    async with AsyncSessionLocal() as db:
        found = await get_pipeline_for_repo(db, tenant_id, repo_url)

    assert found is not None
    assert found.id == matching_pipeline.id


@pytest.mark.asyncio
async def test_get_pipeline_for_repo_returns_none_when_no_match(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"cicdtest-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "CICD Test",
        "tenant_name": "CICD Test Corp 2",
    })
    tenant_id = reg.json()["tenant_id"]
    await _make_pipeline(tenant_id, repo_url="https://github.com/example/unrelated")

    async with AsyncSessionLocal() as db:
        found = await get_pipeline_for_repo(db, tenant_id, "https://github.com/example/no-such-repo")

    assert found is None
