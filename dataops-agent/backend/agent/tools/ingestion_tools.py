from langchain_core.tools import tool
from typing import Optional
from agent.tools._utils import cap_tool_result

@tool
async def list_data_sources(tenant_id: str) -> dict:
    """List all registered data sources for the tenant."""
    from modules.ingestion.connector_manager import ConnectorManager
    return await ConnectorManager(tenant_id).list_sources()

@tool
async def register_data_source(tenant_id: str, name: str, source_type: str, connection_config: dict) -> dict:
    """Register a new data source. source_type: postgres|mysql|csv|excel|json|api_rest|google_sheets|s3|pdf|docx."""
    from modules.ingestion.connector_manager import ConnectorManager
    return await ConnectorManager(tenant_id).register_source(name, source_type, connection_config)

@tool
async def profile_schema(tenant_id: str, source_id: str) -> dict:
    """Auto-discover and profile schema: tables, columns, types, nullability, row counts."""
    from modules.ingestion.schema_profiler import SchemaProfiler
    return cap_tool_result(await SchemaProfiler(tenant_id, source_id).profile())

@tool
async def ingest_file(tenant_id: str, file_path: str, source_type: str, pipeline_id: Optional[str] = None) -> dict:
    """Ingest an uploaded file (CSV, Excel, PDF, DOCX, JSON) and return parsed schema + preview."""
    from modules.ingestion.connector_manager import ConnectorManager
    return cap_tool_result(await ConnectorManager(tenant_id).ingest_file(file_path, source_type, pipeline_id))

@tool
async def sync_source(tenant_id: str, source_id: str, mode: str = "incremental") -> dict:
    """Trigger a sync from a registered data source. mode: full | incremental."""
    from modules.ingestion.connector_manager import ConnectorManager
    return await ConnectorManager(tenant_id).sync(source_id, mode)

@tool
async def preview_source_data(tenant_id: str, source_id: str, table: str, limit: int = 50) -> dict:
    """Preview sample rows from a source table or file."""
    from modules.ingestion.connector_manager import ConnectorManager
    return cap_tool_result(await ConnectorManager(tenant_id).preview(source_id, table, limit))

@tool
async def detect_schema_drift(tenant_id: str, source_id: str) -> dict:
    """Compare current schema vs last snapshot. Returns added/removed/type-changed columns."""
    from modules.ingestion.schema_profiler import SchemaProfiler
    return cap_tool_result(await SchemaProfiler(tenant_id, source_id).detect_drift())

ingestion_tools = [list_data_sources, register_data_source, profile_schema,
                   ingest_file, sync_source, preview_source_data, detect_schema_drift]
