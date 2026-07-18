import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from config import settings
from jose import JWTError, jwt
from typing import Optional

log = structlog.get_logger()
from services.auth_service import (
    hash_password, issue_token_for_user,
    create_new_tenant_and_user, find_existing_tenants_for_email,
    resolve_password_login, resolve_identity,
    check_email_code_request_allowed, send_login_code, verify_login_code,
    get_google_authorize_url, consume_oauth_state, exchange_google_code, verify_google_id_token,
    store_pending_identity, resolve_pending_identity,
)


router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_role(*allowed_roles: str):
    """Dependency factory: Depends(require_role(Role.OWNER, Role.ADMIN))
    rejects any caller whose JWT `role` claim isn't in the allowed set.
    Layers on top of get_current_user, so it enforces normal auth too."""
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(allowed_roles)}",
            )
        return current_user
    return _check


def enforce_quota(resource: str):
    """Dependency factory: Depends(enforce_quota("ai_credits")) hard-blocks
    a request once the tenant's current usage has reached its plan's limit
    for that resource (see services/quota_service.py for the resource
    list, the credit formula, and the tier-limit rationale). Soft-warning
    at 80% is not enforced here - it's surfaced via GET /billing/usage for
    the frontend's usage bars, since a dependency has no clean way to
    attach a non-blocking warning to an otherwise-successful response."""
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        from services.quota_service import get_quota_status
        result = await get_quota_status(current_user["tenant_id"], resource)
        if result["status"] == "exceeded":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={"error": "quota_exceeded", **result},
            )
        return current_user
    return _check


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    tenant_name: str


@router.post("/register")
async def register(req: RegisterRequest):
    # Non-blocking informational nudge (Phase 3, approved) — surfaced to the
    # client, never blocks signup. Cross-tenant email reuse is an
    # intentionally supported pattern (independent workspace memberships),
    # not a collision.
    existing = await find_existing_tenants_for_email(req.email)

    tenant, user = await create_new_tenant_and_user(
        tenant_name=req.tenant_name, email=req.email, auth_method="password",
        hashed_password=hash_password(req.password), full_name=req.full_name,
    )
    token = issue_token_for_user(user, "password")
    return {
        "access_token": token,
        "token_type": "bearer",
        "tenant_id": tenant.id,
        "user_id": user.id,
        "existing_workspaces": existing,
    }


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), tenant_id: Optional[str] = Form(None)):
    result = await resolve_password_login(form.username, form.password, tenant_id)

    if result["status"] == "invalid":
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if result["status"] == "choose":
        return {"status": "choose_workspace", "options": result["options"]}

    return {
        "access_token": result["token"], "token_type": "bearer",
        "user_id": result["user_id"], "tenant_id": result["tenant_id"],
    }


class EmailCodeRequest(BaseModel):
    email: EmailStr
    intended_tenant_id: Optional[str] = None


@router.post("/email-code/request")
async def request_email_code(req: EmailCodeRequest, request: Request):
    client_ip = request.client.host if request.client else None
    allowed = await check_email_code_request_allowed(req.email, client_ip)
    if not allowed:
        return {"status": "rate_limited"}
    await send_login_code(req.email, req.intended_tenant_id, client_ip)
    return {"status": "sent"}


class EmailCodeVerify(BaseModel):
    email: EmailStr
    code: str
    tenant_id: Optional[str] = None
    new_tenant_name: Optional[str] = None


@router.post("/email-code/verify")
async def verify_email_code(req: EmailCodeVerify):
    verify_result = await verify_login_code(req.email, req.code)
    if verify_result["status"] != "ok":
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    effective_tenant_id = req.tenant_id or verify_result.get("intended_tenant_id")

    identity = await resolve_identity(
        req.email, "email_code", intended_tenant_id=effective_tenant_id,
    )

    if identity["status"] == "single":
        return {
            "access_token": identity["token"], "token_type": "bearer",
            "user_id": identity["user_id"], "tenant_id": identity["tenant_id"],
        }
    if identity["status"] == "choose":
        # The email code was already single-use consumed by verify_login_code()
        # above, so the client can't resubmit it a second time with a
        # tenant_id — stash the now-proven identity and hand back a
        # short-lived token to finalize the pick via /resolve-workspace.
        resolution_token = await store_pending_identity(req.email, "email_code")
        return {"status": "choose_workspace", "options": identity["options"], "resolution_token": resolution_token}

    # status == "none": no existing tenant-account for this email.
    if req.new_tenant_name:
        tenant, user = await create_new_tenant_and_user(
            tenant_name=req.new_tenant_name, email=req.email, auth_method="email_code",
            email_verified=True,
        )
        token = issue_token_for_user(user, "email_code")
        return {
            "access_token": token, "token_type": "bearer",
            "user_id": user.id, "tenant_id": tenant.id,
        }
    return {"status": "no_account", "detail": "No workspace found for this email. Resubmit with new_tenant_name to create one."}


@router.get("/google/login-url")
async def google_login_url():
    return await get_google_authorize_url()


class GoogleCallback(BaseModel):
    code: str
    state: str
    intended_tenant_id: Optional[str] = None
    new_tenant_name: Optional[str] = None


@router.post("/google/callback")
async def google_callback(req: GoogleCallback):
    if not await consume_oauth_state(req.state):
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    try:
        tokens = await exchange_google_code(req.code)
        claims = await verify_google_id_token(tokens["id_token"])
    except Exception as exc:
        log.error("google_auth_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=400, detail="Google authentication failed")

    email = claims["email"]
    google_id = claims["sub"]
    provider_email_verified = bool(claims.get("email_verified"))

    identity = await resolve_identity(
        email, "google", intended_tenant_id=req.intended_tenant_id,
        google_id=google_id, provider_email_verified=provider_email_verified,
    )

    if identity["status"] == "single":
        return {
            "access_token": identity["token"], "token_type": "bearer",
            "user_id": identity["user_id"], "tenant_id": identity["tenant_id"],
        }
    if identity["status"] == "choose":
        # Google's authorization code + state are both single-use and already
        # consumed above — same resolution-token handoff as email-code.
        resolution_token = await store_pending_identity(
            email, "google", google_id=google_id, provider_email_verified=provider_email_verified,
        )
        return {"status": "choose_workspace", "options": identity["options"], "resolution_token": resolution_token}
    if identity["status"] == "blocked_unverified":
        raise HTTPException(
            status_code=403,
            detail="This email already has a password account and Google hasn't verified ownership of it. Log in with your password instead.",
        )

    # status == "none": no existing tenant-account for this email.
    if req.new_tenant_name:
        tenant, user = await create_new_tenant_and_user(
            tenant_name=req.new_tenant_name, email=email, auth_method="google",
            google_id=google_id, email_verified=provider_email_verified,
            full_name=claims.get("name"),
        )
        token = issue_token_for_user(user, "google")
        return {
            "access_token": token, "token_type": "bearer",
            "user_id": user.id, "tenant_id": tenant.id,
        }
    return {"status": "no_account", "detail": "No workspace found for this email. Resubmit with new_tenant_name to create one."}


class ResolveWorkspaceRequest(BaseModel):
    resolution_token: str
    tenant_id: str


@router.post("/resolve-workspace")
async def resolve_workspace(req: ResolveWorkspaceRequest):
    """Finalizes a choose_workspace pick from email-code or Google login, where
    the original proof (email code, Google auth code) was already single-use
    consumed by the time multiple tenant matches were found."""
    result = await resolve_pending_identity(req.resolution_token, req.tenant_id)
    if result["status"] != "single":
        raise HTTPException(status_code=400, detail="Invalid or expired selection")
    return {
        "access_token": result["token"], "token_type": "bearer",
        "user_id": result["user_id"], "tenant_id": result["tenant_id"],
    }


VALID_THEMES = ("light", "dark", "system")


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """Merges the JWT payload with a fresh DB read of `theme` - deliberately
    not a JWT claim (same staleness reasoning as personality_mode/
    operation_mode, Phase 3 decisions), so this must be read fresh here
    rather than baked into the token at issue time."""
    from database import AsyncSessionLocal
    from models.all_models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User.theme).where(User.id == user["sub"]))
        theme = r.scalar()
    return {**user, "theme": theme}


class MeUpdate(BaseModel):
    theme: Optional[str] = None


@router.patch("/me")
async def update_me(body: MeUpdate, user=Depends(get_current_user)):
    """Self-service - a user updating their own preference needs no role
    check beyond being authenticated as themselves."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")
    if "theme" in updates and updates["theme"] is not None and updates["theme"] not in VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"Invalid theme '{updates['theme']}'. Valid: {list(VALID_THEMES)}")

    from database import AsyncSessionLocal
    from models.all_models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user["sub"]))
        db_user = r.scalars().first()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")
        if "theme" in updates:
            db_user.theme = updates["theme"]
        await db.commit()
        return {"theme": db_user.theme}
