"""Wunomo Projects Phase 1, part one: intersection permission enforcement,
task-execution half (enforcement points 2 and 3 of 4 - _caller_still_
authorized's scope re-check, and the scope check immediately before
_call_tool()). Mirrors test_task_executor.py's mocking conventions
(monkeypatch _call_tool, no real tools/LLM) and test_agent_scope_gate.py's
required failure shapes:

  (a) High-role caller, narrow-scope agent: denied by SCOPE, not role.
  (b) Low-role caller, broad-scope agent: still denied by ROLE.
  (c) Both re-run through execute_next_step()'s per-step path after the
      task was already queued -- precedent is
      test_deactivated_user_blocks_the_next_step.

A fourth test isolates why there are TWO scope checks, not one:
_caller_still_authorized's own scope check only ever sees whatever is
already in step.tool_args, which can still be an unresolved placeholder
on a step's first pass -- the unconditional backstop that always sees a
fully-resolved id is the separate check immediately before _call_tool()
in the attempt loop.
"""
import uuid

import pytest
from sqlalchemy import delete, select

import modules.orchestration.task_executor as executor_module
from database import AsyncSessionLocal
from modules.orchestration.task_executor import execute_next_step
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, AgentSource, DataSource,
    OperationMode, PersonalityMode, SourceType, Task, TaskShape, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus, User,
)


async def _register(client, prefix="taskscope"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234", "full_name": "Task Scope Test",
        "tenant_name": f"Task Scope Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["tenant_id"], body["user_id"]


async def _make_source(tenant_id: str, name="Source") -> str:
    async with AsyncSessionLocal() as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            source_type=SourceType.POSTGRES, connection_config={},
        )
        db.add(source)
        await db.commit()
        return source.id


async def _make_agent(tenant_id: str, name="Nova", scoped_source_ids=None) -> str:
    async with AsyncSessionLocal() as db:
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
            employee_type=AgentEmployeeType.DATAOPS, personality=PersonalityMode.ENGINEER,
            operation_mode=OperationMode.ASSISTED, model="gemini-3.5-flash",
            status=AgentInstanceStatus.ACTIVE,
        )
        db.add(agent)
        await db.flush()
        for source_id in (scoped_source_ids or []):
            db.add(AgentSource(id=str(uuid.uuid4()), agent_id=agent.id, source_id=source_id))
        await db.commit()
        return agent.id


async def _revoke_scope(agent_id: str, source_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AgentSource).where(AgentSource.agent_id == agent_id, AgentSource.source_id == source_id))
        await db.commit()


async def _set_role(user_id: str, role: str) -> None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = role
        await db.commit()


async def _seed_task(tenant_id: str, user_id: str, agent_id: str, tool_name: str, tool_args: dict) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.QUEUED, step_budget_max=20,
        )
        db.add(task)
        await db.flush()
        step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="do the thing", source=TaskStepSource.LLM_PLANNED,
            tool_name=tool_name, tool_args=tool_args, status=TaskStepStatus.PENDING,
        )
        db.add(step)
        await db.commit()
        return task.id, step.id


async def _fresh(task_id, step_id):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        step = r.scalar_one()
        return task, step


# ---------------------------------------------------------------------------
# (a) High-role caller, narrow-scope agent -> denied by SCOPE, not role.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_owner_with_narrow_scope_agent_denied_by_scope_via_task_step(client, monkeypatch):
    tenant_id, user_id = await _register(client, "taskscopeA")
    await _set_role(user_id, "owner")
    source_a = await _make_source(tenant_id, "Source A")
    source_b = await _make_source(tenant_id, "Source B")
    agent_id = await _make_agent(tenant_id, name="Nova", scoped_source_ids=[source_a])

    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_b})

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run when the scope check fails")
    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    assert "Nova" in outcome["reason"]
    assert "Source B" in outcome["reason"]
    assert "role" not in outcome["reason"].lower()

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


# ---------------------------------------------------------------------------
# (b) Low-role caller, broad-scope agent -> still denied by ROLE.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b_viewer_with_broad_scope_agent_still_denied_by_role_via_task_step(client, monkeypatch):
    tenant_id, user_id = await _register(client, "taskscopeB")
    await _set_role(user_id, "viewer")
    source_a = await _make_source(tenant_id, "Source A")
    agent_id = await _make_agent(tenant_id, name="BroadBot", scoped_source_ids=[source_a])

    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_a})

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run when the role check fails")
    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    assert "role" in outcome["reason"].lower()

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


# ---------------------------------------------------------------------------
# (c) Re-run through execute_next_step()'s per-step path after the task was
# already queued -- precedent: test_deactivated_user_blocks_the_next_step.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c_agent_rescoped_after_queueing_blocks_the_next_step(client, monkeypatch):
    """An agent can be re-scoped mid-task exactly as a user can be
    demoted -- narrowing scope AFTER a task is already queued must still
    block the very next execute_next_step() call, not just a fresh task
    created after the narrowing."""
    tenant_id, user_id = await _register(client, "taskscopeC1")
    await _set_role(user_id, "owner")
    source_a = await _make_source(tenant_id, "Source A")
    agent_id = await _make_agent(tenant_id, name="Nova", scoped_source_ids=[source_a])

    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_a})

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run once scope is revoked")
    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    # Revoke AFTER the task was queued -- the task/step rows above are
    # already committed with source_a legitimately in scope at that time.
    await _revoke_scope(agent_id, source_a)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    assert "Nova" in outcome["reason"]
    assert "Source A" in outcome["reason"]

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


@pytest.mark.asyncio
async def test_c_role_demoted_after_queueing_still_blocks_with_a_broad_scope_agent(client, monkeypatch):
    """The role half of the same property, with a real agent/scope
    present (not agent_id=None) -- proves role demotion still wins even
    when the calling agent is fully in scope."""
    tenant_id, user_id = await _register(client, "taskscopeC2")
    await _set_role(user_id, "owner")
    source_a = await _make_source(tenant_id, "Source A")
    agent_id = await _make_agent(tenant_id, name="BroadBot", scoped_source_ids=[source_a])

    task_id, step_id = await _seed_task(tenant_id, user_id, agent_id, "sync_source", {"source_id": source_a})

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run once the user is demoted")
    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    await _set_role(user_id, "viewer")

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    assert "role" in outcome["reason"].lower()

    task, step = await _fresh(task_id, step_id)
    assert step.status == TaskStepStatus.FAILED
    assert task.status == TaskStatus.PAUSED_FAILED_STEP


# ---------------------------------------------------------------------------
# Why two checks: _caller_still_authorized only ever sees step.tool_args as
# it stands at that moment -- an unresolved placeholder there is genuinely
# nothing to check. The pre-_call_tool() check in the attempt loop is the
# real, unconditional backstop, since current_args is always fully
# resolved by the time it runs.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scope_check_still_fires_after_tier1_resolves_an_out_of_scope_id(client, monkeypatch):
    """A step whose arg starts as a natural-language placeholder (not a
    real id) passes _caller_still_authorized's own scope check with
    nothing to deny -- there's no real id yet. Once Tier 1 resolves it
    (from an earlier, already-succeeded discovery step) to a REAL id
    outside the agent's scope, the pre-_call_tool() check must still
    catch it before the tool ever runs. Uses a LOW-risk tool
    (get_pipeline_run_history) deliberately -- a medium/high-risk tool
    would divert into the approval-gate branch instead of the attempt
    loop this test is exercising."""
    from models.all_models import Pipeline

    tenant_id, user_id = await _register(client, "taskscopeD")
    await _set_role(user_id, "owner")
    source_a = await _make_source(tenant_id, "Warehouse")
    source_b = await _make_source(tenant_id, "Marketing Analytics")
    agent_id = await _make_agent(tenant_id, name="Nova", scoped_source_ids=[source_a])

    async with AsyncSessionLocal() as db:
        pipeline_on_b = Pipeline(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Marketing Analytics Pipeline", source_id=source_b)
        db.add(pipeline_on_b)
        await db.flush()

        task = Task(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
            goal="test", task_shape=TaskShape.DIAGNOSE_PIPELINE_FAILURE,
            status=TaskStatus.QUEUED, step_budget_max=20, started_at=None,
        )
        db.add(task)
        await db.flush()
        discovery_step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=0,
            description="list pipelines", source=TaskStepSource.LLM_PLANNED,
            tool_name="list_pipelines", tool_args={}, status=TaskStepStatus.SUCCEEDED,
            raw_result={"pipelines": [{"id": pipeline_on_b.id, "name": "Marketing Analytics Pipeline"}]},
        )
        target_step = TaskStep(
            id=str(uuid.uuid4()), task_id=task.id, step_index=1,
            description="get run history for the marketing analytics pipeline", source=TaskStepSource.LLM_PLANNED,
            tool_name="get_pipeline_run_history", tool_args={"pipeline_id": "the marketing analytics pipeline"},
            depends_on_step_index=0, status=TaskStepStatus.PENDING,
        )
        db.add_all([discovery_step, target_step])
        await db.commit()
        task_id, step_id = task.id, target_step.id

    async def _fail_if_called(*a, **k):
        raise AssertionError("_call_tool must never run once Tier 1 resolves to an out-of-scope source")
    monkeypatch.setattr(executor_module, "_call_tool", _fail_if_called)

    outcome = await execute_next_step(task_id)
    assert outcome["outcome"] == "blocked_permission"
    assert "Nova" in outcome["reason"]
    assert "Marketing Analytics" in outcome["reason"]

    task, step = await _fresh(task_id, step_id)
    # Tier 1 really did resolve the placeholder to the real, out-of-scope id
    # -- proving the denial happened AFTER resolution, at the real backstop,
    # not by coincidentally refusing an unresolved placeholder.
    assert step.tool_args.get("pipeline_id") == pipeline_on_b.id
    assert step.status == TaskStepStatus.FAILED
