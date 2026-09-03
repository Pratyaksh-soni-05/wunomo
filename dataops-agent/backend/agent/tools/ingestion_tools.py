from langchain_core.tools import tool
from typing import Optional
from agent.tools._utils import cap_tool_result

@tool
async def list_data_sources(tenant_id: str) -> dict:
    """List all registered data sources for the tenant."""
    from modules.ingestion.connector_manager import ConnectorManager
    return await ConnectorManager(tenant_id).list_sources()

@tool
async def register_data_source(tenant_id: str, name: str, file_path: str) -> dict:
    """Register an already-uploaded file (from POST /api/v1/uploads/) as a
    data source. source_type and connection_config are derived from the
    real file on disk, never supplied here -- this can only attach an
    existing upload, never invent a live database or API connection.
    Registering a non-file source (postgres, mysql, api_rest, ...) is a
    user action via POST /api/v1/sources/, not available from chat."""
    from modules.ingestion.connector_manager import ConnectorManager
    return await ConnectorManager(tenant_id).register_uploaded_file(name, file_path)

@tool
async def profile_schema(tenant_id: str, source_id: str, agent_id: Optional[str] = None) -> dict:
    """Auto-discover and profile schema: tables, columns, types, nullability, row counts."""
    from modules.ingestion.schema_profiler import SchemaProfiler
    return cap_tool_result(await SchemaProfiler(tenant_id, source_id, agent_id).profile())

@tool
async def ingest_file(tenant_id: str, file_path: str, pipeline_id: Optional[str] = None) -> dict:
    """Parse an already-uploaded file (CSV, Excel, PDF, DOCX, JSON -- from
    POST /api/v1/uploads/) and return its schema + preview. file_path must
    be a real file already sitting under the upload directory, never an
    arbitrary filesystem path -- source_type is derived from its real
    extension, never supplied here."""
    from modules.ingestion.connector_manager import ConnectorManager
    return cap_tool_result(await ConnectorManager(tenant_id).ingest_file(file_path, pipeline_id))

@tool
async def sync_source(tenant_id: str, source_id: str, mode: str = "incremental",
                       agent_id: Optional[str] = None) -> dict:
    """Trigger a sync from a registered data source. mode: full | incremental."""
    from modules.ingestion.connector_manager import ConnectorManager
    return await ConnectorManager(tenant_id).sync(source_id, mode, agent_id)

@tool
async def preview_source_data(tenant_id: str, source_id: str, table: str, limit: int = 50,
                               agent_id: Optional[str] = None) -> dict:
    """Preview sample rows from a source table or file."""
    from modules.ingestion.connector_manager import ConnectorManager
    return cap_tool_result(await ConnectorManager(tenant_id).preview(source_id, table, limit, agent_id))

@tool
async def detect_schema_drift(tenant_id: str, source_id: str, agent_id: Optional[str] = None) -> dict:
    """Compare current schema vs last snapshot. Returns added/removed/type-changed columns."""
    from modules.ingestion.schema_profiler import SchemaProfiler
    return cap_tool_result(await SchemaProfiler(tenant_id, source_id, agent_id).detect_drift())

ingestion_tools = [list_data_sources, register_data_source, profile_schema,
                   ingest_file, sync_source, preview_source_data, detect_schema_drift]
