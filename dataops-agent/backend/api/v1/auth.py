from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from config import settings
from jose import JWTError, jwt
from typing import Optional
from services.auth_service import (
    hash_password, issue_token_for_user,
    create_new_tenant_and_user, find_existing_tenants_for_email,
    resolve_password_login, resolve_identity,
    check_email_code_request_allowed, send_login_code, verify_login_code,
)


router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


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
        return {"status": "choose_workspace", "options": identity["options"]}

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


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user
