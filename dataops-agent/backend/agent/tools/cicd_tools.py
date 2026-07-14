# agent/tools/cicd_tools.py

import httpx
from langchain.tools import tool

@tool
def get_cicd_status(query: str) -> str:
    """
    Get CICD pipeline deployment status.
    Use when user asks about: CI status, deployments, rollbacks,
    pending approvals, or pipeline health.
    """
    try:
        r = httpx.get(
            "http://localhost:8000/api/v1/cicd/status/summary",
            timeout=5
        )
        data = r.json()
        return (
            f"CICD Status Summary:\n"
            f"- Commit results: {data.get('commit_stats', {})}\n"
            f"- Active deployments: {data.get('active_deployments', 0)}\n"
            f"- Total rollbacks: {data.get('total_rollbacks', 0)}\n"
            f"- Pending approvals: {data.get('pending_approvals', 0)}\n"
            f"- Overall health: {data.get('health', 'unknown')}"
        )
    except Exception as e:
        return f"Could not retrieve CICD status: {e}"