from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from croniter import croniter
from .auth import get_current_user, require_permission, enforce_quota
from modules.orchestration.dag_manager import DAGManager

router = APIRouter()


def _validate_cron_or_400(cron: Optional[str]) -> None:
    """Save-time validation, checked before schedule_cron ever reaches the
    DB - without this, a malformed cron silently persists and only ever
    surfaces (if at all) as a log line in check_scheduled_pipelines(), never
    to the user who typed it."""
    if cron is None:
        return
    if not croniter.is_valid(cron.strip()):
        raise HTTPException(
            status_code=400,
            detail=f"'{cron}' is not a valid cron expression (expected 5 fields: minute hour day-of-month month day-of-week).",
        )


class PipelineCreate(BaseModel):
    name: str
    source_id: Optional[str] = None
    description: Optional[str] = None
    schedule_cron: Optional[str] = None
    pipeline_config: Optional[dict] = {}
    sla_minutes: Optional[int] = None
    retry_policy: Optional[dict] = None
    tags: Optional[list] = []


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule_cron: Optional[str] = None
    pipeline_config: Optional[dict] = None
    sla_minutes: Optional[int] = None
    retry_policy: Optional[dict] = None
    tags: Optional[list] = None
    status: Optional[str] = None


class ScheduleUpdate(BaseModel):
    cron: str


class BackfillRequest(BaseModel):
    start_date: str
    end_date: str


@router.get("/")
async def list_pipelines(user=Depends(get_current_user)):
    return await DAGManager(user["tenant_id"]).list_pipelines()


@router.post("/")
async def create_pipeline(req: PipelineCreate, user=Depends(require_permission("pipelines.create"))):
    _validate_cron_or_400(req.schedule_cron)
    return await DAGManager(user["tenant_id"]).create_pipeline(
        name=req.name, source_id=req.source_id,
        description=req.description, schedule_cron=req.schedule_cron,
        pipeline_config=req.pipeline_config, sla_minutes=req.sla_minutes,
        retry_policy=req.retry_policy, tags=req.tags
    )


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str, user=Depends(get_current_user)):
    result = await DAGManager(user["tenant_id"]).get_pipeline(pipeline_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.put("/{pipeline_id}")
async def update_pipeline(pipeline_id: str, req: PipelineUpdate,
                          user=Depends(require_permission("pipelines.create"))):
    _validate_cron_or_400(req.schedule_cron)
    result = await DAGManager(user["tenant_id"]).update_pipeline(
        pipeline_id, **req.model_dump(exclude_none=True)
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/{pipeline_id}")
async def delete_pipeline(pipeline_id: str, user=Depends(require_permission("pipelines.delete"))):
    from sqlalchemy import select, delete, update
    from database import AsyncSessionLocal
    from models.all_models import Pipeline, PipelineRun, QualityRule, Incident
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Pipeline).where(
            Pipeline.id == pipeline_id,
            Pipeline.tenant_id == user["tenant_id"]
        ))
        p = r.scalars().first()
        if not p:
            raise HTTPException(status_code=404, detail="Pipeline not found")

        # Pipeline.id has no ON DELETE CASCADE on any of these FKs (unlike the
        # CI/CD tables, which do), so a bare db.delete(p) 500s the moment the
        # pipeline has ever been run — the normal case, not an edge case.
        # Incidents are historical audit records, not owned by the pipeline,
        # so they're preserved with their pipeline/run references cleared
        # rather than deleted; runs and quality rules are pipeline-scoped
        # operational data and are deleted along with it. Incident.run_id
        # must be cleared before PipelineRun rows are deleted, since it also
        # FKs into pipeline_runs.id.
        await db.execute(
            update(Incident).where(Incident.pipeline_id == pipeline_id)
            .values(pipeline_id=None, run_id=None)
        )
        await db.execute(delete(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id))
        await db.execute(delete(QualityRule).where(QualityRule.pipeline_id == pipeline_id))
        await db.delete(p)
        await db.commit()
    return {"message": "Pipeline deleted", "id": pipeline_id}


@router.post("/{pipeline_id}/trigger")
async def trigger_run(
    pipeline_id: str,
    _perm=Depends(require_permission("pipelines.operate")),
    user=Depends(enforce_quota("pipeline_runs")),
):
    result = await DAGManager(user["tenant_id"]).trigger_run(
        pipeline_id, triggered_by=user["sub"]
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{pipeline_id}/pause")
async def pause_pipeline(pipeline_id: str, user=Depends(require_permission("pipelines.operate"))):
    result = await DAGManager(user["tenant_id"]).pause_pipeline(pipeline_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{pipeline_id}/activate")
async def activate_pipeline(pipeline_id: str, user=Depends(require_permission("pipelines.operate"))):
    result = await DAGManager(user["tenant_id"]).activate_pipeline(pipeline_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.put("/{pipeline_id}/schedule")
async def set_schedule(pipeline_id: str, req: ScheduleUpdate,
                       user=Depends(require_permission("pipelines.create"))):
    _validate_cron_or_400(req.cron)
    result = await DAGManager(user["tenant_id"]).set_schedule(pipeline_id, req.cron)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{pipeline_id}/runs")
async def get_run_history(pipeline_id: str, limit: int = 20,
                          user=Depends(get_current_user)):
    result = await DAGManager(user["tenant_id"]).get_run_history(pipeline_id, limit)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{pipeline_id}/backfill")
async def backfill(pipeline_id: str, req: BackfillRequest,
                   user=Depends(require_permission("pipelines.operate"))):
    result = await DAGManager(user["tenant_id"]).backfill(
        pipeline_id, req.start_date, req.end_date
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result