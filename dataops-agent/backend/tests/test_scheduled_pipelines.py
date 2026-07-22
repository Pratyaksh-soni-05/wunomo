import uuid
import pytest

from database import AsyncSessionLocal
from models.all_models import Pipeline, PipelineRun, PipelineStatus, RunStatus
from services.tasks import _create_scheduled_run, _check_scheduled_pipelines


async def _register(client, prefix="scheduled"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Scheduled Pipeline Test",
        "tenant_name": f"Scheduled Pipeline Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


async def _make_pipeline(tenant_id: str, cron: str | None, status=PipelineStatus.ACTIVE) -> str:
    async with AsyncSessionLocal() as db:
        p = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="test pipeline",
            status=status, schedule_cron=cron,
        )
        db.add(p)
        await db.commit()
        return p.id


@pytest.mark.asyncio
async def test_create_scheduled_run_creates_a_real_pending_run(client):
    _, tenant_id = await _register(client)
    pipeline_id = await _make_pipeline(tenant_id, "* * * * *")

    run_id = await _create_scheduled_run(pipeline_id, tenant_id)
    assert run_id is not None

    async with AsyncSessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
    assert run.status == RunStatus.PENDING
    assert run.triggered_by == "scheduled"
    assert run.pipeline_id == pipeline_id
    assert run.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_create_scheduled_run_skips_paused_pipeline(client):
    """A pipeline that was paused after its schedule was decided must not
    get a run created for it - regression guard against a race between
    pause and a scheduled firing that was already in flight."""
    _, tenant_id = await _register(client)
    pipeline_id = await _make_pipeline(tenant_id, "* * * * *", status=PipelineStatus.PAUSED)

    run_id = await _create_scheduled_run(pipeline_id, tenant_id)
    assert run_id is None


@pytest.mark.asyncio
async def test_create_scheduled_run_skips_deleted_pipeline(client):
    run_id = await _create_scheduled_run("nonexistent-pipeline-id", "nonexistent-tenant")
    assert run_id is None


@pytest.mark.asyncio
async def test_check_scheduled_pipelines_fires_matching_cron_and_skips_others(client, monkeypatch):
    """The core of the fix: check_scheduled_pipelines() must fire a pipeline
    whose cron matches the current minute (* * * * * always matches) and
    must NOT fire one whose cron clearly doesn't (a fixed date far in the
    past/future can never match "now"). Mocks execute_scheduled_pipeline_run
    .delay() to observe what actually got dispatched without needing a real
    Celery worker."""
    _, tenant_id = await _register(client)
    due_pipeline = await _make_pipeline(tenant_id, "* * * * *")
    never_due_pipeline = await _make_pipeline(tenant_id, "0 0 1 1 *")  # only Jan 1st, midnight
    paused_pipeline = await _make_pipeline(tenant_id, "* * * * *", status=PipelineStatus.PAUSED)
    unscheduled_pipeline = await _make_pipeline(tenant_id, None)

    import services.tasks as tasks_module
    fired = []

    class FakeDelay:
        def delay(self, pipeline_id, tenant_id):
            fired.append((pipeline_id, tenant_id))

    monkeypatch.setattr(tasks_module, "execute_scheduled_pipeline_run", FakeDelay())

    await _check_scheduled_pipelines()

    fired_ids = {pid for pid, _ in fired}
    assert due_pipeline in fired_ids
    assert never_due_pipeline not in fired_ids
    assert paused_pipeline not in fired_ids
    assert unscheduled_pipeline not in fired_ids


@pytest.mark.asyncio
async def test_check_scheduled_pipelines_invalid_cron_does_not_crash(client, monkeypatch):
    """A pipeline that somehow has a malformed schedule_cron (e.g. written
    directly to the DB, bypassing the save-time validation added in this
    same fix) must be skipped with a warning, not crash the whole poll and
    starve every other tenant's pipelines of their own scheduled runs."""
    _, tenant_id = await _register(client)
    async with AsyncSessionLocal() as db:
        p = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="malformed cron pipeline",
            status=PipelineStatus.ACTIVE, schedule_cron="not a real cron",
        )
        db.add(p)
        good_pipeline = Pipeline(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="good pipeline",
            status=PipelineStatus.ACTIVE, schedule_cron="* * * * *",
        )
        db.add(good_pipeline)
        await db.commit()
        good_id = good_pipeline.id

    import services.tasks as tasks_module
    fired = []

    class FakeDelay:
        def delay(self, pipeline_id, tenant_id):
            fired.append(pipeline_id)

    monkeypatch.setattr(tasks_module, "execute_scheduled_pipeline_run", FakeDelay())

    await _check_scheduled_pipelines()  # must not raise

    assert good_id in fired


@pytest.mark.asyncio
async def test_create_pipeline_rejects_invalid_cron(client):
    token, _ = await _register(client)
    r = await client.post("/api/v1/pipelines/", json={
        "name": "bad cron pipeline", "schedule_cron": "not a cron",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert "cron" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_pipeline_accepts_valid_cron(client):
    token, _ = await _register(client)
    r = await client.post("/api/v1/pipelines/", json={
        "name": "good cron pipeline", "schedule_cron": "*/5 * * * *",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_set_schedule_rejects_invalid_cron(client):
    token, _ = await _register(client)
    create = await client.post("/api/v1/pipelines/", json={"name": "p"},
                                headers={"Authorization": f"Bearer {token}"})
    pipeline_id = create.json()["id"]

    r = await client.put(f"/api/v1/pipelines/{pipeline_id}/schedule", json={"cron": "99 99 * * *"},
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_pipelines_reports_next_run_and_last_run(client):
    token, tenant_id = await _register(client)
    r = await client.post("/api/v1/pipelines/", json={
        "name": "visibility test pipeline", "schedule_cron": "*/10 * * * *",
    }, headers={"Authorization": f"Bearer {token}"})
    pipeline_id = r.json()["id"]

    # Fresh pipeline: no runs yet, so last_run is None; but a DRAFT pipeline
    # (the real status create_pipeline() assigns) has no next_run_at either,
    # since only ACTIVE pipelines are ever actually fired.
    listed = await client.get("/api/v1/pipelines/", headers={"Authorization": f"Bearer {token}"})
    row = next(p for p in listed.json()["pipelines"] if p["id"] == pipeline_id)
    assert row["last_run"] is None
    assert row["next_run_at"] is None  # DRAFT, not yet activated

    await client.post(f"/api/v1/pipelines/{pipeline_id}/activate",
                       headers={"Authorization": f"Bearer {token}"})
    run_id = await _create_scheduled_run(pipeline_id, tenant_id)
    assert run_id is not None

    listed2 = await client.get("/api/v1/pipelines/", headers={"Authorization": f"Bearer {token}"})
    row2 = next(p for p in listed2.json()["pipelines"] if p["id"] == pipeline_id)
    assert row2["last_run"]["id"] == run_id
    assert row2["last_run"]["status"] == "pending"
    assert row2["next_run_at"] is not None  # now ACTIVE with a real cron
