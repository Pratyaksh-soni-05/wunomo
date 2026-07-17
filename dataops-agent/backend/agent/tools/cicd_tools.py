# agent/tools/cicd_tools.py

from langchain_core.tools import tool

@tool
async def get_cicd_status(tenant_id: str, query: str = "") -> str:
    """
    Get CICD pipeline deployment status for the authenticated tenant.
    Use when user asks about: CI status, deployments, rollbacks,
    pending approvals, or pipeline health.
    """
    from database import AsyncSessionLocal
    from services.cicd_service import get_status_summary
    async with AsyncSessionLocal() as db:
        data = await get_status_summary(db, tenant_id)
    return (
        f"CICD Status Summary:\n"
        f"- Commit results: {data.get('commit_stats', {})}\n"
        f"- Active deployments: {data.get('active_deployments', 0)}\n"
        f"- Total rollbacks: {data.get('total_rollbacks', 0)}\n"
        f"- Pending approvals: {data.get('pending_approvals', 0)}\n"
        f"- Overall health: {data.get('health', 'unknown')}"
    )