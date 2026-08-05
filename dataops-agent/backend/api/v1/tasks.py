"""Item 6 (long-running AXIOM tasks) -- stage 2, the planning phase. See
docs/PRODUCT_AUDIT.md section 1.9 for the full design.

Task creation/viewing/cancelling of one's own task needs no capability
gate beyond authentication -- the same access chat already has. Nothing
executes at this stage; enforcement of what a task's steps are actually
allowed to *do* is a stage-3 concern (per-step, at execution time, per
amendment 3 -- role is re-read fresh right before each step runs, never
cached here).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import AsyncSessionLocal
from models.all_models import Task, TaskShape, TaskStatus, TaskStep, TaskStepSource, TaskStepStatus
from modules.orchestration.task_planner import PlanGenerationError, PlanValidationError, generate_plan

from .auth import enforce_quota

router = APIRouter()

# Fixed default for stage 2 -- real step/wall-clock/credit budgeting is a
# stage-6 (termination) concern; this just needs a non-null value the
# schema requires today.
DEFAULT_STEP_BUDGET_MAX = 20


class CreateTaskRequest(BaseModel):
    goal: str
    task_shape: str


def _serialize_step(step: TaskStep) -> dict:
    return {
        "id": step.id,
        "step_index": step.step_index,
        "description": step.description,
        "source": step.source.value,
        "tool_name": step.tool_name,
        "tool_args": step.tool_args,
        "depends_on_step_index": step.depends_on_step_index,
        "status": step.status.value,
    }


def _serialize_task(task: Task, steps: list[TaskStep]) -> dict:
    return {
        "id": task.id,
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "goal": task.goal,
        "task_shape": task.task_shape.value,
        "status": task.status.value,
        "plan_approved_by": task.plan_approved_by,
        "plan_approved_at": task.plan_approved_at.isoformat() if task.plan_approved_at else None,
        "plan_edited": bool(task.plan_edited),
        "step_budget_max": task.step_budget_max,
        "step_budget_used": task.step_budget_used,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "steps": [_serialize_step(s) for s in sorted(steps, key=lambda s: s.step_index)],
    }


@router.post("/")
async def create_task(body: CreateTaskRequest, current_user: dict = Depends(enforce_quota("ai_credits"))):
    """Generates and persists a real plan. Quota is checked (via the
    dependency above) before the LLM call ever runs, same order as chat.
    On any generation/validation failure, nothing is persisted -- a clean
    error, not a Task row stuck in draft_plan with no steps and no
    explanation."""
    try:
        task_shape = TaskShape(body.task_shape)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task_shape '{body.task_shape}'. Valid: {[s.value for s in TaskShape]}",
        )

    if not body.goal or not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal must not be empty.")

    tenant_id = current_user["tenant_id"]
    user_id = current_user["sub"]

    try:
        steps = await generate_plan(tenant_id, user_id, body.goal, task_shape)
    except (PlanGenerationError, PlanValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not generate a valid plan: {exc}")

    async with AsyncSessionLocal() as db:
        task = Task(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            goal=body.goal,
            task_shape=task_shape,
            status=TaskStatus.DRAFT_PLAN,
            step_budget_max=DEFAULT_STEP_BUDGET_MAX,
        )
        db.add(task)
        await db.flush()

        task_steps = []
        for i, step in enumerate(steps):
            ts = TaskStep(
                id=str(uuid.uuid4()),
                task_id=task.id,
                step_index=i,
                description=step["description"],
                source=TaskStepSource.LLM_PLANNED,
                tool_name=step["tool_name"],
                tool_args=step.get("tool_args") or {},
                depends_on_step_index=step.get("depends_on_step_index"),
                status=TaskStepStatus.PENDING,
            )
            db.add(ts)
            task_steps.append(ts)

        await db.commit()
        await db.refresh(task)
        for ts in task_steps:
            await db.refresh(ts)

    return _serialize_task(task, task_steps)
