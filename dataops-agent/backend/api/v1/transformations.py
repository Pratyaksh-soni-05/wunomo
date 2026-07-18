import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc

from .auth import get_current_user, require_role
from services.rbac import Role
from database import AsyncSessionLocal
from models.all_models import TransformRun
from modules.transformation.transform_generator import TransformGenerator
from modules.transformation.sql_runner import SqlRunner
from modules.transformation.python_runner import PythonRunner
from modules.transformation.transform_run_log import log_transform_run
from modules.governance.audit_trail import AuditTrail

log = structlog.get_logger()
router = APIRouter()


# ------------------------------------------------------------------
# Pydantic schemas
# ------------------------------------------------------------------

class GenerateRequest(BaseModel):
    request: str
    language: Optional[str] = "auto"   # "sql" | "pandas" | "auto"
    source_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    extra_context: Optional[str] = None

class RunSqlRequest(BaseModel):
    source_id: str
    sql: str
    params: Optional[dict] = {}
    row_limit: Optional[int] = 10_000

class RunPandasRequest(BaseModel):
    source_id: str
    code: str
    row_limit: Optional[int] = 50_000

class ExplainRequest(BaseModel):
    code: str
    language: Optional[str] = "sql"


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/generate")
async def generate_transform(
    body: GenerateRequest,
    user=Depends(get_current_user),
):
    """
    Generates a SQL or Pandas transformation from a natural language request.
    Language is auto-detected from source type if not specified.
    """
    gen = TransformGenerator(user["tenant_id"])
    result = await gen.generate(
        request=body.request,
        language=body.language or "auto",
        source_id=body.source_id,
        pipeline_id=body.pipeline_id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"],
        action="transform.generated",
        resource_type="source",
        resource_id=body.source_id or body.pipeline_id or "none",
        payload={"language": result.get("type"), "warnings": result.get("warnings")},
    )
    return result


@router.post("/generate/sql")
async def generate_sql(body: GenerateRequest, user=Depends(get_current_user)):
    """Generate SQL transformation explicitly."""
    gen = TransformGenerator(user["tenant_id"])
    result = await gen.generate_sql(
        request=body.request,
        source_id=body.source_id,
        pipeline_id=body.pipeline_id,
        extra_context=body.extra_context,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/generate/pandas")
async def generate_pandas(body: GenerateRequest, user=Depends(get_current_user)):
    """Generate Pandas transformation explicitly."""
    gen = TransformGenerator(user["tenant_id"])
    result = await gen.generate_pandas(
        request=body.request,
        source_id=body.source_id,
        pipeline_id=body.pipeline_id,
        extra_context=body.extra_context,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/run/sql")
async def run_sql(body: RunSqlRequest, user=Depends(require_role(Role.OWNER, Role.ADMIN, Role.DATA_ENGINEER, Role.DATA_ANALYST))):
    """
    Executes SQL against a registered DataSource.
    Safety checks: SELECT-only, keyword blocklist, LIMIT injection.
    """
    runner = SqlRunner(user["tenant_id"])
    result = await runner.run_on_source(
        source_id=body.source_id,
        sql=body.sql,
        params=body.params or {},
        row_limit=body.row_limit or 10_000,
        actor=user["email"],
    )
    await log_transform_run(
        tenant_id=user["tenant_id"], user_id=user["sub"], session_id=None,
        source_id=body.source_id, transform_type="sql", origin="manual",
        code=body.sql, result=result,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/run/sql/dry-run")
async def dry_run_sql(body: RunSqlRequest, user=Depends(get_current_user)):
    """Returns EXPLAIN plan without executing the query."""
    runner = SqlRunner(user["tenant_id"])
    result = await runner.dry_run(source_id=body.source_id, sql=body.sql)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/run/pandas")
async def run_pandas(body: RunPandasRequest, user=Depends(require_role(Role.OWNER, Role.ADMIN, Role.DATA_ENGINEER, Role.DATA_ANALYST))):
    """
    Executes Pandas transformation code in a sandboxed environment.
    Input: df (loaded from source). Output must be assigned to result_df.
    """
    runner = PythonRunner(user["tenant_id"])
    result = await runner.run_on_source(
        source_id=body.source_id,
        code=body.code,
        row_limit=body.row_limit or 50_000,
        actor=user["email"],
    )
    await log_transform_run(
        tenant_id=user["tenant_id"], user_id=user["sub"], session_id=None,
        source_id=body.source_id, transform_type="pandas", origin="manual",
        code=body.code, result=result,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/preview/pandas")
async def preview_pandas(body: RunPandasRequest, user=Depends(get_current_user)):
    """Runs a Pandas transformation and returns only the first 100 rows. No audit trail."""
    runner = PythonRunner(user["tenant_id"])
    result = await runner.preview(source_id=body.source_id, code=body.code)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/explain")
async def explain_code(body: ExplainRequest, user=Depends(get_current_user)):
    """Uses the LLM to explain what a SQL or Pandas code block does in plain English."""
    gen = TransformGenerator(user["tenant_id"])
    result = await gen.explain_code(body.code, language=body.language or "sql")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/runs")
async def list_transform_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Lists real transform executions for the Transforms History tab —
    newest-first, tenant-scoped. Phase 13 built TransformRun persistence but
    no read endpoint; this is that missing read side (Phase 14 addendum)."""
    async with AsyncSessionLocal() as db:
        query = select(TransformRun).where(TransformRun.tenant_id == user["tenant_id"])
        if source_id:
            query = query.where(TransformRun.source_id == source_id)
        query = query.order_by(desc(TransformRun.created_at)).offset(offset).limit(limit)
        result = await db.execute(query)
        runs = result.scalars().all()

    return {
        "runs": [
            {
                "id": r.id,
                "source_id": r.source_id,
                "transform_type": r.transform_type,
                "origin": r.origin,
                "code": r.code,
                "status": r.status,
                "row_count": r.row_count,
                "duration_ms": r.duration_ms,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ],
        "count": len(runs),
    }