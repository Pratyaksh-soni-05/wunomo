from modules.orchestration.dag_manager import DAGManager
from models.all_models import RunStatus


class RunTracker:
    """Thin wrapper — DAGManager handles all run state.
       Kept as a class for agent tool compatibility."""
    def __init__(self, tenant_id: str):
        self.dag = DAGManager(tenant_id)

    async def update_status(self, run_id: str, status: str, **kwargs) -> dict:
        return await self.dag.update_run_status(
            run_id, RunStatus(status), **kwargs
        )

    async def get_history(self, pipeline_id: str, limit: int = 20) -> dict:
        return await self.dag.get_run_history(pipeline_id, limit)