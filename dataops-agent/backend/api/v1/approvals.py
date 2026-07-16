import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc

from .auth import get_current_user
from database import get_db
from models.cicd import PipelineCommit
from modules.governance.policy_engine import PolicyEngine
from modules.governance.audit_trail import AuditTrail

log = structlog.get_logger()
router = APIRouter()


# ------------------------------------------------------------------
# Pydantic schemas
# ------------------------------------------------------------------

class ResolveRequest(BaseModel):
    notes: Optional[str] = ""


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
@router.get("/")
async def list_pending_approvals(user=Depends(get_current_user)):
    """
    Returns all pending approval requests for the tenant.
    Ordered by created_at descending.
    """
    engine = PolicyEngine(user["tenant_id"])
    result = await engine.list_pending()
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"approvals": result, "count": len(result)}


@router.get("/merged")
async def list_merged_approvals(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Combines the two real, separate pending-approval queues this tenant can
    have — general agent-action approvals (PolicyEngine) and CI/CD deployment
    gates (PipelineCommit.gate_decision == "pending_approval") — into one
    tenant-scoped, chronologically-ordered list. Read-only: each item is
    tagged with `source` so the client resolves approve/reject to the
    correct existing endpoint (/approvals/{id}/approve|reject for
    "policy_engine", /cicd/commits/{id}/approve|reject for "cicd_deployment")
    rather than this endpoint inventing a second mutation path.

    Excludes PolicyEngine requests with action_name == "cicd_pipeline_deployment":
    services/cicd_tasks.py creates one of these alongside every high-risk
    commit's gate_decision, but "cicd_pipeline_deployment" was never added to
    PolicyEngine.TOOL_REGISTRY — approving it always fails execution (no
    deploy triggered) while leaving the real gate_decision stuck pending, so
    showing it as an actionable item would be actively misleading. The
    PipelineCommit side is the one real, tested, role-gated action for this
    event; this exclusion is a read-side dedupe only, not a fix to the
    underlying double-bookkeeping (tracked in CLAUDE.md's Known-broken table).
    """
    engine = PolicyEngine(user["tenant_id"])
    policy_result = await engine.list_pending()
    if isinstance(policy_result, dict) and "error" in policy_result:
        raise HTTPException(status_code=500, detail=policy_result["error"])

    merged = [
        {
            "id": item["approval_id"],
            "source": "policy_engine",
            "title": item["action_name"],
            "description": item["reason"],
            "risk_level": item["risk_level"],
            "created_at": item["created_at"],
            "raw": item,
        }
        for item in policy_result
        if item["action_name"] != "cicd_pipeline_deployment"
    ]

    commit_result = await db.execute(
        select(PipelineCommit).where(
            PipelineCommit.tenant_id == user["tenant_id"],
            PipelineCommit.gate_decision == "pending_approval",
        ).order_by(desc(PipelineCommit.trigger_time))
    )
    for c in commit_result.scalars().all():
        merged.append({
            "id": str(c.id),
            "source": "cicd_deployment",
            "title": f"Deploy {c.commit_sha[:8]} to production",
            "description": c.commit_message or f"{c.branch} @ {c.commit_sha[:8]} by {c.author or 'unknown'}",
            "risk_level": "high" if (c.risk_score or 0) >= 0.7 else "medium" if (c.risk_score or 0) >= 0.4 else "low",
            "created_at": c.trigger_time.isoformat() if c.trigger_time else None,
            "raw": {
                "commit_id": str(c.id), "pipeline_id": c.pipeline_id, "commit_sha": c.commit_sha,
                "branch": c.branch, "author": c.author, "risk_score": c.risk_score,
                "check_results": c.check_results,
            },
        })

    merged.sort(key=lambda a: a["created_at"] or "", reverse=True)
    return {"approvals": merged, "count": len(merged)}


@router.get("/{approval_id}")
async def get_approval(approval_id: str, user=Depends(get_current_user)):
    """Get a single approval request by ID."""
    engine = PolicyEngine(user["tenant_id"])
    result = await engine.get_request(approval_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{approval_id}/approve")
async def approve_action(
    approval_id: str,
    body: ResolveRequest,
    user=Depends(get_current_user),
):
    """
    Approve a pending action and execute it immediately.
    The execution result is stored on the approval request.
    Only users with role 'admin' or 'owner' may approve.
    """
    if user.get("role") not in ("admin", "owner"):
        raise HTTPException(
            status_code=403,
            detail="Only admins and owners can approve actions",
        )

    engine = PolicyEngine(user["tenant_id"])
    result = await engine.approve(
        approval_id=approval_id,
        reviewer=user["email"],
        notes=body.notes or "",
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"],
        action="approval.granted",
        resource_type="approval",
        resource_id=approval_id,
        payload={
            "notes": body.notes,
            "execution_status": result.get("status"),
        },
    )
    return result


@router.post("/{approval_id}/reject")
async def reject_action(
    approval_id: str,
    body: ResolveRequest,
    user=Depends(get_current_user),
):
    """
    Reject a pending action. The action will not be executed.
    Only users with role 'admin' or 'owner' may reject.
    """
    if user.get("role") not in ("admin", "owner"):
        raise HTTPException(
            status_code=403,
            detail="Only admins and owners can reject actions",
        )

    engine = PolicyEngine(user["tenant_id"])
    result = await engine.reject(
        approval_id=approval_id,
        reviewer=user["email"],
        notes=body.notes or "",
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"],
        action="approval.rejected",
        resource_type="approval",
        resource_id=approval_id,
        payload={"notes": body.notes},
    )
    return result