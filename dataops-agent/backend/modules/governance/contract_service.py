import structlog
from datetime import datetime, timezone
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import DataContract, DataSource
from modules.governance.audit_trail import AuditTrail

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def serialize_contract(c: DataContract) -> dict:
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


async def create_contract(
    tenant_id: str,
    actor: str,
    name: str,
    producer_source_id: str,
    consumer_description: str = "",
    schema_expectations: dict | None = None,
    quality_conditions: dict | None = None,
    sla_hours: int | None = None,
) -> dict:
    """Creates a new DataContract. Shared by the REST endpoint
    (api/v1/governance.py) and the create_data_contract agent tool — same
    logic, same audit trail, no tool calling back into this app's own API.
    Returns {"error": ...} rather than raising, matching this codebase's
    service-layer convention (DAGManager, QualityRuleEngine, etc.)."""
    try:
        async with AsyncSessionLocal() as db:
            src_result = await db.execute(
                select(DataSource).where(
                    DataSource.id == producer_source_id,
                    DataSource.tenant_id == tenant_id,
                )
            )
            if src_result.scalar_one_or_none() is None:
                return {"error": f"Source {producer_source_id} not found"}

            contract = DataContract(
                tenant_id=tenant_id,
                name=name,
                producer_source_id=producer_source_id,
                consumer_description=consumer_description,
                schema_expectations=schema_expectations or {},
                quality_conditions=quality_conditions or {},
                sla_hours=sla_hours,
                is_active=True,
                validation_status="pending",
                created_at=utcnow(),
            )
            db.add(contract)
            await db.commit()
            await db.refresh(contract)

        await AuditTrail(tenant_id).log_action(
            actor=actor,
            action="contract.created",
            resource_type="contract",
            resource_id=str(contract.id),
            payload={"name": name, "producer_source_id": producer_source_id},
        )
        return serialize_contract(contract)
    except Exception as exc:
        log.error("contract_service.create_contract.error", error=str(exc))
        return {"error": str(exc)}


async def validate_contract(tenant_id: str, actor: str, contract_id: str) -> dict:
    """Validates a data contract against the current source schema snapshot.
    Shared by the REST endpoint and the validate_data_contract agent tool."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DataContract).where(
                    DataContract.id == contract_id,
                    DataContract.tenant_id == tenant_id,
                )
            )
            contract = result.scalar_one_or_none()
            if contract is None:
                return {"error": f"Contract {contract_id} not found"}

            src_result = await db.execute(
                select(DataSource).where(
                    DataSource.id == contract.producer_source_id,
                    DataSource.tenant_id == tenant_id,
                )
            )
            source = src_result.scalar_one_or_none()

        violations = []
        passed = []

        if source and source.schema_snapshot:
            live_schema = source.schema_snapshot
            expected = contract.schema_expectations or {}

            expected_columns = expected.get("columns", [])
            live_columns = [col.get("name") for col in live_schema.get("columns", [])]
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

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DataContract).where(
                    DataContract.id == contract_id,
                    DataContract.tenant_id == tenant_id,
                )
            )
            contract = result.scalar_one_or_none()
            contract.validation_status = validation_status
            contract.last_validated_at = utcnow()
            db.add(contract)
            await db.commit()

        await AuditTrail(tenant_id).log_action(
            actor=actor,
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
    except Exception as exc:
        log.error("contract_service.validate_contract.error", error=str(exc))
        return {"error": str(exc)}
