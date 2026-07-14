from langchain_core.tools import tool

@tool
async def create_pipeline(tenant_id: str, name: str, source_id: str, config: dict) -> dict:
    """Create a new DataOps pipeline with steps, transforms, quality rules, and schedule."""
    from modules.orchestration.dag_manager import DAGManager
    return await DAGManager(tenant_id).create(name, source_id, config)

@tool
async def run_pipeline(tenant_id: str, pipeline_id: str, triggered_by: str = "user") -> dict:
    """Manually trigger a pipeline run."""
    from modules.orchestration.dag_manager import DAGManager
    return await DAGManager(tenant_id).trigger_run(pipeline_id, triggered_by)

@tool
async def pause_pipeline(tenant_id: str, pipeline_id: str) -> dict:
    """Pause a scheduled pipeline."""
    from modules.orchestration.dag_manager import DAGManager
    return await DAGManager(tenant_id).pause(pipeline_id)

@tool
async def get_pipeline_run_history(tenant_id: str, pipeline_id: str, limit: int = 20) -> dict:
    """Get run history: status, duration, quality scores, row counts."""
    from modules.orchestration.run_tracker import RunTracker
    return await RunTracker(tenant_id).get_history(pipeline_id, limit)

@tool
async def backfill_pipeline(tenant_id: str, pipeline_id: str, start_date: str, end_date: str) -> dict:
    """Trigger a backfill run for a date range. Requires approval in ASSISTED mode."""
    from modules.orchestration.dag_manager import DAGManager
    return await DAGManager(tenant_id).backfill(pipeline_id, start_date, end_date)

@tool
async def set_pipeline_schedule(tenant_id: str, pipeline_id: str, cron_expression: str) -> dict:
    """Set or update the cron schedule. e.g. '0 6 * * *' for 6am daily."""
    from modules.orchestration.scheduler import PipelineScheduler
    return await PipelineScheduler(tenant_id).set_schedule(pipeline_id, cron_expression)

orchestration_tools = [create_pipeline, run_pipeline, pause_pipeline,
                        get_pipeline_run_history, backfill_pipeline, set_pipeline_schedule]
