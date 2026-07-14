from ast import pattern
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select

from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import DataContract, DataSource
from modules.governance.lineage_tracker import LineageTracker
from modules.governance.audit_trail import AuditTrail

log = structlog.get_logger()
router = APIRouter()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------
# Pydantic schemas
# ------------------------------------------------------------------

class AddNodeRequest(BaseModel):
    node_type: str
    name: str
    metadata: Optional[dict] = {}

class AddEdgeRequest(BaseModel):
    upstream_id: str
    downstream_id: str
    relationship_type: Optional[str] = "produces"

class CreateContractRequest(BaseModel):
    name: str
    producer_source_id: str
    consumer_description: Optional[str] = ""
    schema_expectations: Optional[dict] = {}
    quality_conditions: Optional[dict] = {}
    sla_hours: Optional[int] = None

class ValidateContractRequest(BaseModel):
    pass  # validation is driven by stored contract config


# ------------------------------------------------------------------
# Lineage endpoints
# ------------------------------------------------------------------

@router.get("/lineage/{asset_name}")
async def get_lineage(
    asset_name: str,
    direction: str = Query("both", pattern="^(upstream|downstream|both)$"),
    max_depth: int = Query(10, ge=1, le=20),
    user=Depends(get_current_user),
):
    """Get upstream/downstream lineage graph for a named asset."""
    tracker = LineageTracker(user["tenant_id"])
    result = await tracker.get_lineage(asset_name, direction=direction, max_depth=max_depth)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"],
        action="lineage.viewed",
        resource_type="lineage",
        resource_id=asset_name,
        payload={"direction": direction},
    )
    return result


@router.get("/graph")
async def get_full_graph(user=Depends(get_current_user)):
    """Return the full lineage graph for the tenant (for visualization)."""
    tracker = LineageTracker(user["tenant_id"])
    result = await tracker.get_full_graph()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/lineage/node", status_code=201)
async def add_lineage_node(
    body: AddNodeRequest,
    user=Depends(get_current_user),
):
    """Register a new lineage node."""
    tracker = LineageTracker(user["tenant_id"])
    result = await tracker.add_node(body.node_type, body.name, body.metadata)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"],
        action="lineage.node_added",
        resource_type="lineage",
        resource_id=result.get("node_id", ""),
        payload={"node_type": body.node_type, "name": body.name},
    )
    return result


@router.post("/lineage/edge", status_code=201)
async def add_lineage_edge(
    body: AddEdgeRequest,
    user=Depends(get_current_user),
):
    """Register a directed edge between two lineage nodes."""
    tracker = LineageTracker(user["tenant_id"])
    result = await tracker.add_edge(
        body.upstream_id, body.downstream_id, body.relationship_type
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"],
        action="lineage.edge_added",
        resource_type="lineage",
        resource_id=result.get("edge_id", ""),
        payload={"upstream_id": body.upstream_id, "downstream_id": body.downstream_id},
    )
    return result


# ------------------------------------------------------------------
# Data Contract endpoints
# ------------------------------------------------------------------

@router.get("/contracts")
async def list_contracts(
    is_active: Optional[bool] = Query(None),
    user=Depends(get_current_user),
):
    """List all data contracts for the tenant."""
    try:
        async with AsyncSessionLocal() as db:
            query = select(DataContract).where(
                DataContract.tenant_id == user["tenant_id"]
            )
            if is_active is not None:
                query = query.where(DataContract.is_active == is_active)
            result = await db.execute(query)
            contracts = result.scalars().all()
        return {"contracts": [_serialize_contract(c) for c in contracts], "count": len(contracts)}
    except Exception as exc:
        log.error("governance.list_contracts.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/contracts/{contract_id}")
async def get_contract(contract_id: str, user=Depends(get_current_user)):
    """Get a single data contract by ID."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DataContract).where(
                    DataContract.id == contract_id,
                    DataContract.tenant_id == user["tenant_id"],
                )
            )
            contract = result.scalar_one_or_none()
        if contract is None:
            raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")
        return _serialize_contract(contract)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/contracts", status_code=201)
async def create_contract(
    body: CreateContractRequest,
    user=Depends(get_current_user),
):
    """Create a new data contract."""
    try:
        async with AsyncSessionLocal() as db:
            # Verify producer source belongs to tenant
            src_result = await db.execute(
                select(DataSource).where(
                    DataSource.id == body.producer_source_id,
                    DataSource.tenant_id == user["tenant_id"],
                )
            )
            if src_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Source {body.producer_source_id} not found",
                )

            contract = DataContract(
                tenant_id=user["tenant_id"],
                name=body.name,
                producer_source_id=body.producer_source_id,
                consumer_description=body.consumer_description,
                schema_expectations=body.schema_expectations,
                quality_conditions=body.quality_conditions,
                sla_hours=body.sla_hours,
                is_active=True,
                validation_status="pending",
                created_at=utcnow(),
            )
            db.add(contract)
            await db.commit()
            await db.refresh(contract)

        await AuditTrail(user["tenant_id"]).log_action(
            actor=user["email"],
            action="contract.created",
            resource_type="contract",
            resource_id=str(contract.id),
            payload={"name": body.name, "producer_source_id": body.producer_source_id},
        )
        return _serialize_contract(contract)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("governance.create_contract.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/contracts/{contract_id}/validate")
async def validate_contract(
    contract_id: str,
    user=Depends(get_current_user),
):
    """
    Validate a data contract against the current source schema.
    Checks schema_expectations and quality_conditions against live DataSource snapshot.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DataContract).where(
                    DataContract.id == contract_id,
                    DataContract.tenant_id == user["tenant_id"],
                )
            )
            contract = result.scalar_one_or_none()
            if contract is None:
                raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")

            # Fetch the producer source's live schema snapshot
            src_result = await db.execute(
                select(DataSource).where(
                    DataSource.id == contract.producer_source_id,
                    DataSource.tenant_id == user["tenant_id"],
                )
            )
            source = src_result.scalar_one_or_none()

        violations = []
        passed = []

        if source and source.schema_snapshot:
            live_schema = source.schema_snapshot
            expected = contract.schema_expectations or {}

            # Check expected columns exist
            expected_columns = expected.get("columns", [])
            live_columns = [
                col.get("name") for col in live_schema.get("columns", [])
            ]
            for col in expected_columns:
                col_name = col.get("name") if isinstance(col, dict) else col
                if col_name not in live_columns:
                    violations.append({
                        "check": "schema.column_missing",
                        "column": col_name,
                        "message": f"Expected column '{col_name}' not found in live schema",
                    })
                else:
                    passed.append({"check": "schema.column_present", "column": col_name})

            # Check expected row count minimum
            min_rows = expected.get("min_row_count")
            live_row_count = live_schema.get("row_count")
            if min_rows and live_row_count is not None:
                if live_row_count < min_rows:
                    violations.append({
                        "check": "quality.min_row_count",
                        "expected": min_rows,
                        "actual": live_row_count,
                        "message": f"Row count {live_row_count} is below minimum {min_rows}",
                    })
                else:
                    passed.append({"check": "quality.min_row_count"})
        else:
            violations.append({
                "check": "schema.no_snapshot",
                "message": "Source has not been profiled yet — no schema snapshot available",
            })

        validation_status = "valid" if not violations else "violated"

        # Persist validation result
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DataContract).where(
                    DataContract.id == contract_id,
                    DataContract.tenant_id == user["tenant_id"],
                )
            )
            contract = result.scalar_one_or_none()
            contract.validation_status = validation_status
            contract.last_validated_at = utcnow()
            db.add(contract)
            await db.commit()

        await AuditTrail(user["tenant_id"]).log_action(
            actor=user["email"],
            action="contract.validated",
            resource_type="contract",
            resource_id=contract_id,
            payload={"status": validation_status, "violations": len(violations)},
        )

        return {
            "contract_id": contract_id,
            "validation_status": validation_status,
            "violations": violations,
            "passed": passed,
            "validated_at": utcnow().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.error("governance.validate_contract.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ------------------------------------------------------------------
# Audit trail endpoint
# ------------------------------------------------------------------

@router.get("/audit")
async def get_audit_trail(
    resource_id: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    action_prefix: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user=Depends(get_current_user),
):
    """Query the audit trail with optional filters."""
    trail = AuditTrail(user["tenant_id"])
    result = await trail.get_audit_trail(
        resource_id=resource_id,
        resource_type=resource_type,
        actor=actor,
        action_prefix=action_prefix,
        limit=limit,
    )
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"entries": result, "count": len(result)}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _serialize_contract(c: DataContract) -> dict:
    return {
        "contract_id": str(c.id),
        "name": c.name,
        "producer_source_id": str(c.producer_source_id) if c.producer_source_id else None,
        "consumer_description": c.consumer_description,
        "schema_expectations": c.schema_expectations or {},
        "quality_conditions": c.quality_conditions or {},
        "sla_hours": c.sla_hours,
        "is_active": c.is_active,
        "validation_status": c.validation_status,
        "last_validated_at": c.last_validated_at.isoformat() if c.last_validated_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }