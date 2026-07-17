from langchain_core.tools import tool
from typing import Optional
from agent.tools._utils import cap_tool_result


@tool
async def generate_sql_transform(tenant_id: str, transformation_goal: str,
    source_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> dict:
    """Generate a SQL transformation from a natural-language goal. Returns SQL for
    review before execution. Provide either source_id or pipeline_id so the real
    source schema can be used to ground the generated SQL."""
    from modules.transformation.transform_generator import TransformGenerator
    return await TransformGenerator(tenant_id).generate_sql(
        request=transformation_goal, source_id=source_id, pipeline_id=pipeline_id)


@tool
async def execute_sql_transform(tenant_id: str, sql: str, source_id: str, dry_run: bool = True) -> dict:
    """Execute SQL transformation against a data source. dry_run=True explains
    without running (via EXPLAIN); dry_run=False actually runs it (SELECT/WITH only)."""
    from modules.transformation.sql_runner import SqlRunner
    runner = SqlRunner(tenant_id)
    if dry_run:
        return cap_tool_result(await runner.dry_run(source_id, sql))
    return cap_tool_result(await runner.run_on_source(source_id, sql))


@tool
async def run_python_transform(tenant_id: str, source_id: str, script: str) -> dict:
    """Execute a sandboxed pandas transformation script against a data source.
    Input DataFrame is `df`, output must be assigned to `result_df`."""
    from modules.transformation.python_runner import PythonRunner
    return cap_tool_result(await PythonRunner(tenant_id).run_on_source(source_id, script))


@tool
async def standardize_dataset(tenant_id: str, source_id: str, table: str, rules: dict) -> dict:
    """Standardize a dataset: rename columns, cast types, fill nulls, deduplicate."""
    return {
        "error": "Dataset standardization is not implemented yet — there is no real "
                 "standardize path in this system. Use generate_sql_transform or "
                 "run_python_transform to write and run an equivalent transformation "
                 "instead. Do not tell the user this succeeded."
    }


transformation_tools = [generate_sql_transform, execute_sql_transform, run_python_transform, standardize_dataset]
