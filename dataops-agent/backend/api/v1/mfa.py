"""MFA endpoints (Security Master Ranking Item #13). Mounted at /api/v1/auth/mfa.

    GET  /status                         authenticated
    POST /setup                          authenticated  -> secret + otpauth:// URI (pending, in Redis)
    POST /enable      {code}             authenticated  -> verifies against the pending secret; only then enabled
    POST /disable     {code}             authenticated  -> refused for owner/admin (mandatory)
    POST /backup-codes/regenerate {code} authenticated
    POST /verify      {mfa_token, code}  PRE-AUTH       -> the login second step; mints the JWT

State changes (enable / disable / regenerate) bump the user's token epoch --
Item #4's "log out all devices" -- and return a fresh access_token so the
client that made the change is not logged out by it. The QR code is not
generated here: the frontend renders the otpauth:// URI.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import User
from modules.governance.audit_trail import AuditTrail
from services import mfa_service
from services.auth_service import issue_token_and_remember
from services.tenant_context import tenant_session
from services.token_revocation import bump_epoch
from sqlalchemy import select

router = APIRouter()


class CodeBody(BaseModel):
    code: str


class VerifyBody(BaseModel):
    mfa_token: str
    code: str


async def _user(user_id: str, tenant_id: str) -> User:
    async with tenant_session(tenant_id) as db:
        u = (await db.execute(select(User).where(
            User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return u


async def _fresh_token_after_bump(user_id: str, tenant_id: str, auth_method: str) -> str:
    """Bump the epoch (every other session dies) and mint a token in the NEW
    epoch for the caller, in that order, so the returned token survives."""
    await bump_epoch(user_id)
    return await issue_token_and_remember(await _user(user_id, tenant_id), auth_method)


@router.get("/status")
async def mfa_status(user=Depends(get_current_user)):
    return await mfa_service.status_for(user["sub"], user["tenant_id"])


@router.post("/setup")
async def mfa_setup(user=Depends(get_current_user)):
    out = await mfa_service.start_setup(user["sub"], user["tenant_id"])
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    return out


@router.post("/enable")
async def mfa_enable(body: CodeBody, user=Depends(get_current_user)):
    out = await mfa_service.confirm_setup(user["sub"], user["tenant_id"], body.code)
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    token = await _fresh_token_after_bump(user["sub"], user["tenant_id"], user.get("auth_method", "password"))
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="mfa.enabled", resource_type="user", resource_id=user["sub"],
        payload={"backup_codes_issued": len(out["backup_codes"])})
    return {**out, "access_token": token, "token_type": "bearer",
            "note": "Other sessions have been signed out. Store the backup codes now; they are not shown again."}


@router.post("/disable")
async def mfa_disable(body: CodeBody, user=Depends(get_current_user)):
    if mfa_service.is_mandatory_for_role(user.get("role")):
        raise HTTPException(status_code=403, detail="MFA is mandatory for owners and admins and cannot be disabled.")
    factor = await mfa_service.verify_code_for_user(user["sub"], user["tenant_id"], body.code)
    if factor is None:
        raise HTTPException(status_code=400, detail="A valid authenticator or backup code is required to disable MFA.")
    out = await mfa_service.disable(user["sub"], user["tenant_id"])
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    token = await _fresh_token_after_bump(user["sub"], user["tenant_id"], user.get("auth_method", "password"))
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="mfa.disabled", resource_type="user", resource_id=user["sub"],
        payload={"verified_with": factor})
    return {**out, "access_token": token, "token_type": "bearer"}


@router.post("/backup-codes/regenerate")
async def mfa_regenerate_backup_codes(body: CodeBody, user=Depends(get_current_user)):
    factor = await mfa_service.verify_code_for_user(user["sub"], user["tenant_id"], body.code)
    if factor is None:
        raise HTTPException(status_code=400, detail="A valid authenticator or backup code is required.")
    out = await mfa_service.regenerate_backup_codes(user["sub"], user["tenant_id"])
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    token = await _fresh_token_after_bump(user["sub"], user["tenant_id"], user.get("auth_method", "password"))
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="mfa.backup_codes_regenerated", resource_type="user",
        resource_id=user["sub"], payload={"verified_with": factor})
    return {**out, "access_token": token, "token_type": "bearer"}


@router.post("/verify")
async def mfa_verify(body: VerifyBody):
    """Second step of login. Pre-auth: rate limited per IP with /login, and
    each challenge dies after MAX_CHALLENGE_ATTEMPTS wrong codes."""
    out = await mfa_service.resolve_challenge(body.mfa_token, body.code)
    if out["status"] == "invalid":
        raise HTTPException(status_code=400, detail="Invalid or expired MFA challenge. Log in again.")
    if out["status"] == "exhausted":
        raise HTTPException(status_code=400, detail="Too many incorrect codes. Log in again.")
    if out["status"] == "wrong":
        raise HTTPException(status_code=400, detail=f"Incorrect code. {out['attempts_left']} attempt(s) left.")
    user = await _user(out["user_id"], out["tenant_id"])
    token = await issue_token_and_remember(user, out["auth_method"])
    if out["factor"] == "backup":
        await AuditTrail(user.tenant_id).log_action(
            actor=user.email, action="mfa.backup_code_used", resource_type="user", resource_id=user.id,
            payload={"remaining": len(user.mfa_backup_codes or [])})
    return {"access_token": token, "token_type": "bearer", "user_id": user.id,
            "tenant_id": user.tenant_id, "factor": out["factor"],
            "backup_codes_remaining": len(user.mfa_backup_codes or []) if out["factor"] == "backup" else None}
