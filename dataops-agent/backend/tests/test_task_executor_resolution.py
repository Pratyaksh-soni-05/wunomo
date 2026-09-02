"""Tier 1 argument resolution (2026-08 — see docs/context/SESSION_LOG.md
for the full diagnosis and docs/context/WALKTHROUGH_FINDINGS_2026-08.md
items 8/9). Two properties this suite exists specifically to guard,
per explicit instruction that a future refactor could otherwise break
silently without any test noticing:

1. Idempotency — a step's args are resolved at most once, ever. Re-
   entering execute_next_step() on a resume must not re-run resolution,
   because the approval card the human reviewed already showed the
   resolved value; re-resolving afterward would mean approving one thing
   and executing another, exactly the failure mode this design exists to
   prevent.
2. Human-edited steps are never touched by resolution, even when a
   deterministic match is available and the human's value looks wrong —
   a human who typed a specific value meant that value.

Also covers Commit 4 (honest failure messaging): when neither tier can
resolve a reference, the final failure message says so explicitly
instead of only repeating the raw tool error.
"""
import uuid

import pytest
from sqlalchemy import select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import execute_next_step, resume_task
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus


async def _register(client, prefix="taskresolve"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Resolution Test",
        "tenant_name": f"Task Resolution Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _seed_task_with_discovery(
    tenant_id, user_id, *, discovery_raw_result, discovery_tool_name,
    step_tool_name, step_tool_args, step_description, step_source=TaskStepSource.LLM_PLANNED,
):
    """A two-step task: a discovery step already SUCCEEDED with a real
    raw_result, and the dependent step PENDING right behind it — matching
    exactly the shape execute_next_step() picks up next (lowest step_index
    PENDING step whose depends_on_step_index is already SUCCEEDED)."""
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            goal="test", task_shape=TaskShape.SYNC_PROFILE_QUALITY,
            status=TaskStatus.RUNNING, step_budget_max=20,
        )
        db.add(task)
        await db.flush()
        discovery_step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="Discover the real entities.", source=TaskStepSource.LLM_PLANNED,
            tool_name=discovery_tool_name, tool_args={},
            status=TaskStepStatus.SUCCEEDED, raw_result=discovery_raw_result,
            attempt_count=1,
        )
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=1,
            description=step_description, source=step_source,
            tool_name=step_tool_name, tool_args=step_tool_args,
            status=TaskStepStatus.PENDING, depends_on_step_index=0,
        )
        db.add(discovery_step)
        db.add(step)
        await db.commit()
        return task.id, step.id


async def _fresh_step(step_id):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        return r.scalar_one()


@pytest.mark.asyncio
async def test_resolution_is_noop_on_resume(client, monkeypatch):
    tenant_id, user_id = await _register(client, "resolvenoop")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result={"sources": [{"id": "src-real-123", "name": "Sales Orders"}], "count": 1},
        discovery_tool_name="list_data_sources",
        step_tool_name="sync_source",
        step_tool_args={"source_id": "sales_orders_source_id"},  # the real, observed placeholder shape
        step_description="Trigger an incremental sync for the Sales Orders data source.",
    )

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_needs_approval"

    step = await _fresh_step(step_id)
    # Tier 1 resolved it before the approval card could ever render this
    # value — this is what the human would have seen on the card.
    assert step.tool_args["source_id"] == "src-real-123"
    approved_args = dict(step.tool_args)

    # Prove resolution does not fire a second time on resume. If it did,
    # this monkeypatch makes the failure obvious instead of silently
    # producing the same (coincidentally correct) value twice.
    async def _poison(*args, **kwargs):
        raise AssertionError("_resolve_step_args was called again on resume — idempotency broken")
    monkeypatch.setattr(executor_module, "_resolve_step_args", _poison)

    seen_args = {}

    async def _capture(tenant_id, tool_name, tool_args, **kwargs):
        seen_args.update(tool_args)
        return {"status": "synced", "rows": 5}
    monkeypatch.setattr(executor_module, "_call_tool", _capture)

    result = await resume_task(task_id, resolved_by=str(uuid.uuid4()))
    assert result["outcome"] == "step_succeeded"

    # What executed is byte-identical to what was displayed on the card —
    # the entire point of resolving before the gate, not after it.
    assert seen_args == approved_args
    step = await _fresh_step(step_id)
    assert step.tool_args["source_id"] == "src-real-123"


@pytest.mark.asyncio
async def test_resolution_skips_human_edited_args(client):
    tenant_id, user_id = await _register(client, "resolvehumanedit")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result={"sources": [{"id": "src-real-123", "name": "Sales Orders"}], "count": 1},
        discovery_tool_name="list_data_sources",
        step_tool_name="sync_source",
        # Deliberately a value that does NOT match anything real, and that
        # a deterministic pass over this description WOULD "correct" to
        # src-real-123 if it were allowed to run. A human is presumed to
        # have meant this value, wrong-looking or not.
        step_tool_args={"source_id": "human-typed-value"},
        step_description="Trigger an incremental sync for the Sales Orders data source.",
        step_source=TaskStepSource.HUMAN_EDITED,
    )

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_needs_approval"

    step = await _fresh_step(step_id)
    assert step.tool_args["source_id"] == "human-typed-value"


@pytest.mark.asyncio
async def test_tier2_never_substitutes_an_undiscovered_or_ambiguous_entity(client, monkeypatch):
    """Item 32 (2026-08-17, found live): Tier 2's LLM adapt call must never
    silently retarget a step onto a different real entity when the one the
    plan actually meant doesn't exist. Two discovered pipelines, neither
    named by the step's own description — Tier 1 correctly finds 0
    candidates (already covered above), and here Tier 2 is mocked to
    propose one of the two real-but-wrong pipeline ids anyway, exactly
    reproducing the live bug (a diagnose_pipeline_failure task targeting a
    nonexistent "Zephyr Cargo Manifest Pipeline" got silently pointed at
    the real "Sales Ingestion Pipeline" instead). The guardrail
    (_reject_ungrounded_adaptation) must revert the proposed id — 2 real
    candidates with nothing narrowing it down is exactly the kind of guess
    Tier 1 already refuses to make — so the step fails honestly instead of
    succeeding against the wrong pipeline."""
    tenant_id, user_id = await _register(client, "resolveneverguess")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result={
            "pipelines": [
                {"id": "pl-real-1", "name": "HR Sync Pipeline"},
                {"id": "pl-real-2", "name": "Sales Ingestion Pipeline"},
            ],
            "count": 2,
        },
        discovery_tool_name="list_pipelines",
        step_tool_name="get_pipeline_run_history",
        step_tool_args={"pipeline_id": "zephyr_cargo_manifest_pipeline_id"},
        step_description="Retrieve the run history for the Zephyr Cargo Manifest Pipeline to diagnose the failures.",
    )

    seen_args = []

    async def _always_not_found(tenant_id, tool_name, tool_args, **kwargs):
        seen_args.append(dict(tool_args))
        return {"error": "Pipeline not found"}

    async def _wrongly_substitutes(tenant_id, user_id, description, tool_name, tool_args, error_message, prior_results=None, task_id=None):
        # Simulates exactly the live bug: picks a REAL id from prior_results
        # that has nothing to do with what the step actually asked for.
        return {**tool_args, "pipeline_id": "pl-real-2"}

    monkeypatch.setattr(executor_module, "_call_tool", _always_not_found)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _wrongly_substitutes)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_failed"

    # The guardrail must have reverted the substitution on every attempt --
    # the wrong-but-real id must never have reached the tool at all.
    assert all(a["pipeline_id"] != "pl-real-2" for a in seen_args)

    step = await _fresh_step(step_id)
    assert step.status == TaskStepStatus.FAILED
    assert "Could not determine the real value for 'pipeline_id'" in step.error_message
    # Tier 1's own (description-text-matched) candidate count is 0 here --
    # neither real pipeline's name appears in this step's description --
    # which is exactly why Tier 2 was reached at all; the guardrail's
    # "exactly one, from the full pool" check is separate evidence and is
    # what actually blocked the substitution (proven above via seen_args).
    assert "no match" in step.error_message
    assert "Pipeline not found" in step.error_message


@pytest.mark.asyncio
async def test_honest_failure_message_when_neither_tier_resolves(client, monkeypatch):
    """Commit 4: a reference that never matches anything real (0
    candidates, and Tier 2 can't improve on it either) fails with an
    explicit "could not determine the real value" note, not just the raw
    tool error repeated back — the raw error blames the entity for not
    existing when the actual problem was the argument was never real to
    begin with. Uses get_pipeline_run_history/list_pipelines (a low-risk,
    auto-run tool, no approval gate in the way) to exercise the final
    attempt-budget-exhausted failure path directly."""
    tenant_id, user_id = await _register(client, "resolvehonestfail")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result={"pipelines": [{"id": "pl-real-1", "name": "Sales Ingestion Pipeline"}], "count": 1},
        discovery_tool_name="list_pipelines",
        step_tool_name="get_pipeline_run_history",
        # Deliberately unrelated to anything discovered — 0 candidates.
        step_tool_args={"pipeline_id": "totally_unrelated_guess"},
        step_description="Check recent runs for a pipeline nothing here describes by name.",
    )

    async def _always_not_found(tenant_id, tool_name, tool_args, **kwargs):
        return {"error": "Pipeline not found"}

    async def _cant_improve(tenant_id, user_id, description, tool_name, tool_args, error_message, prior_results=None, task_id=None):
        return tool_args  # Tier 2 also has nothing to go on

    monkeypatch.setattr(executor_module, "_call_tool", _always_not_found)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _cant_improve)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_failed"

    step = await _fresh_step(step_id)
    assert step.status == TaskStepStatus.FAILED
    assert "Could not determine the real value for 'pipeline_id'" in step.error_message
    assert "no match" in step.error_message
    assert "Pipeline not found" in step.error_message  # the real underlying error is still present, not replaced


@pytest.mark.asyncio
async def test_tier1_resolves_a_real_paraphrase_via_token_overlap(client, monkeypatch):
    """2026-09: Tier 1 used to require an exact substring match, so "the
    sales pipeline" never resolved against the real "Sales Ingestion
    Pipeline" (no substring relation in either direction) — a real, live
    failure that cost an extra real LLM call every time it happened (see
    docs/context/GOTCHAS.md for the full incident). Token-overlap scoring
    (_score_candidates) must resolve this exact case, with a clear margin:
    real numbers from that live failure are top=0.5 (Sales Ingestion
    Pipeline) vs 0.0 (HR Sync Pipeline shares no non-generic token with
    the description at all)."""
    tenant_id, user_id = await _register(client, "resolveparaphrase")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result={
            "pipelines": [
                {"id": "pl-sales", "name": "Sales Ingestion Pipeline"},
                {"id": "pl-hr", "name": "HR Sync Pipeline"},
            ],
            "count": 2,
        },
        discovery_tool_name="list_pipelines",
        step_tool_name="get_pipeline_run_history",
        step_tool_args={"pipeline_id": "sales_pipeline"},
        step_description="Get the run history of the sales pipeline to diagnose why it is lagging.",
    )

    seen_args = []

    async def _capture(tenant_id, tool_name, tool_args, **kwargs):
        seen_args.append(dict(tool_args))
        return {"pipeline_id": tool_args.get("pipeline_id"), "runs": []}

    monkeypatch.setattr(executor_module, "_call_tool", _capture)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_succeeded"
    assert seen_args == [{"pipeline_id": "pl-sales"}]


@pytest.mark.asyncio
async def test_tier1_refuses_a_tied_pool_instead_of_guessing(client):
    """2026-09: token-overlap scoring must still refuse — not just plain
    substring matching — when multiple discovered candidates score
    identically against a vague description. Real repro (2026-09-02): 20+
    near-identical "Stale data: <source> (Nh overdue)" incidents on the
    same real tenant, all sharing "stale"/"data"/"overdue" (correctly
    stripped as generic terms) and the discriminating "sales"/"orders"
    tokens equally across every Sales Orders variant — see
    docs/context/GOTCHAS.md for the full real numbers (0.025 tied across
    all 10 Sales Orders incidents, a 1.0x margin). Reproduced here with 2
    of them, enough to prove the tie-refusal without seeding all 20."""
    tenant_id, user_id = await _register(client, "resolvetiedpool")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result=[
            {"incident_id": "inc-1", "title": "Stale data: Sales Orders (195.5h overdue)"},
            {"incident_id": "inc-2", "title": "Stale data: Sales Orders (196.0h overdue)"},
        ],
        discovery_tool_name="list_open_incidents",
        step_tool_name="triage_incident",
        step_tool_args={"incident_id": "sales_orders_stale_incident"},
        step_description="Perform root cause analysis on the identified stale sales data incident.",
    )

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_needs_approval"  # triage_incident is medium-risk

    step = await _fresh_step(step_id)
    # Tier 1 refused (tied pool, 1.0x margin) — the unresolved placeholder
    # reaches the approval card exactly as-is, never a guessed id.
    assert step.tool_args["incident_id"] == "sales_orders_stale_incident"


@pytest.mark.asyncio
async def test_tier1_refuses_when_the_discovered_pool_is_empty(client, monkeypatch):
    """A discovery step that ran and succeeded but genuinely found nothing
    (empty pool) must refuse the same as a tied or below-floor pool —
    there's no candidate to even score. Distinct from
    test_honest_failure_message_when_neither_tier_resolves (candidates
    exist but none match this description) and from the tied-pool case
    above (candidates exist and match equally) — this is the third,
    simplest refusal path: nothing was ever discovered at all."""
    tenant_id, user_id = await _register(client, "resolveemptypool")
    task_id, step_id = await _seed_task_with_discovery(
        tenant_id, user_id,
        discovery_raw_result={"pipelines": [], "count": 0},
        discovery_tool_name="list_pipelines",
        step_tool_name="get_pipeline_run_history",
        step_tool_args={"pipeline_id": "sales_pipeline"},
        step_description="Get the run history of the sales pipeline to diagnose why it is lagging.",
    )

    async def _always_not_found(tenant_id, tool_name, tool_args, **kwargs):
        return {"error": "Pipeline not found"}

    async def _cant_improve(tenant_id, user_id, description, tool_name, tool_args, error_message, prior_results=None, task_id=None):
        return tool_args  # Tier 2 also has nothing to go on

    monkeypatch.setattr(executor_module, "_call_tool", _always_not_found)
    monkeypatch.setattr(executor_module, "_adapt_step_args", _cant_improve)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "step_failed"

    step = await _fresh_step(step_id)
    assert step.status == TaskStepStatus.FAILED
    assert "no match" in step.error_message
