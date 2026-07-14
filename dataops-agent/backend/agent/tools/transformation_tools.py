from langchain_core.tools import tool
from typing import Optional, List


@tool
async def generate_sql_transform(tenant_id: str, source_tables: List[str], transformation_goal: str, output_table_name: str) -> dict:
    """Generate SQL transformation from natural language. Returns SQL for review before execution."""
    from modules.transformation.transform_generator import TransformGenerator
    return await TransformGenerator(tenant_id).generate_sql(source_tables, transformation_goal, output_table_name)


@tool
async def execute_sql_transform(tenant_id: str, sql: str, source_id: str, dry_run: bool = True) -> dict:
    """Execute SQL transformation. dry_run=True explains without running."""
    from modules.transformation.sql_runner import SQLRunner
    return await SQLRunner(tenant_id, source_id).execute(sql, dry_run=dry_run)


@tool
async def run_python_transform(tenant_id: str, pipeline_id: str, script: str, input_data: Optional[dict] = None) -> dict:
    """Execute a sandboxed pandas transformation script on a dataset."""
    from modules.transformation.python_runner import PythonRunner
    return await PythonRunner(tenant_id, pipeline_id).run(script, input_data)


@tool
async def standardize_dataset(tenant_id: str, source_id: str, table: str, rules: dict) -> dict:
    """Standardize a dataset: rename columns, cast types, fill nulls, deduplicate."""
    from modules.transformation.transform_generator import TransformGenerator
    return await TransformGenerator(tenant_id).standardize(source_id, table, rules)


transformation_tools = [generate_sql_transform, execute_sql_transform, run_python_transform, standardize_dataset]