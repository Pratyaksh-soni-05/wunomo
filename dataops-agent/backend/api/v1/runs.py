from fastapi import APIRouter, Depends
from .auth import get_current_user
from modules.orchestration.run_tracker import RunTracker

router = APIRouter()

@router.get("/{pipeline_id}")
async def get_runs(pipeline_id: str, limit: int = 20, user=Depends(get_current_user)):
    return await RunTracker(user["tenant_id"]).get_history(pipeline_id, limit)
