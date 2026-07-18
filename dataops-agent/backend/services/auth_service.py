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
from models.all_models import EmailLoginCode, Tenant, User

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


def create_token(data: dict) -> str:
    now = utcnow()
    exp = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode({**data, "iat": now, "exp": exp}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def issue_token_for_user(user: User, auth_method: str) -> str:
    return create_token({
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "role": user.role,
        "auth_method": auth_method,
    })


# ---------------------------------------------------------------------------
# Tenant creation (shared by register(), email-code, and Google — all three
# "create a new workspace" paths are otherwise identical)
# ---------------------------------------------------------------------------

async def create_new_tenant_and_user(
    *, tenant_name: str, email: str, auth_method: str,
    hashed_password: Optional[str] = None, google_id: Optional[str] = None,
    email_verified: bool = False, full_name: Optional[str] = None,
) -> tuple[Tenant, User]:
    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            id=str(uuid.uuid4()), name=tenant_name,
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
        )
        db.add(user)
        await db.commit()
        await db.refresh(tenant)
        await db.refresh(user)
        return tenant, user


async def find_existing_tenants_for_email(email: str) -> list[dict]:
    """Non-blocking signup nudge (Phase 3, approved): informs the client an
    email already has a workspace elsewhere, without blocking registration."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.email == email))
        users = r.scalars().all()
        if not users:
            return []
        tr = await db.execute(select(Tenant).where(Tenant.id.in_([u.tenant_id for u in users])))
        return [{"tenant_id": t.id, "tenant_name": t.name} for t in tr.scalars().all()]


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
        user = matches[0]
        return {
            "status": "single", "token": issue_token_for_user(user, "password"),
            "user_id": user.id, "tenant_id": user.tenant_id,
        }

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
) -> dict:
    async with AsyncSessionLocal() as db:
        if intended_tenant_id:
            r = await db.execute(select(User).where(
                User.tenant_id == intended_tenant_id, User.email == email,
            ))
            user = r.scalars().first()
            if user is None:
                return {"status": "none"}
            return await _link_and_issue(db, user, auth_method, google_id, provider_email_verified)

        r = await db.execute(select(User).where(User.email == email))
        users = r.scalars().all()
        if not users:
            return {"status": "none"}
        if len(users) == 1:
            return await _link_and_issue(db, users[0], auth_method, google_id, provider_email_verified)

        tr = await db.execute(select(Tenant).where(Tenant.id.in_([u.tenant_id for u in users])))
        tenants = {t.id: t.name for t in tr.scalars().all()}
        return {
            "status": "choose",
            "options": [{"tenant_id": u.tenant_id, "tenant_name": tenants.get(u.tenant_id, u.tenant_id)} for u in users],
        }


async def _link_and_issue(db, user: User, auth_method: str, google_id, provider_email_verified) -> dict:
    if auth_method == "google" and not user.google_id:
        if not provider_email_verified:
            return {"status": "blocked_unverified"}
        user.google_id = google_id
        user.email_verified = True
        db.add(user)
        await db.commit()
    elif auth_method == "email_code" and not user.email_verified:
        user.email_verified = True
        db.add(user)
        await db.commit()

    return {
        "status": "single", "token": issue_token_for_user(user, auth_method),
        "user_id": user.id, "tenant_id": user.tenant_id,
    }


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
