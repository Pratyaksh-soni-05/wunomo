"""Blueprint §11 (Outputs) -- backend only (services/output_service.py,
api/v1/outputs.py, models/all_models.py's Output). Covers the four areas
the task explicitly called for: tenant isolation, the version chain,
trust aggregation (including the no-checks NULL case), and provenance
ordering. No mocks for any of the real engine calls -- QualityRuleEngine.
run_checks() is called for real against real QualityRule rows.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.all_models import (
    AgentInstance, ApprovalRequest, ApprovalStatus, Handoff, Pipeline, Project, ProjectAgent,
    QualityRule, Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus,
)
from services.output_service import OutputService, compute_trust_score
from services.tenant_context import tenant_session


async def _register(client, prefix="outputs"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Outputs Test",
        "tenant_name": f"Outputs Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"], body["user_id"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _hire(client, token, name="Ravi") -> str:
    r = await client.post("/api/v1/agents/", json={"name": name, "employee_type": "dataops"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _make_task(tenant_id, user_id, agent_id, *, goal="produce a file", minutes_ago=10) -> str:
    # completed_at always lands strictly before "now" (never in the future
    # relative to whatever create_output() stamps a moment later) -- the
    # real "task already finished" shape, not a timing artifact of the
    # test's own seeding.
    created = datetime.utcnow() - timedelta(minutes=minutes_ago)
    completed = datetime.utcnow() - timedelta(seconds=1)
    async with tenant_session(tenant_id) as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal=goal, task_shape=TaskShape.SYNC_PROFILE_QUALITY, status=TaskStatus.COMPLETED,
            step_budget_max=10, created_at=created, completed_at=completed,
        )
        db.add(task)
        await db.commit()
        return task.id


@pytest.mark.asyncio
async def test_404_for_nonexistent_output(client):
    token, _, _ = await _register(client, "notfound")
    r = await client.get(f"/api/v1/outputs/{uuid.uuid4()}", headers=_auth(token))
    assert r.status_code == 404


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_output_is_invisible_across_tenants(client):
    token_a, tenant_a, user_a = await _register(client, "tenanta")
    agent_a = await _hire(client, token_a)
    task_a = await _make_task(tenant_a, user_a, agent_a)

    created = await OutputService(tenant_a).create_output(
        task_id=task_a, agent_instance_id=agent_a, filename="report.csv",
        content_type="text/csv", size_bytes=100, storage_ref="/tmp/report.csv",
    )
    assert "error" not in created, created
    output_id = created["id"]

    # Real tenant A can see it via the real HTTP endpoint.
    r = await client.get(f"/api/v1/outputs/{output_id}", headers=_auth(token_a))
    assert r.status_code == 200

    # A second, real, unrelated tenant cannot -- not via the service layer...
    token_b, tenant_b, _ = await _register(client, "tenantb")
    assert await OutputService(tenant_b).get_output(output_id) is None

    # ...and not via the real HTTP endpoint either (404, not a leak).
    r = await client.get(f"/api/v1/outputs/{output_id}", headers=_auth(token_b))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_outputs_only_returns_this_tenants_rows(client):
    token_a, tenant_a, user_a = await _register(client, "lista")
    agent_a = await _hire(client, token_a)
    task_a = await _make_task(tenant_a, user_a, agent_a)
    await OutputService(tenant_a).create_output(
        task_id=task_a, agent_instance_id=agent_a, filename="a.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/a.csv",
    )

    token_b, tenant_b, user_b = await _register(client, "listb")
    agent_b = await _hire(client, token_b)
    task_b = await _make_task(tenant_b, user_b, agent_b)
    await OutputService(tenant_b).create_output(
        task_id=task_b, agent_instance_id=agent_b, filename="b.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/b.csv",
    )

    r = await client.get("/api/v1/outputs/", headers=_auth(token_a))
    assert r.status_code == 200
    names = {o["filename"] for o in r.json()["outputs"]}
    assert names == {"a.csv"}


@pytest.mark.asyncio
async def test_list_outputs_shows_latest_version_only(client):
    """§11's own mock shows one row per filename, not one per version --
    a superseded version must not clutter the main list, while staying
    directly retrievable by id (get_output), proven separately by the
    version-chain tests below."""
    token, tenant_id, user_id = await _register(client, "latestonly")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)
    svc = OutputService(tenant_id)

    v1 = await svc.create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/report_v1.csv",
    )
    v2 = await svc.create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/report_v2.csv",
        supersedes_output_id=v1["id"],
    )
    # An unrelated, never-superseded output in the same tenant.
    other = await svc.create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="other.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/other.csv",
    )

    listed = await svc.list_outputs()
    listed_ids = {o["id"] for o in listed}
    assert v1["id"] not in listed_ids  # superseded, excluded
    assert v2["id"] in listed_ids      # latest in its chain, included
    assert other["id"] in listed_ids   # unrelated, included

    # v1 is still directly retrievable by id -- "stays retrievable."
    assert await svc.get_output(v1["id"]) is not None


@pytest.mark.asyncio
async def test_list_and_get_resolve_agent_name_and_project_name(client):
    """The list/detail views can't show "Made by Ravi" or a project
    column off bare UUIDs -- real names, not raw ids."""
    token, tenant_id, user_id = await _register(client, "names")
    agent_id = await _hire(client, token, name="Ravi")
    project = await client.post("/api/v1/projects/", json={"name": "Hiring wave"}, headers=_auth(token))
    project_id = project.json()["id"]
    task_id = await _make_task(tenant_id, user_id, agent_id)

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="x.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/x.csv",
        project_id=project_id,
    )
    assert created["agent_name"] == "Ravi"
    assert created["employee_type"] == "dataops"
    assert created["project_name"] == "Hiring wave"

    listed = await OutputService(tenant_id).list_outputs()
    assert listed[0]["agent_name"] == "Ravi"
    assert listed[0]["project_name"] == "Hiring wave"


# ── Version chain ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_version_chain_v2_supersedes_v1_and_v1_stays_retrievable(client):
    token, tenant_id, user_id = await _register(client, "versions")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)
    svc = OutputService(tenant_id)

    v1 = await svc.create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=100, storage_ref="/tmp/report_v1.csv",
    )
    assert v1["version"] == 1
    assert v1["supersedes_output_id"] is None

    v2 = await svc.create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=120, storage_ref="/tmp/report_v2.csv",
        supersedes_output_id=v1["id"],
    )
    assert v2["version"] == 2
    assert v2["supersedes_output_id"] == v1["id"]

    v3 = await svc.create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=130, storage_ref="/tmp/report_v3.csv",
        supersedes_output_id=v2["id"],
    )
    assert v3["version"] == 3
    assert v3["supersedes_output_id"] == v2["id"]

    # v1 and v2 are never deleted or mutated -- both stay retrievable with
    # their own original version numbers, never overwritten.
    fetched_v1 = await svc.get_output(v1["id"])
    assert fetched_v1["version"] == 1
    assert fetched_v1["storage_ref"] == "/tmp/report_v1.csv"
    fetched_v2 = await svc.get_output(v2["id"])
    assert fetched_v2["version"] == 2


@pytest.mark.asyncio
async def test_supersedes_output_id_must_be_real_and_same_tenant(client):
    token, tenant_id, user_id = await _register(client, "badsupersede")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)

    result = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="x.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/x.csv",
        supersedes_output_id=str(uuid.uuid4()),
    )
    assert "error" in result


# ── Trust aggregation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_pipeline_id_means_trust_score_is_null_not_zero_or_100(client):
    score, checks = await compute_trust_score("doesn't matter", pipeline_id=None)
    assert score is None
    assert checks is None


@pytest.mark.asyncio
async def test_pipeline_with_zero_active_rules_means_trust_score_is_null(client):
    """The real engine's own run_checks() returns score=100.0 for this
    case (a sensible default for its own blocking-gate job) -- this test
    proves compute_trust_score() does NOT inherit that default."""
    token, tenant_id, _ = await _register(client, "norules")
    pipe = await client.post("/api/v1/pipelines/", json={"name": "Empty Pipeline"}, headers=_auth(token))
    pipeline_id = pipe.json()["id"]

    score, checks = await compute_trust_score(tenant_id, pipeline_id)
    assert score is None
    assert checks is None


@pytest.mark.asyncio
async def test_pipeline_with_real_rules_produces_a_real_score_and_checks(client):
    """Real QualityRuleEngine.run_checks() call, real QualityRule rows, no
    mocking -- a source-less pipeline makes every rule auto-pass
    ("No source attached -- skipping"), which is itself real engine
    behavior (modules/quality/rule_engine.py's own first check), not a
    test double standing in for it."""
    token, tenant_id, _ = await _register(client, "realrules")
    pipe = await client.post("/api/v1/pipelines/", json={"name": "Checked Pipeline"}, headers=_auth(token))
    pipeline_id = pipe.json()["id"]

    async with tenant_session(tenant_id) as db:
        db.add(QualityRule(
            id=str(uuid.uuid4()), pipeline_id=pipeline_id, tenant_id=tenant_id,
            name="has rows", rule_type="row_count", rule_config={"min_rows": 1},
            severity="high", is_blocking=True, is_active=True,
        ))
        db.add(QualityRule(
            id=str(uuid.uuid4()), pipeline_id=pipeline_id, tenant_id=tenant_id,
            name="order_id not null", rule_type="not_null", column_name="order_id",
            severity="high", is_blocking=True, is_active=True,
        ))
        await db.commit()

    score, checks = await compute_trust_score(tenant_id, pipeline_id)
    assert score == 100.0
    assert len(checks) == 2
    names = {c["check"] for c in checks}
    assert names == {"has rows", "order_id not null"}
    assert all(c["passed"] for c in checks)
    assert all(c["message"] for c in checks)  # a real human-readable line, not blank


@pytest.mark.asyncio
async def test_create_output_stores_the_real_trust_score_snapshot(client):
    token, tenant_id, user_id = await _register(client, "snapshot")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)
    pipe = await client.post("/api/v1/pipelines/", json={"name": "Snapshot Pipeline"}, headers=_auth(token))
    pipeline_id = pipe.json()["id"]

    async with tenant_session(tenant_id) as db:
        db.add(QualityRule(
            id=str(uuid.uuid4()), pipeline_id=pipeline_id, tenant_id=tenant_id,
            name="has rows", rule_type="row_count", rule_config={"min_rows": 1},
            severity="high", is_blocking=True, is_active=True,
        ))
        await db.commit()

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=100, storage_ref="/tmp/report.csv",
        pipeline_id=pipeline_id,
    )
    assert created["trust_score"] == 100.0
    assert len(created["trust_checks"]) == 1
    assert created["trust_checks"][0]["check"] == "has rows"


@pytest.mark.asyncio
async def test_create_output_with_no_pipeline_id_has_null_trust_fields(client):
    token, tenant_id, user_id = await _register(client, "nopipeline")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="notes.txt",
        content_type="text/plain", size_bytes=10, storage_ref="/tmp/notes.txt",
    )
    assert created["trust_score"] is None
    assert created["trust_checks"] is None


# ── Provenance ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provenance_story_is_chronologically_ordered_across_all_sources(client):
    token, tenant_id, user_id = await _register(client, "provenance")
    agent_id = await _hire(client, token, name="Ravi")
    other_agent_id = await _hire(client, token, name="Nova")

    now = datetime.utcnow()
    task_id = str(uuid.uuid4())
    source_task_id = str(uuid.uuid4())

    async with tenant_session(tenant_id) as db:
        # The upstream task whose handoff feeds the producing task.
        db.add(Task(
            id=source_task_id, tenant_id=tenant_id, user_id=user_id, agent_id=other_agent_id,
            goal="gather the raw numbers", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.COMPLETED, step_budget_max=10,
            created_at=now - timedelta(minutes=30), completed_at=now - timedelta(minutes=25),
        ))
        # The producing task itself.
        db.add(Task(
            id=task_id, tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="produce the report", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.COMPLETED, step_budget_max=10,
            created_at=now - timedelta(minutes=20), completed_at=now - timedelta(minutes=1),
        ))
        await db.flush()

        # A real handoff feeding the producing task.
        db.add(Handoff(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            channel_id=(await _make_real_channel(db, tenant_id)),
            from_agent_id=other_agent_id, to_agent_id=agent_id,
            from_task_id=source_task_id, to_task_id=task_id,
            payload_summary="Raw sales numbers for Q3.", withheld=[],
            created_at=now - timedelta(minutes=18),
        ))

        # A real approval that gated a step of the producing task.
        approval = ApprovalRequest(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, session_id=task_id,
            action_name="sync_source", action_args={}, risk_level="medium", reason="test",
            status=ApprovalStatus.APPROVED, resolved_by="owner@example.com",
            resolution_note="looks fine", created_at=now - timedelta(minutes=15),
            resolved_at=now - timedelta(minutes=10),
        )
        db.add(approval)
        await db.flush()
        db.add(TaskStep(
            id=str(uuid.uuid4()), task_id=task_id, tenant_id=tenant_id, step_index=0,
            description="sync the finance source", source=TaskStepSource.LLM_PLANNED,
            tool_name="sync_source", tool_args={}, status=TaskStepStatus.SUCCEEDED,
            approval_request_id=approval.id, completed_at=now - timedelta(minutes=5),
        ))
        await db.commit()

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=100, storage_ref="/tmp/report.csv",
    )

    provenance = await OutputService(tenant_id).get_provenance(created["id"])
    assert provenance is not None
    story = provenance["story"]
    types = [e["type"] for e in story]

    # Chronological order, oldest first: task_created, handoff_received,
    # approval, task_completed, output_created (output_created is always
    # last -- it's created.created_at, which is always >= task.completed_at
    # by construction in this test).
    assert types == [
        "task_created", "handoff_received", "approval", "step_executed", "task_completed", "output_created",
    ]
    assert "Raw sales numbers for Q3." in story[1]["description"]
    assert "owner@example.com" in story[2]["description"]
    # Strictly non-decreasing timestamps.
    timestamps = [e["at"] for e in story]
    assert timestamps == sorted(timestamps)


async def _make_real_channel(db, tenant_id) -> str:
    from models.all_models import Channel
    channel = Channel(id=str(uuid.uuid4()), tenant_id=tenant_id, name="test-channel")
    db.add(channel)
    await db.flush()
    return channel.id


@pytest.mark.asyncio
async def test_provenance_for_a_task_with_no_handoff_or_approval_still_works(client):
    """The honest common case: no handoff, no approval -- the story is
    just task_created, task_completed, output_created, not an error."""
    token, tenant_id, user_id = await _register(client, "minimal")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="x.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/x.csv",
    )
    provenance = await OutputService(tenant_id).get_provenance(created["id"])
    types = [e["type"] for e in provenance["story"]]
    assert types == ["task_created", "task_completed", "output_created"]


@pytest.mark.asyncio
async def test_provenance_step_executed_exposes_sql_only_when_the_step_has_one(client):
    """"show the SQL one click away where it exists" -- a step whose
    tool_args carries a real sql key exposes it; a step that doesn't
    (e.g. sync_source) must not have a fabricated sql field at all."""
    token, tenant_id, user_id = await _register(client, "sqlstep")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)

    async with tenant_session(tenant_id) as db:
        db.add(TaskStep(
            id=str(uuid.uuid4()), task_id=task_id, tenant_id=tenant_id, step_index=0,
            description="sync the source", source=TaskStepSource.LLM_PLANNED,
            tool_name="sync_source", tool_args={}, status=TaskStepStatus.SUCCEEDED,
            completed_at=datetime.utcnow() - timedelta(minutes=5),
        ))
        db.add(TaskStep(
            id=str(uuid.uuid4()), task_id=task_id, tenant_id=tenant_id, step_index=1,
            description="build the report", source=TaskStepSource.LLM_PLANNED,
            tool_name="execute_sql_transform", tool_args={"sql": "SELECT region, SUM(amount) FROM sales GROUP BY region"},
            status=TaskStepStatus.SUCCEEDED, completed_at=datetime.utcnow() - timedelta(minutes=2),
        ))
        await db.commit()

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="report.csv",
        content_type="text/csv", size_bytes=10, storage_ref="/tmp/report.csv",
    )
    provenance = await OutputService(tenant_id).get_provenance(created["id"])
    steps = [e for e in provenance["story"] if e["type"] == "step_executed"]
    assert len(steps) == 2
    assert "sql" not in steps[0]
    assert steps[1]["sql"] == "SELECT region, SUM(amount) FROM sales GROUP BY region"


@pytest.mark.asyncio
async def test_provenance_404_for_nonexistent_output(client):
    token, tenant_id, _ = await _register(client, "provenance404")
    assert await OutputService(tenant_id).get_provenance(str(uuid.uuid4())) is None
    r = await client.get(f"/api/v1/outputs/{uuid.uuid4()}/provenance", headers=_auth(token))
    assert r.status_code == 404


# ── Download ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_download_returns_the_real_file_bytes(client, tmp_path):
    from modules.ingestion.connector_manager import UPLOAD_DIR
    import os

    token, tenant_id, user_id = await _register(client, "download")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)

    real_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.csv")
    with open(real_path, "w") as f:
        f.write("order_id,amount\n1,100\n2,200\n")

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="orders.csv",
        content_type="text/csv", size_bytes=os.path.getsize(real_path), storage_ref=real_path,
    )

    r = await client.get(f"/api/v1/outputs/{created['id']}/download", headers=_auth(token))
    assert r.status_code == 200
    assert r.content == b"order_id,amount\n1,100\n2,200\n"
    os.remove(real_path)


@pytest.mark.asyncio
async def test_download_404s_when_the_underlying_file_is_gone(client):
    token, tenant_id, user_id = await _register(client, "downloadmissing")
    agent_id = await _hire(client, token)
    task_id = await _make_task(tenant_id, user_id, agent_id)

    from modules.ingestion.connector_manager import UPLOAD_DIR
    import os
    fake_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.csv")  # never actually written

    created = await OutputService(tenant_id).create_output(
        task_id=task_id, agent_instance_id=agent_id, filename="ghost.csv",
        content_type="text/csv", size_bytes=10, storage_ref=fake_path,
    )
    r = await client.get(f"/api/v1/outputs/{created['id']}/download", headers=_auth(token))
    assert r.status_code == 404
