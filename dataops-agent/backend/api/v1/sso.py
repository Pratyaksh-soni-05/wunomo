"""Enterprise SSO endpoints (Security Master Ranking Item #14). Mounted at
/api/v1/auth/sso.

    POST /start     {email}          PRE-AUTH  -> {url, state} to redirect to, or 404
    POST /callback  {code, state}    PRE-AUTH  -> the same session response every login returns
    GET  /config                     settings.manage
    PUT  /config    {...}            settings.manage; satisfies_mfa changes need owner

An SSO login ends in _session_response() exactly like password / Google /
email-code, so "mfa_required" (Option A) or a token (single, or Option B)
comes back in the same shape the frontend already handles.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional

from .auth import get_current_user, require_permission, _session_response
from config import settings
from services import sso_service

router = APIRouter()


class StartBody(BaseModel):
    email: EmailStr


class CallbackBody(BaseModel):
    code: str
    state: str


class ConfigBody(BaseModel):
    connection_id: Optional[str] = ""
    email_domain: Optional[str] = ""
    enabled: bool = False
    satisfies_mfa: bool = False


@router.post("/start")
async def sso_start(body: StartBody):
    out = await sso_service.start(body.email)
    if "error" in out:
        code = out.get("code")
        raise HTTPException(status_code=503 if code == "not_configured" else 404, detail=out["error"])
    return out


@router.post("/callback")
async def sso_callback(body: CallbackBody):
    identity = await sso_service.complete(body.code, body.state)
    status = identity.get("status")
    if status in ("single", "mfa_required"):
        return _session_response(identity)
    if status == "invalid_state":
        raise HTTPException(status_code=400, detail="Invalid or expired SSO state. Start again.")
    if status == "disabled":
        raise HTTPException(status_code=403, detail="Single sign-on is disabled for this workspace.")
    if status == "exchange_failed":
        raise HTTPException(status_code=400, detail="SSO sign-in failed at the identity provider.")
    if status == "connection_mismatch":
        raise HTTPException(status_code=403, detail="This sign-in came from a different identity provider than the workspace's.")
    if status in ("domain_mismatch", "blocked_unverified"):
        raise HTTPException(status_code=403, detail=(
            "The identity provider asserted an email outside this workspace's SSO domain, "
            "so the sign-in was refused."))
    raise HTTPException(status_code=400, detail="SSO sign-in could not be completed.")


@router.get("/config")
async def sso_get_config(user=Depends(require_permission("settings.manage"))):
    cfg = await sso_service.get_config(user["tenant_id"])
    return {**cfg, "configured_on_deployment": sso_service.is_configured(),
            "redirect_uri": settings.SSO_REDIRECT_URI}


@router.put("/config")
async def sso_put_config(body: ConfigBody, user=Depends(require_permission("settings.manage"))):
    try:
        cfg = await sso_service.set_config(
            user["tenant_id"], body.model_dump(), actor=user["email"], actor_role=user.get("role", ""))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return cfg
