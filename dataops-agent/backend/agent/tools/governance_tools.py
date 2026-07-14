from langchain_core.tools import tool
from typing import Optional, List


@tool
async def get_lineage(tenant_id: str, asset_name: str, direction: str = "both") -> dict:
    """Get data lineage for an asset. direction: upstream|downstream|both."""
    from modules.governance.lineage_tracker import LineageTracker
    return await LineageTracker(tenant_id).get_lineage(asset_name, direction)


@tool
async def get_audit_trail(tenant_id: str, resource_type: Optional[str] = None,
                           resource_id: Optional[str] = None, limit: int = 50) -> dict:
    """Retrieve audit trail for a resource or across the tenant."""
    from modules.governance.audit_trail import AuditTrail
    return await AuditTrail(tenant_id).query(resource_type, resource_id, limit)


@tool
async def create_data_contract(tenant_id: str, name: str, producer_source_id: str,
    schema_expectations: dict, quality_conditions: List[str], sla_hours: int) -> dict:
    """Create a formal data contract between a producer source and consumers."""
    from modules.governance.lineage_tracker import LineageTracker
    return await LineageTracker(tenant_id).create_contract(
        name, producer_source_id, schema_expectations, quality_conditions, sla_hours)


@tool
async def validate_data_contract(tenant_id: str, contract_id: str) -> dict:
    """Validate current data against a contract's schema, quality, and SLA expectations."""
    from modules.governance.lineage_tracker import LineageTracker
    return await LineageTracker(tenant_id).validate_contract(contract_id)


@tool
async def request_approval(tenant_id: str, action_type: str, action_payload: dict,
                             risk_level: str, reason: str) -> dict:
    """Create a human approval request for a risky action. risk_level: low|medium|high."""
    from modules.governance.policy_engine import PolicyEngine
    return await PolicyEngine(tenant_id).request_approval(action_type, action_payload, risk_level, reason)


governance_tools = [get_lineage, get_audit_trail, create_data_contract,
                     validate_data_contract, request_approval]