from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy import select

from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import DataSource

router = APIRouter()


def _normalize_column(col: dict) -> dict:
    """SchemaProfiler's 3 profilers don't all use the same column dict shape
    (Postgres/MySQL use asyncpg/DESCRIBE-derived "column_name"/"data_type"/
    "is_nullable"; the file profiler adds "null_count"/"unique_count" on top
    of the same 3 keys) — normalize to one consistent {name, type, nullable}
    shape for the catalog response, regardless of source type."""
    return {
        "name": col.get("column_name"),
        "type": col.get("data_type"),
        "nullable": col.get("is_nullable") in ("YES", True),
    }


@router.get("/")
async def get_catalog(source_id: Optional[str] = None, user=Depends(get_current_user)):
    """Thin, tenant-scoped aggregation over every DataSource's real
    schema_snapshot — flattens each source's tables (SchemaProfiler nests
    columns/row_count under a table-name key: {"main": {...}} for files,
    {table1: {...}, ...} for Postgres/MySQL) into one list of catalog
    entries. Sources that have never been profiled are included with
    profiled: false rather than hidden, so the Catalog UI can prompt to
    profile them instead of silently omitting them."""
    async with AsyncSessionLocal() as db:
        query = select(DataSource).where(DataSource.tenant_id == user["tenant_id"])
        if source_id:
            query = query.where(DataSource.id == source_id)
        result = await db.execute(query)
        sources = result.scalars().all()

    entries = []
    for source in sources:
        source_type = (
            source.source_type.value
            if hasattr(source.source_type, "value")
            else str(source.source_type)
        )
        snapshot = source.schema_snapshot or {}

        if not snapshot:
            entries.append({
                "source_id": source.id,
                "source_name": source.name,
                "source_type": source_type,
                "table_name": None,
                "row_count": None,
                "column_count": 0,
                "columns": [],
                "profiled": False,
                "last_profiled_at": None,
                "tags": source.tags or [],
                "owner": source.owner,
            })
            continue

        for table_name, table_info in snapshot.items():
            columns = [_normalize_column(c) for c in table_info.get("columns", [])]
            entries.append({
                "source_id": source.id,
                "source_name": source.name,
                "source_type": source_type,
                "table_name": table_name,
                "row_count": table_info.get("row_count"),
                "column_count": len(columns),
                "columns": columns,
                "profiled": True,
                "last_profiled_at": str(source.last_profiled_at) if source.last_profiled_at else None,
                "tags": source.tags or [],
                "owner": source.owner,
            })

    return {"entries": entries, "count": len(entries)}
