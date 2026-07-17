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
    entries = await AuditTrail(tenant_id).get_audit_trail(
        resource_type=resource_type, resource_id=resource_id, limit=limit)
    if isinstance(entries, dict) and "error" in entries:
        return entries
    return {"entries": entries, "count": len(entries)}


@tool
async def create_data_contract(tenant_id: str, name: str, producer_source_id: str,
    schema_expectations: dict, quality_conditions: List[str], sla_hours: int) -> dict:
    """Create a formal data contract between a producer source and consumers."""
    from modules.governance import contract_service
    return await contract_service.create_contract(
        tenant_id=tenant_id, actor="axiom-agent", name=name,
        producer_source_id=producer_source_id,
        schema_expectations=schema_expectations,
        quality_conditions={"conditions": quality_conditions},
        sla_hours=sla_hours,
    )


@tool
async def validate_data_contract(tenant_id: str, contract_id: str) -> dict:
    """Validate current data against a contract's schema, quality, and SLA expectations."""
    from modules.governance import contract_service
    return await contract_service.validate_contract(
        tenant_id=tenant_id, actor="axiom-agent", contract_id=contract_id)


@tool
async def request_approval(tenant_id: str, user_id: str, session_id: str,
    action_type: str, action_payload: dict, risk_level: str, reason: str) -> dict:
    """Create a human approval request for a risky action. risk_level: low|medium|high.
    user_id and session_id are filled in automatically from the current conversation —
    never invent or guess them."""
    from modules.governance.policy_engine import PolicyEngine
    return await PolicyEngine(tenant_id).create_request(
        user_id=user_id, session_id=session_id, action_name=action_type,
        action_args=action_payload, risk_level=risk_level, reason=reason,
    )


governance_tools = [get_lineage, get_audit_trail, create_data_contract,
                     validate_data_contract, request_approval]
