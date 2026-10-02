import asyncio
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import httpx
import structlog
from jose import jwt
from redis import asyncio as aioredis
from slugify import slugify
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models.all_models import (
    AgentEmployeeType, AgentInstance, AgentInstanceStatus, EmailLoginCode,
    OperationMode, PersonalityMode, Tenant, User, UserWorkspacePreference,
)
from services.tenant_context import with_tenant_context, async_tenant_context, apply_tenant_to_session, tenant_session

log = structlog.get_logger()

# A module-level client created at import time binds to whatever event loop
# happens to exist then — fine for a real app (one loop, whole process
# lifetime), but breaks across pytest-asyncio's test/loop boundaries
# ("RuntimeError: Event loop is closed" on a later test's first Redis call).
# Lazily create (and recreate if the running loop has changed) instead.
_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client

# ---------------------------------------------------------------------------
# Rate limit / TTL constants — Phase 3 design, approved defaults (tunable
# later without a redesign; see FRONTEND_BUILD_PLAN.md's Phase 3 section).
# ---------------------------------------------------------------------------
CODE_TTL_MINUTES = 10
MAX_VERIFY_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
MAX_REQUESTS_PER_EMAIL_PER_HOUR = 5
MAX_REQUESTS_PER_IP_PER_HOUR = 20
LOCKOUT_MINUTES = 30
CONSECUTIVE_EXHAUSTIONS_FOR_LOCKOUT = 3

# Item 1's switch-workspace endpoint: not a guessing/brute-force target the
# way login is (the caller must already hold a valid, authenticated session
# and a real active membership in the target tenant - there's no secret to
# guess), so these are generous compared to the OTP limits above, sized
# against script/abuse volume rather than credential-stuffing. Reuses
# _check_and_increment(), the same real Redis mechanism email-code login
# already uses, rather than a new one-off scheme.
MAX_WORKSPACE_SWITCHES_PER_EMAIL_PER_HOUR = 30
MAX_WORKSPACE_SWITCHES_PER_IP_PER_HOUR = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Password + JWT (moved here from api/v1/auth.py so every auth method — and
# the shared resolution logic below — shares one implementation)
# ---------------------------------------------------------------------------

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw[:72].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw[:72].encode("utf-8"), hashed.encode("utf-8"))


# The literal default in config.py. It is on GitHub, so a deployment that
# somehow boots with it is signing every token with a public string.
_PLACEHOLDER_JWT_SECRET = "dev-jwt-secret"
# HS256 needs at least as many bytes of secret as the hash width to give the
# strength it advertises; the value that was actually in .env until Item #8
# was 9 characters.
_MIN_JWT_SECRET_LEN = 32


class JwtSecretMisconfiguredError(RuntimeError):
    pass


def verify_jwt_secret_configured() -> None:
    """Fail loudly at app startup rather than on the first login.

    Mirrors encryption_service.verify_encryption_key_configured(), for the
    same reason and with the same test carve-out. config.py declares
    `JWT_SECRET: str = "dev-jwt-secret"`, so a fresh clone, a stripped CI
    environment, or a deploy whose .env never made it across would boot
    cleanly and then sign every session with a value anyone can read in the
    repository. Nothing would raise; logins would simply work. That is the
    failure mode this closes.

    Called from main.py's lifespan hook. Tests set APP_ENV=test (conftest.py
    line 2) and use whatever the environment provides, exactly as the
    encryption guard allows them to.
    """
    if settings.APP_ENV == "test":
        return
    secret = (settings.JWT_SECRET or "").strip()
    if not secret or secret == _PLACEHOLDER_JWT_SECRET:
        raise JwtSecretMisconfiguredError(
            "JWT_SECRET is unset or still the placeholder from config.py. Every "
            "token would be signed with a publicly known value. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_hex(32))"\n'
            "then set it in dataops-agent/.env (the file Docker actually reads) "
            "and recreate the backend:\n"
            "  docker compose up -d --force-recreate backend"
        )
    if len(secret) < _MIN_JWT_SECRET_LEN:
        raise JwtSecretMisconfiguredError(
            f"JWT_SECRET is only {len(secret)} characters; at least "
            f"{_MIN_JWT_SECRET_LEN} are required for HS256 to give the strength "
            f"it advertises. Regenerate with: "
            f'python -c "import secrets; print(secrets.token_hex(32))"'
        )


def create_token(data: dict) -> str:
    """Every token this app issues is minted here, so `jti` is added here.

    `jti` is a unique id per token, which is what makes revoking ONE token
    possible — without it the only lever is "invalidate everything this user
    holds". Generated with uuid4: no I/O, so this stays synchronous and all
    five issuing paths (password, email-code, Google, workspace-switch,
    invite-accept) get one for free rather than each needing to remember.
    """
    now = utcnow()
    exp = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {**data, "jti": uuid.uuid4().hex, "iat": now, "exp": exp},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM,
    )


def issue_token_for_user(user: User, auth_method: str, epoch: int = 0,
                         extra_claims: Optional[dict] = None) -> str:
    """Kept synchronous (see issue_token_and_remember's docstring for why).

    `epoch` therefore has to be passed in rather than read here — the lookup is
    async. It defaults to 0, and that default fails CLOSED rather than open: a
    user who has never revoked sits at epoch 0, so a 0-token is valid for them;
    a user who HAS revoked sits at 1 or higher, so a 0-token is immediately
    stale (0 < 1) and rejected. A caller forgetting to pass the epoch produces
    a token that stops working, never one that outlives a revocation.
    """
    return create_token({
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "role": user.role,
        "auth_method": auth_method,
        "epoch": epoch,
        **(extra_claims or {}),
    })


async def establish_session(user: User, auth_method: str, mfa_via_idp: bool = False) -> dict:
    """Item #13: the ONE place a proven first factor becomes a session.

    Every login path -- password, email-code, Google, the pending-identity
    finalisation, and workspace switch -- ends here. If the user has MFA
    enabled, no JWT is minted: a short-lived single-use challenge is created
    instead and the caller returns {"status": "mfa_required"}; the JWT is
    minted only by POST /auth/mfa/verify against that challenge. Putting the
    fork here rather than in each route means a login path added later
    cannot skip the second factor by omission.
    """
    # Item #14, MFA composition. Option A (default): SSO is a first factor
    # like any other, so an account with TOTP enabled still completes it.
    # Option B: the tenant's owner opted in to trusting the IdP's MFA
    # (Tenant.settings.sso.satisfies_mfa); an SSO session then skips Wunomo
    # TOTP and carries a signed claim that also satisfies the owner/admin
    # mandate for THIS session only. The flag reaches here only from
    # sso_service.complete(), which read it from the tenant's own config.
    trusted_idp = auth_method == "sso" and mfa_via_idp
    if user.mfa_enabled and not trusted_idp:
        from services.mfa_service import create_challenge
        return {
            "status": "mfa_required", "mfa_token": await create_challenge(user, auth_method),
            "user_id": user.id, "tenant_id": user.tenant_id,
        }
    extra = {"mfa_via_idp": True} if trusted_idp else None
    return {
        "status": "single", "token": await issue_token_and_remember(user, auth_method, extra_claims=extra),
        "user_id": user.id, "tenant_id": user.tenant_id,
    }


async def issue_token_and_remember(user: User, auth_method: str,
                                   extra_claims: Optional[dict] = None) -> str:
    """Item 1: wraps issue_token_for_user() with the "remember the last
    workspace used" write, for the real login/signup/invite-accept/switch
    call sites (6 of them, confirmed by grep, every one a genuine "a
    session was just established" moment) -- kept as a separate async
    function rather than making issue_token_for_user itself async so the
    ~20 test files that call it directly as a plain synchronous "mint a
    token for this seeded user" helper don't all need touching for
    something they don't care about."""
    # Stamp the user's current token epoch. This is the async half that
    # issue_token_for_user() cannot do itself, and it is why every real login
    # path goes through this wrapper rather than the sync function directly.
    from services.token_revocation import current_epoch
    token = issue_token_for_user(user, auth_method, epoch=await current_epoch(user.id),
                                 extra_claims=extra_claims)
    await _remember_workspace(user.email, user.tenant_id)
    return token


@with_tenant_context
async def _remember_workspace(email: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(UserWorkspacePreference).where(UserWorkspacePreference.email == email))
        pref = r.scalars().first()
        if pref is None:
            db.add(UserWorkspacePreference(email=email, tenant_id=tenant_id, updated_at=utcnow()))
        else:
            pref.tenant_id = tenant_id
            pref.updated_at = utcnow()
        await db.commit()


async def _remembered_workspace(email: str) -> Optional[str]:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(UserWorkspacePreference.tenant_id).where(UserWorkspacePreference.email == email))
        return r.scalar()


async def _match_remembered(email: str, candidates: list[User]) -> Optional[User]:
    """Item 1: when an email resolves to more than one active tenant
    account, skip the choose-workspace picker if the remembered one is
    still a valid, current candidate. If the remembered tenant was
    deleted, or the user's own row there was deactivated/removed since
    (no longer in `candidates`, which is already filtered to
    is_active-only by both callers), this returns None and the caller
    falls through to its existing "choose" behavior unchanged -- never a
    hard failure, never a silently-wrong tenant."""
    remembered = await _remembered_workspace(email)
    if not remembered:
        return None
    return next((c for c in candidates if c.tenant_id == remembered), None)


# ---------------------------------------------------------------------------
# Tenant creation (shared by register(), email-code, and Google — all three
# "create a new workspace" paths are otherwise identical)
# ---------------------------------------------------------------------------

async def create_new_tenant_and_user(
    *, tenant_name: str, email: str, auth_method: str,
    hashed_password: Optional[str] = None, google_id: Optional[str] = None,
    email_verified: bool = False, full_name: Optional[str] = None,
) -> tuple[Tenant, User]:
    # Creating a tenant is the one operation that has to establish its own RLS
    # context rather than inherit one: `tenants` is policy-protected with
    # WITH CHECK (id = current_setting('app.current_tenant_id')), and at signup
    # there is no tenant yet to have been set. Because the id is generated here
    # rather than by the database, it can simply be minted first and the context
    # set to it — so the INSERT satisfies its own policy, and the User INSERT
    # that follows satisfies `users`' policy for the same tenant.
    #
    # This is deliberately NOT solved with a permissive INSERT policy on
    # tenants, nor by running signup as the privileged role: either would carve
    # a genuine hole (any session could then mint rows for any tenant id) to
    # avoid what turns out to be a two-line ordering change.
    tenant_id = str(uuid.uuid4())
    async with async_tenant_context(tenant_id), AsyncSessionLocal() as db:
        tenant = Tenant(
            id=tenant_id, name=tenant_name,
            slug=slugify(tenant_name) + "-" + str(uuid.uuid4())[:6],
            created_at=utcnow(),
        )
        db.add(tenant)
        await db.flush()
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant.id, email=email,
            hashed_password=hashed_password, google_id=google_id,
            email_verified=email_verified, full_name=full_name or email.split("@")[0],
            role="owner", created_at=utcnow(),
            mfa_required_since=utcnow(),   # Item #13: owners must enrol within the grace period
        )
        db.add(user)
        # Wunomo Projects Phase 0 promised "AXIOM becomes row one per
        # tenant" — true for every tenant that existed when that phase's
        # backfill migration ran, but never wired for tenants created
        # AFTER it, until now. Without this, every tenant signing up
        # since Phase 0 shipped has zero agent_instances rows, which
        # makes Phase 1's scope enforcement (agent_scope_denied_tool_calls,
        # task_executor's per-step scope check) silently inert for them —
        # not a regression (nothing enforced scope before either), but it
        # means the new fail-closed boundary doesn't actually apply to any
        # new signup. No agent_sources rows are created here — a brand
        # new tenant has no data sources yet either, so there is nothing
        # to grant; scope starts genuinely empty and fills in as the
        # tenant connects real sources (see services/agent_scope.py's own
        # docstring on why new sources aren't auto-granted).
        from services.llm_service import SUPPORTED_MODEL_OVERRIDES
        agent = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=tenant.id, name="AXIOM",
            employee_type=AgentEmployeeType.DATAOPS, personality=PersonalityMode.ENGINEER,
            operation_mode=OperationMode.ASSISTED, model=SUPPORTED_MODEL_OVERRIDES[0],
            status=AgentInstanceStatus.ACTIVE, created_at=utcnow(), updated_at=utcnow(),
        )
        db.add(agent)
        await db.commit()
        await db.refresh(tenant)
        await db.refresh(user)

    # After commit, own session (see _provision_sso_user's comment on why
    # this isn't atomic with the rows above, and why that's accepted here).
    from modules.governance.audit_trail import AuditTrail
    await AuditTrail(tenant.id).log_action(
        actor=email, action="user.registered",
        resource_type="user", resource_id=user.id,
        payload={"auth_method": auth_method, "tenant_id": tenant.id},
    )
    return tenant, user


async def find_existing_tenants_for_email(email: str, active_only: bool = False) -> list[dict]:
    """Non-blocking signup nudge (Phase 3, approved): informs the client an
    email already has a workspace elsewhere, without blocking registration.
    active_only=True (item 1's workspace-switcher list) additionally
    requires User.is_active, so a deactivated/removed membership never
    shows up as a valid switch target -- the signup-nudge caller leaves
    this False, unchanged from its original behavior."""
    async with AsyncSessionLocal() as db:
        query = select(User).where(User.email == email)
        if active_only:
            query = query.where(User.is_active.is_(True))
        r = await db.execute(query)
        users = r.scalars().all()
        if not users:
            return []
        # Deliberately cross-tenant: the whole point is to surface workspaces
        # belonging to OTHER tenants, and this runs before (or independently of)
        # any tenant context. `tenants` is policy-scoped by id, so a direct
        # select here returns at most the caller's own row. Read through
        # tenant_registry instead — the same view the Celery sweepers use, which
        # runs with its owner's privileges and exposes only id/name/is_active,
        # never settings (webhook URLs, alert emails) or plan.
        from sqlalchemy import text as _text
        tenant_ids = [u.tenant_id for u in users]
        tr = await db.execute(
            _text("SELECT id, name FROM tenant_registry WHERE id = ANY(:ids)"),
            {"ids": tenant_ids},
        )
        return [{"tenant_id": row[0], "tenant_name": row[1]} for row in tr.fetchall()]


class WorkspaceSwitchRateLimited(Exception):
    """Raised, not returned, so the route can't accidentally treat a rate
    limit the same as a 403-no-access - they need different status codes
    and different messages."""


async def switch_workspace(
    email: str, from_tenant_id: str, target_tenant_id: str, ip: Optional[str] = None,
) -> Optional[dict]:
    """Item 1: re-issues a fresh token for a tenant the caller already has
    an active account in -- no password re-entry required, since the
    caller is already authenticated (get_current_user already proved
    identity for this request) and is only re-selecting among tenants
    that same proven email already has a real membership in, same trust
    boundary as picking among choose_workspace's options during login.

    The authorization check is the whole security of this endpoint, so it
    is stated plainly: `target_tenant_id` comes from the request body (an
    arbitrary tenant id the caller could type), but `email` comes from
    get_current_user()'s JWT-decoded, freshly is_active/role-checked
    identity -- never from the request. The query below only ever
    succeeds if THAT authenticated email has a real, currently-active
    User row in the target tenant; there is no code path that trusts the
    caller's own claim about who they are or what they're allowed to
    reach. Returns None (-> the route 403s) if it doesn't.

    Rate-limited (per email and per IP, item 1 follow-up) using the same
    real Redis mechanism email-code login already uses - raises rather
    than returning, so a 429 can't be confused with the 403 no-access case.
    Writes two AuditLog entries on success, one per tenant side of the
    switch, so each tenant's own Audit Log independently shows a member
    switching away vs. a member switching in."""
    if ip and not await _check_and_increment(
        f"wsswitch:ip:{ip}", MAX_WORKSPACE_SWITCHES_PER_IP_PER_HOUR, 3600,
    ):
        raise WorkspaceSwitchRateLimited()
    if not await _check_and_increment(
        f"wsswitch:email:{email}", MAX_WORKSPACE_SWITCHES_PER_EMAIL_PER_HOUR, 3600,
    ):
        raise WorkspaceSwitchRateLimited()

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(
            User.email == email, User.tenant_id == target_tenant_id, User.is_active.is_(True),
        ))
        user = r.scalars().first()
        if user is None:
            return None
        # The caller proved identity for the CURRENT tenant's account; the
        # target tenant's account is a separate row that may have MFA
        # enabled independently, so it gets the same second-factor gate.
        session = await establish_session(user, "switch_workspace")
        if session["status"] == "mfa_required":
            return session
        token = session["token"]

    from modules.governance.audit_trail import AuditTrail
    await AuditTrail(from_tenant_id).log_action(
        actor=email, action="workspace.switched_away",
        resource_type="tenant", resource_id=target_tenant_id,
        payload={"to_tenant_id": target_tenant_id},
    )
    await AuditTrail(target_tenant_id).log_action(
        actor=email, action="workspace.switched_into",
        resource_type="tenant", resource_id=from_tenant_id,
        payload={"from_tenant_id": from_tenant_id},
    )

    return {"access_token": token, "user_id": user.id, "tenant_id": user.tenant_id}


# ---------------------------------------------------------------------------
# Password login resolution — replaces the old unscoped
# `select(User).where(User.email == ...)).scalars().first()` bug. Password
# verification happens per-candidate-row (unlike email-code/Google, where
# ownership is proven once, upfront) so this has its own resolver rather than
# reusing resolve_identity() below.
# ---------------------------------------------------------------------------

async def resolve_password_login(email: str, password: str, tenant_id: Optional[str] = None) -> dict:
    async with AsyncSessionLocal() as db:
        query = select(User).where(User.email == email, User.is_active.is_(True))
        if tenant_id:
            query = query.where(User.tenant_id == tenant_id)
        r = await db.execute(query)
        candidates = r.scalars().all()

    matches = [u for u in candidates if u.hashed_password and verify_password(password, u.hashed_password)]

    if not matches:
        return {"status": "invalid"}
    if len(matches) == 1:
        return await establish_session(matches[0], "password")

    remembered = await _match_remembered(email, matches)
    if remembered:
        return await establish_session(remembered, "password")

    async with AsyncSessionLocal() as db:
        tr = await db.execute(select(Tenant).where(Tenant.id.in_([u.tenant_id for u in matches])))
        tenants = {t.id: t.name for t in tr.scalars().all()}
    return {
        "status": "choose",
        "options": [{"tenant_id": u.tenant_id, "tenant_name": tenants.get(u.tenant_id, u.tenant_id)} for u in matches],
    }


# ---------------------------------------------------------------------------
# Shared post-proof resolution for email-code and Google — both prove email
# ownership *before* this runs (a verified code; a verified ID token), so
# unlike password login this never needs to check a per-row secret, only
# resolve which tenant-account(s) the now-proven email maps to and apply the
# Phase 3 auto-link rules.
# ---------------------------------------------------------------------------

async def resolve_identity(
    email: str, auth_method: str, intended_tenant_id: Optional[str] = None,
    google_id: Optional[str] = None, provider_email_verified: bool = False,
    sso_subject: Optional[str] = None, sso_satisfies_mfa: bool = False,
    full_name: Optional[str] = None, connection_id: Optional[str] = None,
) -> dict:
    """Shared post-proof resolver for email-code, Google and (Item #14) SSO.
    SSO always arrives with intended_tenant_id -- the connection IS the
    tenant -- so it never reaches the multi-tenant "choose" branch. An SSO
    email with no account in that tenant is provisioned just-in-time
    (`viewer`; the domain guard already proved the IdP owns the domain),
    because enterprise SSO where every employee first needs an invite is
    SSO in name only.

    connection_id: passed through from sso_service.complete() (its own
    cfg["connection_id"], already confirmed to match the profile's) purely
    for the sso.user_provisioned / user.linked_sso audit payloads below --
    not used for any access decision, that already happened in complete()
    before this is called."""
    async with AsyncSessionLocal() as db:
        if intended_tenant_id:
            r = await db.execute(select(User).where(
                User.tenant_id == intended_tenant_id, User.email == email,
                User.is_active.is_(True),
            ))
            user = r.scalars().first()
            if user is None:
                if auth_method == "sso" and provider_email_verified:
                    user = await _provision_sso_user(intended_tenant_id, email, sso_subject, full_name,
                                                      connection_id=connection_id)
                    return await establish_session(user, "sso", mfa_via_idp=sso_satisfies_mfa)
                return {"status": "none"}
            return await _link_and_issue(db, user, auth_method, google_id, provider_email_verified,
                                         sso_subject=sso_subject, sso_satisfies_mfa=sso_satisfies_mfa,
                                         connection_id=connection_id)

        r = await db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
        users = r.scalars().all()
        if not users:
            return {"status": "none"}
        if len(users) == 1:
            return await _link_and_issue(db, users[0], auth_method, google_id, provider_email_verified)

        remembered = await _match_remembered(email, users)
        if remembered:
            return await _link_and_issue(db, remembered, auth_method, google_id, provider_email_verified)

        tr = await db.execute(select(Tenant).where(Tenant.id.in_([u.tenant_id for u in users])))
        tenants = {t.id: t.name for t in tr.scalars().all()}
        return {
            "status": "choose",
            "options": [{"tenant_id": u.tenant_id, "tenant_name": tenants.get(u.tenant_id, u.tenant_id)} for u in users],
        }


async def _provision_sso_user(tenant_id: str, email: str, sso_subject: Optional[str],
                              full_name: Optional[str], connection_id: Optional[str] = None) -> User:
    async with tenant_session(tenant_id) as db:
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=email, hashed_password=None,
            email_verified=True, sso_subject=sso_subject,
            full_name=full_name or email.split("@")[0], role="viewer", created_at=utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    log.info("sso.user_provisioned", tenant_id=tenant_id, user_id=user.id)
    # Found 2026-09-30: this log.info line reads like an audit event (same
    # string as the action name below) but was never one -- AuditTrail.
    # log_action was never called here, so the first real browser round-trip
    # produced zero audit_logs rows. AuditTrail is @tenant_scoped, so this
    # establishes its own RLS context from tenant_id regardless of the
    # pre-auth caller having none. Called after the commit above, not before
    # -- log_action opens its own separate session/transaction (not atomic
    # with the user row), and a row describing a user whose own transaction
    # later rolled back is worse than an occasional missing row if
    # log_action itself fails (it fails closed on nothing -- see its own
    # swallowed-exception behaviour, unchanged here, GOTCHAS.md).
    from modules.governance.audit_trail import AuditTrail
    from services.sso_service import email_domain
    await AuditTrail(tenant_id).log_action(
        actor=email, action="sso.user_provisioned",
        resource_type="user", resource_id=user.id,
        payload={"provider": "workos", "connection_id": connection_id,
                 "email_domain": email_domain(email)},
    )
    return user


def _existing_auth_methods(user: User) -> list[str]:
    """Which methods this account already had, captured BEFORE the
    mutation about to happen in _link_and_issue -- the audit payload's
    previous_auth_methods field. Derived from persistent identity columns,
    not a separately tracked list, so there is nothing to keep in sync."""
    methods = []
    if user.hashed_password:
        methods.append("password")
    if user.google_id:
        methods.append("google")
    if user.sso_subject:
        methods.append("sso")
    return methods


async def _link_and_issue(db, user: User, auth_method: str, google_id, provider_email_verified,
                          sso_subject: Optional[str] = None, sso_satisfies_mfa: bool = False,
                          connection_id: Optional[str] = None) -> dict:
    # This is the write half of the pre-auth chicken-and-egg. The caller found
    # this user by email across all tenants, which the `pre_auth_read` policy
    # permits precisely because the tenant isn't known until the user is. The
    # UPDATE below is governed by the ordinary tenant_isolation policy, though,
    # so without a context it matches zero rows and SQLAlchemy raises
    # StaleDataError ("expected to update 1 row(s); 0 were matched").
    #
    # The tenant is no longer unknown at this point — the row we just read tells
    # us. So scope the write to that tenant and leave the policy strict, rather
    # than widening pre_auth_read to cover UPDATE (which would let any session
    # modify any tenant's users).
    if (auth_method == "google" and not user.google_id) or \
       (auth_method == "email_code" and not user.email_verified) or \
       (auth_method == "sso" and user.sso_subject != sso_subject):
        await apply_tenant_to_session(db, user.tenant_id)

    # Linking a new external identity onto an EXISTING account is an
    # account-takeover vector (found 2026-09-30, same pass as
    # sso.user_provisioned) -- captured before any of the three branches
    # below mutate the row, so the payload shows what the account could
    # already authenticate with before this link, never token/id material.
    # auto_linked is always True: nothing in this codebase asks the human
    # to confirm a link first, resolve_identity()'s whole point is that a
    # provider-proven email match links automatically.
    previous_auth_methods = _existing_auth_methods(user)

    if auth_method == "google" and not user.google_id:
        if not provider_email_verified:
            return {"status": "blocked_unverified"}
        user.google_id = google_id
        user.email_verified = True
        db.add(user)
        await db.commit()
        from modules.governance.audit_trail import AuditTrail
        await AuditTrail(user.tenant_id).log_action(
            actor=user.email, action="user.linked_google",
            resource_type="user", resource_id=user.id,
            payload={"provider": "google", "previous_auth_methods": previous_auth_methods,
                     "email_verified_source": "google", "auto_linked": True},
        )
    elif auth_method == "email_code" and not user.email_verified:
        user.email_verified = True
        db.add(user)
        await db.commit()
        from modules.governance.audit_trail import AuditTrail
        await AuditTrail(user.tenant_id).log_action(
            actor=user.email, action="user.linked_email_code",
            resource_type="user", resource_id=user.id,
            payload={"provider": "email_code", "previous_auth_methods": previous_auth_methods,
                     "email_verified_source": "email code", "auto_linked": True},
        )
    elif auth_method == "sso":
        # The SSO counterpart of Google's email_verified rule: the IdP is
        # believed only for the domain the tenant configured, and
        # sso_service.complete() passes provider_email_verified=True only
        # when the asserted email is in that domain.
        if not provider_email_verified:
            return {"status": "blocked_unverified"}
        if user.sso_subject != sso_subject:
            user.sso_subject = sso_subject
            user.email_verified = True
            db.add(user)
            await db.commit()
            from modules.governance.audit_trail import AuditTrail
            await AuditTrail(user.tenant_id).log_action(
                actor=user.email, action="user.linked_sso",
                resource_type="user", resource_id=user.id,
                payload={"provider": "workos", "connection_id": connection_id,
                         "previous_auth_methods": previous_auth_methods,
                         "email_verified_source": "tenant verified domain", "auto_linked": True},
            )
        return await establish_session(user, "sso", mfa_via_idp=sso_satisfies_mfa)

    return await establish_session(user, auth_method)


# ---------------------------------------------------------------------------
# Pending-identity resolution token — closes a real gap: when resolve_identity()
# returns "choose" for email-code or Google, the proof that got us there (the
# email code, Google's authorization code) is already single-use and consumed
# by that point, so the client can't just resubmit the same proof a second
# time with a tenant_id the way password login can (password verification is
# stateless and safe to repeat). Instead, stash the already-proven identity
# server-side under a short-lived, single-use random token and let the client
# finalize the tenant choice against that token via resolve_pending_identity()
# (wired to POST /auth/resolve-workspace). Not needed for password login's own
# "choose" path, which resubmits the real password and needs nothing extra.
# ---------------------------------------------------------------------------

PENDING_IDENTITY_TTL_SECONDS = 300


async def store_pending_identity(
    email: str, auth_method: str, google_id: Optional[str] = None,
    provider_email_verified: bool = False,
) -> str:
    token = secrets.token_urlsafe(24)
    payload = json.dumps({
        "email": email, "auth_method": auth_method,
        "google_id": google_id, "provider_email_verified": provider_email_verified,
    })
    await _redis().set(f"pending_identity:{token}", payload, ex=PENDING_IDENTITY_TTL_SECONDS)
    return token


async def resolve_pending_identity(token: str, tenant_id: str) -> dict:
    key = f"pending_identity:{token}"
    raw = await _redis().get(key)
    if not raw:
        return {"status": "invalid"}
    await _redis().delete(key)
    data = json.loads(raw)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(
            User.tenant_id == tenant_id, User.email == data["email"],
        ))
        user = r.scalars().first()
        if user is None:
            return {"status": "invalid"}
        return await _link_and_issue(
            db, user, data["auth_method"], data.get("google_id"), data.get("provider_email_verified", False),
        )


# ---------------------------------------------------------------------------
# Email-code: generation, hashing, Resend delivery, rate limiting
# ---------------------------------------------------------------------------

def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def _check_and_increment(key: str, limit: int, window_seconds: int) -> bool:
    count = await _redis().incr(key)
    if count == 1:
        await _redis().expire(key, window_seconds)
    return count <= limit


async def check_email_code_request_allowed(email: str, ip: Optional[str]) -> bool:
    """Keyed by the raw submitted email string, independent of whether it
    resolves to a real account, so a non-existent email rate-limits/locks out
    exactly like a real one under the same request pattern — no enumeration
    leak via differing rate-limit behavior."""
    if await _redis().exists(f"otp:lockout:{email}"):
        return False
    if await _redis().exists(f"otp:cooldown:{email}"):
        return False
    if ip and not await _check_and_increment(f"otp:ip:{ip}", MAX_REQUESTS_PER_IP_PER_HOUR, 3600):
        return False
    if not await _check_and_increment(f"otp:hourly:{email}", MAX_REQUESTS_PER_EMAIL_PER_HOUR, 3600):
        return False
    await _redis().set(f"otp:cooldown:{email}", "1", ex=RESEND_COOLDOWN_SECONDS)
    return True


async def record_exhausted_code(email: str) -> None:
    key = f"otp:exhausted_streak:{email}"
    streak = await _redis().incr(key)
    await _redis().expire(key, 3600)
    if streak >= CONSECUTIVE_EXHAUSTIONS_FOR_LOCKOUT:
        await _redis().set(f"otp:lockout:{email}", "1", ex=LOCKOUT_MINUTES * 60)


async def clear_exhausted_streak(email: str) -> None:
    await _redis().delete(f"otp:exhausted_streak:{email}")


async def send_login_code(email: str, intended_tenant_id: Optional[str], request_ip: Optional[str]) -> Optional[str]:
    """Generates, stores, and emails a code. Returns the Resend message id (or
    None if Resend isn't configured) — callers shouldn't need the raw code."""
    code = _generate_code()
    async with AsyncSessionLocal() as db:
        db.add(EmailLoginCode(
            id=str(uuid.uuid4()), email=email, code_hash=_hash_code(code),
            intended_tenant_id=intended_tenant_id,
            expires_at=utcnow() + timedelta(minutes=CODE_TTL_MINUTES),
            attempts_used=0, request_ip=request_ip,
        ))
        await db.commit()
    return await _send_code_email(email, code)


async def _send_code_email(email: str, code: str) -> Optional[str]:
    """Never raises — a Resend failure (misconfiguration, sandbox
    restriction, outage) must not surface as a 500, and must not distinguish
    its response from the generic "code sent" path (enumeration safety: the
    request endpoint always returns the same response regardless of whether
    delivery actually succeeded). Failures are logged loudly instead, since
    that's the only place this is now visible."""
    if not settings.RESEND_API_KEY:
        log.warning("resend_not_configured")
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [email],
                    "subject": f"Your AXIOM sign-in code: {code}",
                    "text": f"Your sign-in code is {code}. It expires in {CODE_TTL_MINUTES} minutes.",
                },
            )
            r.raise_for_status()
            return r.json().get("id")
    except httpx.HTTPError as exc:
        log.error("email_code_send_failed", email=email, error=str(exc))
        return None


async def verify_login_code(email: str, code: str) -> dict:
    """Returns {"status": "invalid"} | {"status": "ok", "intended_tenant_id": ...}.
    Single-use: marks the code consumed on any successful match."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(EmailLoginCode)
            .where(EmailLoginCode.email == email, EmailLoginCode.consumed_at.is_(None))
            .order_by(EmailLoginCode.created_at.desc())
            .limit(1)
        )
        record = r.scalars().first()

        if record is None or record.expires_at < utcnow() or record.attempts_used >= MAX_VERIFY_ATTEMPTS:
            return {"status": "invalid"}

        if _hash_code(code) != record.code_hash:
            record.attempts_used += 1
            exhausted = record.attempts_used >= MAX_VERIFY_ATTEMPTS
            if exhausted:
                record.consumed_at = utcnow()
            db.add(record)
            await db.commit()
            if exhausted:
                await record_exhausted_code(email)
            return {"status": "invalid"}

        record.consumed_at = utcnow()
        db.add(record)
        await db.commit()

    await clear_exhausted_streak(email)
    return {"status": "ok", "intended_tenant_id": record.intended_tenant_id}


# ---------------------------------------------------------------------------
# Google OAuth — authorization URL generation (with CSRF state, same
# single-use/TTL pattern as email-code), code exchange, ID token
# verification.
# ---------------------------------------------------------------------------

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
OAUTH_STATE_TTL_SECONDS = 600


async def get_google_authorize_url() -> dict:
    state = secrets.token_urlsafe(24)
    await _redis().set(f"oauth_state:google:{state}", "1", ex=OAUTH_STATE_TTL_SECONDS)
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return {"url": f"{GOOGLE_AUTH_ENDPOINT}?{httpx.QueryParams(params)}", "state": state}


async def consume_oauth_state(state: str) -> bool:
    """Single-use CSRF check — same pattern as email-code's single-use
    consumed_at marker, just Redis-backed since there's no other persistent
    record needed for this short-lived value."""
    key = f"oauth_state:google:{state}"
    deleted = await _redis().delete(key)
    return deleted > 0


async def exchange_google_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(GOOGLE_TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        r.raise_for_status()
        return r.json()


def _verify_google_id_token_sync(id_token_str: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    # verify_oauth2_token() defaults to clock_skew_in_seconds=0 — any drift
    # between this server's clock and Google's (common in Docker/WSL2 dev
    # environments after host sleep; possible in production too without
    # perfect NTP sync) fails real, valid tokens with "Token used too early".
    # A small tolerance is standard JWT practice, not a security weakening.
    return google_id_token.verify_oauth2_token(
        id_token_str, google_requests.Request(), audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        clock_skew_in_seconds=10,
    )


async def verify_google_id_token(id_token_str: str) -> dict:
    """verify_oauth2_token() is synchronous (blocking cert fetch/verify) —
    run off the event loop rather than block it."""
    return await asyncio.to_thread(_verify_google_id_token_sync, id_token_str)
