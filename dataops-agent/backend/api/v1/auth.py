import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from config import settings
from jose import JWTError, jwt
from typing import Optional

log = structlog.get_logger()
from services.auth_service import (
    hash_password, issue_token_and_remember,
    create_new_tenant_and_user, find_existing_tenants_for_email,
    resolve_password_login, resolve_identity, switch_workspace, WorkspaceSwitchRateLimited,
    check_email_code_request_allowed, send_login_code, verify_login_code,
    get_google_authorize_url, consume_oauth_state, exchange_google_code, verify_google_id_token,
    store_pending_identity, resolve_pending_identity,
)


router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# Item #13: an owner/admin past their MFA enrolment deadline may still reach
# these -- they are what enrolling, checking status, and logging out need.
# Everything else answers 403 mfa_enrollment_required until MFA is enabled.
MFA_ENROLLMENT_EXEMPT_PREFIXES = ("/api/v1/auth/",)


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)) -> dict:
    """Decodes the JWT, then re-reads `is_active`/`role` fresh from the DB —
    exactly once per request (FastAPI caches a dependency's return value per
    request by default, and every other dependency in this file/every route
    handler depends on this same callable, so the extra query below never
    runs more than once regardless of how many permission/quota checks a
    request triggers). Closes the "removed/demoted member keeps their old
    JWT's access for up to the token's full TTL" gap (see CLAUDE.md
    Known-broken) — is_active=False is rejected immediately, for every
    authenticated request app-wide, not just role-gated ones; role is
    refreshed so a demoted user loses their old capabilities on their very
    next request instead of at token expiry."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    from database import AsyncSessionLocal
    from models.all_models import Tenant, User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        # `plan` is joined onto the query that already runs here rather than
        # fetched separately: this read happens once per request regardless, so
        # carrying the tenant's tier costs a join instead of a second round
        # trip. It is not in the JWT deliberately — a plan change would then
        # not take effect until the token expired, the same staleness class as
        # the role gap this function exists to close.
        r = await db.execute(
            select(User.is_active, User.role, User.tenant_id, Tenant.plan,
                   User.mfa_enabled, User.mfa_required_since, User.created_at)
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(User.id == payload.get("sub"))
        )
        row = r.first()

    if row is None or not row.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Revocation: a specifically-blocklisted jti, or a token issued before this
    # user's current epoch ("log out all devices"). Checked here as well as in
    # both middlewares — see services/token_revocation.py.
    from services.token_revocation import is_revoked
    if await is_revoked(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # The tenant_id claim was trusted but never verified. Safe in practice
    # (nothing mutates User.tenant_id, and forging the claim needs the signing
    # key) — but it is an assumption, and both middlewares scope RLS and rate
    # limiting off this claim before this function ever runs. Making it a
    # structural check costs nothing: the row is already in hand.
    if payload.get("tenant_id") != row.tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Item #13: MFA is mandatory for owners and admins. After the grace
    # period an un-enrolled one is refused everywhere except the auth routes
    # (status, setup, enable, me, revoke) -- a hard block on the privileged
    # capability, with the way out left open. A grace period rather than an
    # immediate block because the rule lands on existing accounts; a lockout
    # nobody was warned about is an outage, not a control.
    from services.mfa_service import enrollment_overdue
    # Item #14 Option B: a session whose token carries the signed mfa_via_idp
    # claim was authenticated through an IdP the tenant's owner chose to
    # trust for MFA; that satisfies the mandate for this session only.
    if enrollment_overdue(row.role, row.mfa_enabled, row.mfa_required_since, row.created_at) \
            and not payload.get("mfa_via_idp") \
            and not request.url.path.startswith(MFA_ENROLLMENT_EXEMPT_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "mfa_enrollment_required",
                    "message": "Multi-factor authentication is required for your role. "
                               "Enable it under Settings -> Security to continue."},
        )

    payload["role"] = row.role
    payload["plan"] = row.plan
    payload["mfa_enabled"] = bool(row.mfa_enabled)
    payload["mfa_via_idp"] = bool(payload.get("mfa_via_idp", False))
    return payload


def require_permission(capability: str):
    """Dependency factory: Depends(require_permission("sources.delete"))
    rejects any caller whose current role (freshly re-read by
    get_current_user above, not trusted from the JWT alone) lacks this
    capability under services/rbac.py's PERMISSIONS map — the same map
    agent_node's tool-dispatch gate reads for AXIOM's tool calls, so REST
    and chat can never silently drift onto two different rulebooks. Layers
    on top of get_current_user, so it enforces normal auth too."""
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        from services.rbac import has_permission
        if not has_permission(current_user.get("role"), capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to do this — requires a role with '{capability}' access.",
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


class RevokeRequest(BaseModel):
    # Default is the safer of the two: "log out everywhere" is the action a
    # user reaches for when they think they have been compromised, and quietly
    # revoking only the current session in that moment would leave the attacker
    # logged in while the user believed otherwise.
    scope: str = "all"


@router.post("/revoke")
async def revoke_tokens(body: RevokeRequest, user=Depends(get_current_user)):
    """Self-service revocation.

    scope="all" (default) — bumps the caller's token epoch, invalidating every
    token they hold, on every device, immediately. This is "log out all
    devices". It is implemented as one counter rather than by tracking each
    issued jti: a per-user set of jtis grows with every login and needs
    reconciling as tokens expire, whereas the epoch does the same job in O(1)
    with nothing to clean up.

    scope="current" — blocklists only the calling token's own jti, leaving the
    user's other sessions alone. For "sign out this browser" without disturbing
    their phone.

    Note the caller's own token is invalidated either way: the response is the
    last thing this token can do. That is the intended behaviour for both
    scopes, not an oversight.
    """
    from services.token_revocation import bump_epoch, revoke_jti

    if body.scope == "current":
        await revoke_jti(user.get("jti"), user.get("exp"))
        # Found 2026-10-01, privilege-events audit sweep: self-service
        # revocation had no audit row at all. After the revoke, own session
        # (see the identity-audit PR for why this isn't atomic and why
        # that's accepted here -- unchanged log_action, not gated on).
        from modules.governance.audit_trail import AuditTrail
        await AuditTrail(user["tenant_id"]).log_action(
            actor=user["email"], action="auth.session_revoked",
            resource_type="user", resource_id=user["sub"],
            payload={"scope": body.scope},
        )
        return {"revoked": "current_session"}

    if body.scope != "all":
        raise HTTPException(
            status_code=400,
            detail="scope must be 'all' or 'current'",
        )

    epoch = await bump_epoch(user["sub"])
    from modules.governance.audit_trail import AuditTrail
    await AuditTrail(user["tenant_id"]).log_action(
        actor=user["email"], action="auth.all_sessions_revoked",
        resource_type="user", resource_id=user["sub"],
        payload={"scope": body.scope},
    )
    return {"revoked": "all_sessions", "epoch": epoch}


async def enforce_agent_budget(agent_id: str | None) -> None:
    """Gate 2 of the two-gate per-agent token-budget path (Wunomo
    Projects Phase 1, part two) - both gates must pass, and this one
    never replaces enforce_quota("ai_credits")'s existing tenant-level
    gate above, which keeps running as its own dependency. Not a
    dependency itself, unlike enforce_quota: a real agent_id isn't known
    until chat.py/tasks.py resolve the tenant's real agent deeper in the
    endpoint body (mirroring the same reason agent_scope_denial_reason()
    can't be a dependency either), so this is a plain function callers
    invoke directly once they have one. agent_id=None is a no-op - no
    agent context, nothing to check - matching every other agent-scope
    check's own convention this phase."""
    if agent_id is None:
        return
    from services.quota_service import get_agent_quota_status
    result = await get_agent_quota_status(agent_id)
    if result["status"] == "exceeded":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            # agent_id (Wunomo Projects Phase 2 frontend, slice 9): without
            # it, a frontend catching this 402 has no way to link to the
            # one agent whose budget is actually the problem -- the caller
            # already has it (it's this function's own argument), so there
            # was no reason to make the frontend re-resolve it.
            detail={"error": "agent_budget_exceeded", "agent_id": agent_id, **result},
        )


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
    token = await issue_token_and_remember(user, "password")
    return {
        "access_token": token,
        "token_type": "bearer",
        "tenant_id": tenant.id,
        "user_id": user.id,
        "existing_workspaces": existing,
    }


def _session_response(result: dict) -> dict:
    """Item #13: a proven first factor is either a session or an MFA
    challenge. Every route that used to build the access_token dict by hand
    goes through this so none can forget the second-factor branch."""
    if result["status"] == "mfa_required":
        return {"status": "mfa_required", "mfa_token": result["mfa_token"],
                "user_id": result["user_id"], "tenant_id": result["tenant_id"]}
    return {
        "access_token": result["token"], "token_type": "bearer",
        "user_id": result["user_id"], "tenant_id": result["tenant_id"],
    }


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), tenant_id: Optional[str] = Form(None)):
    result = await resolve_password_login(form.username, form.password, tenant_id)

    if result["status"] == "invalid":
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if result["status"] == "choose":
        return {"status": "choose_workspace", "options": result["options"]}

    return _session_response(result)


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

    if identity["status"] in ("single", "mfa_required"):
        return _session_response(identity)
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
        token = await issue_token_and_remember(user, "email_code")
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

    if identity["status"] in ("single", "mfa_required"):
        return _session_response(identity)
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
        token = await issue_token_and_remember(user, "google")
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
    if result["status"] not in ("single", "mfa_required"):
        raise HTTPException(status_code=400, detail="Invalid or expired selection")
    return _session_response(result)


@router.get("/my-workspaces")
async def my_workspaces(user=Depends(get_current_user)):
    """Item 1: backs the sidebar's real workspace switcher - every tenant
    this authenticated email has an active account in, for the same
    WorkspacePicker component login's choose_workspace step already uses."""
    options = await find_existing_tenants_for_email(user["email"], active_only=True)
    return {"options": options}


class SwitchWorkspaceRequest(BaseModel):
    tenant_id: str


@router.post("/switch-workspace")
async def switch_workspace_route(req: SwitchWorkspaceRequest, request: Request, user=Depends(get_current_user)):
    """Item 1: re-issues a fresh token for a different tenant the caller
    already has an active account in - no password re-entry, since
    get_current_user already proved identity for this request. tenant_id
    is baked into the JWT, so there is no way to "switch" without a new
    token."""
    client_ip = request.client.host if request.client else None
    try:
        result = await switch_workspace(user["email"], user["tenant_id"], req.tenant_id, ip=client_ip)
    except WorkspaceSwitchRateLimited:
        raise HTTPException(status_code=429, detail="Too many workspace switches recently — wait a bit and try again.")
    if result is None:
        raise HTTPException(status_code=403, detail="You don't have an active account in that workspace.")
    if result.get("status") == "mfa_required":
        return _session_response(result)
    return {"token_type": "bearer", **result}


VALID_THEMES = ("light", "dark", "system")


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """Merges the JWT payload with a fresh DB read of `theme`/`email_verified`
    - deliberately not JWT claims (same staleness reasoning as
    personality_mode/operation_mode, Phase 3 decisions), so both must be read
    fresh here rather than baked into the token at issue time. email_verified
    in particular must never be stale: it's what item 25's Settings notice
    checks to decide whether to show the "verify your email" prompt, and a
    token issued before verifying would otherwise keep showing it forever."""
    from database import AsyncSessionLocal
    from models.all_models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User.theme, User.email_verified, User.role, User.mfa_enabled,
                                    User.mfa_required_since, User.created_at).where(User.id == user["sub"]))
        row = r.one()
    # Item #13: enough for the UI to nag an owner/admin before their deadline.
    from services.mfa_service import enrollment_overdue, is_mandatory_for_role
    from datetime import timedelta as _td
    from config import settings as _settings
    mfa_deadline = None
    if is_mandatory_for_role(row.role) and not row.mfa_enabled:
        since = row.mfa_required_since or row.created_at
        mfa_deadline = (since + _td(days=_settings.MFA_GRACE_DAYS)).isoformat() if since else None
    return {**user, "theme": row.theme, "email_verified": bool(row.email_verified),
            "mfa_enabled": bool(row.mfa_enabled), "mfa_required": is_mandatory_for_role(row.role),
            "mfa_enrollment_deadline": mfa_deadline,
            "mfa_overdue": enrollment_overdue(row.role, row.mfa_enabled, row.mfa_required_since, row.created_at)}


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
