import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user
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