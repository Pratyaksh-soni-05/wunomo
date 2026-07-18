import uuid
import pytest
from datetime import datetime, timezone

from database import AsyncSessionLocal
from models.cicd import PipelineCommit
from models.all_models import ApprovalRequest
from sqlalchemy import select
import services.cicd_tasks as cicd_tasks


async def _register(client, prefix="cicdnodupe"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "CICD No Dupe Test", "tenant_name": f"CICD No Dupe Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


@pytest.mark.asyncio
async def test_high_risk_commit_sets_pending_approval_but_creates_no_duplicate_approval_request(client, monkeypatch):
    """Regression for the resolved 'CI/CD high-risk commits double-book
    their approval into two never-linked tables' bug: run_ci_pipeline used
    to both set PipelineCommit.gate_decision AND separately create a
    PolicyEngine ApprovalRequest (action_name='cicd_pipeline_deployment')
    for the same event - the latter was orphaned (never registered in
    TOOL_REGISTRY, so approving it always failed) and has been removed.
    This test forces a high risk score via monkeypatch rather than trying
    to trigger all 4 real check functions into a specific combined score -
    the actual risk *calculation* is unrelated to and unaffected by this
    fix, and is separately covered elsewhere."""
    monkeypatch.setattr(cicd_tasks, "calculate_risk_score", lambda check_results, changed: 90.0)

    token, tenant_id = await _register(client)
    pipe = await client.post(
        "/api/v1/pipelines/", json={"name": "No Dupe Pipeline"},
        headers={"Authorization": f"Bearer {token}"},
    )
    pipeline_id = pipe.json()["id"]

    commit_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(PipelineCommit(
            id=commit_id, tenant_id=tenant_id, pipeline_id=pipeline_id,
            commit_sha="deadbeef1234", branch="main", author="tester",
            commit_message="a real change", changed_files=[],
            trigger_time=datetime.now(timezone.utc),
        ))
        await db.commit()

    import asyncio
    # run_ci_pipeline calls asyncio.run() internally (real Celery-task
    # behavior), which can't nest inside pytest-asyncio's already-running
    # loop - run it in a separate thread, which gets its own fresh loop.
    await asyncio.to_thread(cicd_tasks.run_ci_pipeline.run, commit_id, tenant_id)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(PipelineCommit).where(PipelineCommit.id == commit_id))
        commit = r.scalar_one()
        assert commit.gate_decision == "pending_approval"  # the real, tested path still works

        ar = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.action_name == "cicd_pipeline_deployment",
            )
        )
        assert ar.scalars().all() == []  # no duplicate ever written


@pytest.mark.asyncio
async def test_merged_approvals_shows_the_commit_exactly_once(client, monkeypatch):
    """End-to-end proof the fix doesn't just avoid writing the duplicate
    row in isolation, but that the real user-facing symptom (the same
    commit appearing twice in the merged approvals view) is gone."""
    monkeypatch.setattr(cicd_tasks, "calculate_risk_score", lambda check_results, changed: 90.0)

    token, tenant_id = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    pipe = await client.post("/api/v1/pipelines/", json={"name": "No Dupe Pipeline 2"}, headers=headers)
    pipeline_id = pipe.json()["id"]

    commit_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(PipelineCommit(
            id=commit_id, tenant_id=tenant_id, pipeline_id=pipeline_id,
            commit_sha="cafebabe5678", branch="main", author="tester",
            commit_message="another real change", changed_files=[],
            trigger_time=datetime.now(timezone.utc),
        ))
        await db.commit()

    import asyncio
    # run_ci_pipeline calls asyncio.run() internally (real Celery-task
    # behavior), which can't nest inside pytest-asyncio's already-running
    # loop - run it in a separate thread, which gets its own fresh loop.
    await asyncio.to_thread(cicd_tasks.run_ci_pipeline.run, commit_id, tenant_id)

    r = await client.get("/api/v1/approvals/merged", headers=headers)
    assert r.status_code == 200
    approvals = r.json()["approvals"]

    cicd_deployment_matches = [a for a in approvals if a["source"] == "cicd_deployment" and a["id"] == commit_id]
    policy_engine_matches = [
        a for a in approvals
        if a["source"] == "policy_engine" and a.get("action_args", {}).get("commit_id") == commit_id
    ]
    assert len(cicd_deployment_matches) == 1  # the one real, role-gated approval path
    assert len(policy_engine_matches) == 0    # no orphaned duplicate anymore
