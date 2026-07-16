import uuid
import pytest
from datetime import datetime, timezone, timedelta

from database import AsyncSessionLocal
from models.cicd import PipelineCommit
from modules.governance.policy_engine import PolicyEngine


async def _register(client, prefix="mergedapproval"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Merged Approvals Test",
        "tenant_name": f"Merged Approvals Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


async def _make_pending_commit(tenant_id, commit_sha="abc123def456", risk_score=0.8, minutes_ago=0):
    async with AsyncSessionLocal() as db:
        commit = PipelineCommit(
            id=str(uuid.uuid4()), tenant_id=tenant_id, commit_sha=commit_sha,
            branch="main", author="tester", commit_message="risky change",
            gate_decision="pending_approval", risk_score=risk_score,
            trigger_time=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        )
        db.add(commit)
        await db.commit()
        return commit.id


@pytest.mark.asyncio
async def test_merged_returns_both_sources(client):
    token, tenant_id, user_id = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    await PolicyEngine(tenant_id).create_request(
        user_id=user_id, session_id=str(uuid.uuid4()), action_name="rerun_pipeline",
        action_args={"pipeline_id": "p1"}, risk_level="medium", reason="rerun after fix",
    )
    await _make_pending_commit(tenant_id)

    r = await client.get("/api/v1/approvals/merged", headers=headers)
    assert r.status_code == 200
    body = r.json()
    sources = {a["source"] for a in body["approvals"]}
    assert sources == {"policy_engine", "cicd_deployment"}
    assert body["count"] == 2


@pytest.mark.asyncio
async def test_merged_excludes_non_pending_commits(client):
    token, tenant_id, user_id = await _register(client, "mergedexcl")
    headers = {"Authorization": f"Bearer {token}"}

    await _make_pending_commit(tenant_id, commit_sha="pending111")
    async with AsyncSessionLocal() as db:
        approved = PipelineCommit(
            id=str(uuid.uuid4()), tenant_id=tenant_id, commit_sha="approved222",
            branch="main", gate_decision="approved", risk_score=0.1,
        )
        db.add(approved)
        await db.commit()

    r = await client.get("/api/v1/approvals/merged", headers=headers)
    body = r.json()
    assert body["count"] == 1
    assert body["approvals"][0]["raw"]["commit_sha"] == "pending111"


@pytest.mark.asyncio
async def test_merged_sorted_newest_first(client):
    token, tenant_id, user_id = await _register(client, "mergedsort")
    headers = {"Authorization": f"Bearer {token}"}

    await _make_pending_commit(tenant_id, commit_sha="older111", minutes_ago=30)
    await _make_pending_commit(tenant_id, commit_sha="newer222", minutes_ago=1)

    r = await client.get("/api/v1/approvals/merged", headers=headers)
    approvals = r.json()["approvals"]
    assert approvals[0]["raw"]["commit_sha"] == "newer222"
    assert approvals[1]["raw"]["commit_sha"] == "older111"


@pytest.mark.asyncio
async def test_merged_excludes_orphaned_cicd_policy_mirror(client):
    """services/cicd_tasks.py creates a PolicyEngine ApprovalRequest with
    action_name="cicd_pipeline_deployment" alongside every high-risk commit's
    gate_decision — that action isn't in TOOL_REGISTRY, so approving it via
    the general path always fails without deploying anything. It must not
    show up as an actionable merged item, even though a real (non-mirror)
    policy_engine approval for something else still should."""
    token, tenant_id, user_id = await _register(client, "mergedorphan")
    headers = {"Authorization": f"Bearer {token}"}

    await PolicyEngine(tenant_id).create_request(
        user_id="system", session_id=str(uuid.uuid4()), action_name="cicd_pipeline_deployment",
        action_args={"commit_id": "orphan-commit"}, risk_level="high",
        reason="High-risk pipeline change requires approval. Risk score: 65/100",
    )
    await PolicyEngine(tenant_id).create_request(
        user_id=user_id, session_id=str(uuid.uuid4()), action_name="rerun_pipeline",
        action_args={"pipeline_id": "p1"}, risk_level="medium", reason="a real, separate request",
    )

    r = await client.get("/api/v1/approvals/merged", headers=headers)
    body = r.json()
    action_names = {a["title"] for a in body["approvals"]}
    assert "cicd_pipeline_deployment" not in action_names
    assert "rerun_pipeline" in action_names
    assert body["count"] == 1


@pytest.mark.asyncio
async def test_merged_risk_level_uses_the_real_0_to_100_scale(client):
    """risk_score is 0-100 everywhere in this codebase (cicd_tasks.py's
    AUTO_APPROVE_THRESHOLD=60, its own "Risk score: N/100" phrasing) — a
    bucketing bug that assumed 0-1 would call every nonzero score "high"."""
    token, tenant_id, user_id = await _register(client, "mergedriskscale")
    headers = {"Authorization": f"Bearer {token}"}

    await _make_pending_commit(tenant_id, commit_sha="lowrisk", risk_score=15)
    await _make_pending_commit(tenant_id, commit_sha="medrisk", risk_score=55)
    await _make_pending_commit(tenant_id, commit_sha="hirisk", risk_score=85)

    r = await client.get("/api/v1/approvals/merged", headers=headers)
    by_sha = {a["raw"]["commit_sha"]: a["risk_level"] for a in r.json()["approvals"]}
    assert by_sha["lowrisk"] == "low"
    assert by_sha["medrisk"] == "medium"
    assert by_sha["hirisk"] == "high"


@pytest.mark.asyncio
async def test_merged_is_tenant_scoped(client):
    token_a, tenant_a, user_a = await _register(client, "mergedtena")
    token_b, tenant_b, user_b = await _register(client, "mergedtenb")

    await _make_pending_commit(tenant_a, commit_sha="tenantacommit")
    await _make_pending_commit(tenant_b, commit_sha="tenantbcommit")

    r_a = await client.get("/api/v1/approvals/merged", headers={"Authorization": f"Bearer {token_a}"})
    r_b = await client.get("/api/v1/approvals/merged", headers={"Authorization": f"Bearer {token_b}"})

    shas_a = {a["raw"]["commit_sha"] for a in r_a.json()["approvals"]}
    shas_b = {a["raw"]["commit_sha"] for a in r_b.json()["approvals"]}
    assert shas_a == {"tenantacommit"}
    assert shas_b == {"tenantbcommit"}
