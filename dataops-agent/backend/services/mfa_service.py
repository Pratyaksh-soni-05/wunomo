"""TOTP multi-factor authentication (Security Master Ranking Item #13).

What lives where, and why:

  * The ACTIVE secret lives on users.mfa_secret through EncryptedJSON -- the
    Fernet column type Item #1 built for source credentials. A TOTP secret
    is as sensitive as a password (anyone who reads it mints valid codes
    forever), so it gets the same at-rest treatment, same key, same
    decorator, no second encryption path to get wrong.
  * The PENDING secret -- generated at setup, not yet proven to work -- lives
    only in Redis, Fernet-encrypted, for ten minutes. It never touches the
    users row, so a user who scans a QR and walks away is not enrolled with
    a secret they never confirmed. mfa_secret set <=> mfa_enabled.
  * Backup codes are stored as keyed HMAC-SHA256 digests (key: the same
    CREDENTIAL_ENCRYPTION_KEY), never plaintext. bcrypt would be the choice
    for user-chosen secrets; these are 50-bit random codes, so stretching
    adds nothing and a keyed fast hash means a database dump alone can
    neither verify nor forge one. Each is removed on use: single-use by
    construction, not by a flag.
  * The login CHALLENGE (password/Google/email-code proved, TOTP not yet)
    is a short-lived single-use Redis token with its own attempt counter,
    the same shape as the pending-identity token auth_service already uses.

Composition with Item #4 (revocation): enabling, disabling and regenerating
codes each bump the user's token epoch -- a change to the account's
second factor is exactly the moment every other session should stop being
trusted -- and the endpoint hands the current client a fresh token so it
is not logged out by its own action. A backup-code LOGIN does not bump:
it is a successful login by the account holder, and bumping would only
log out their other legitimate devices while doing nothing to an attacker
who now holds a fresh token anyway.

Composition with Item #3 (rate limiting): /auth/mfa/verify is in the
pre-auth per-IP bucket (10/min) like /login, AND each challenge token
allows at most MAX_CHALLENGE_ATTEMPTS wrong codes before it is destroyed
and the user must re-authenticate with their first factor. A 6-digit code
with a +/-1 step window is 3-in-a-million per guess; five guesses per
first-factor proof, ten first-factor attempts per minute per IP, closes
the brute-force surface without a bespoke limiter.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

import pyotp
import structlog
from redis import asyncio as aioredis
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models.all_models import User
from services.encryption_service import _fernet
from services.tenant_context import tenant_session

log = structlog.get_logger()

MANDATORY_ROLES = ("owner", "admin")
BACKUP_CODE_COUNT = 10
PENDING_SECRET_TTL = 600           # a QR code left unconfirmed dies in 10 minutes
CHALLENGE_TTL = 300                # second-factor prompt after first-factor proof
MAX_CHALLENGE_ATTEMPTS = 5
TOTP_VALID_WINDOW = 1              # accept the previous/next 30s step (clock skew)

_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_event_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


def utcnow() -> datetime:
    return datetime.utcnow()


# ── Role policy ──────────────────────────────────────────────────────────────

def is_mandatory_for_role(role: Optional[str]) -> bool:
    return (role or "") in MANDATORY_ROLES


def enrollment_deadline(user: User) -> Optional[datetime]:
    """When an un-enrolled owner/admin starts being refused. None if MFA is
    not mandatory for them, or already enabled."""
    if user.mfa_enabled or not is_mandatory_for_role(user.role):
        return None
    since = user.mfa_required_since or user.created_at or utcnow()
    return since + timedelta(days=settings.MFA_GRACE_DAYS)


def enrollment_overdue(role: Optional[str], mfa_enabled: bool,
                       mfa_required_since: Optional[datetime], created_at: Optional[datetime]) -> bool:
    """Row-field form of enrollment_deadline(), for get_current_user which
    selects columns rather than loading the ORM object."""
    if mfa_enabled or not is_mandatory_for_role(role):
        return False
    since = mfa_required_since or created_at or utcnow()
    return utcnow() > since + timedelta(days=settings.MFA_GRACE_DAYS)


# ── Secrets & codes ──────────────────────────────────────────────────────────

def _encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def _hash_backup_code(code: str) -> str:
    """Always over the normalised form (no dash, upper-case), so what the
    user types back -- with or without the dash, any case -- matches."""
    key = settings.CREDENTIAL_ENCRYPTION_KEY.encode()
    return hmac.new(key, _normalise_code(code).encode(), hashlib.sha256).hexdigest()


def _normalise_code(code: str) -> str:
    return (code or "").strip().replace(" ", "").replace("-", "").upper()


def generate_backup_codes() -> list[str]:
    # 10 groups of "XXXXX-XXXXX" from an unambiguous alphabet: 50 bits each.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    out = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.MFA_ISSUER)


async def _totp_ok(user_id: str, secret: str, code: str) -> bool:
    """RFC 6238 check with a replay guard: a code that already logged this
    user in cannot be used again inside its validity window, so a shoulder-
    surfed code is worthless the moment its owner has used it."""
    code = _normalise_code(code)
    if not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=TOTP_VALID_WINDOW):
        return False
    # pyotp does not tell us which step matched; lock the code itself for
    # the window's duration instead, which is the property that matters.
    guard = f"mfa:used:{user_id}:{code}"
    if not await _redis().set(guard, "1", ex=30 * (2 * TOTP_VALID_WINDOW + 1), nx=True):
        return False
    return True


async def _load_user(user_id: str, tenant_id: str) -> Optional[User]:
    async with tenant_session(tenant_id) as db:
        return (await db.execute(select(User).where(
            User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()


# ── Setup flow ───────────────────────────────────────────────────────────────

async def start_setup(user_id: str, tenant_id: str) -> dict:
    user = await _load_user(user_id, tenant_id)
    if user is None:
        return {"error": "User not found"}
    if user.mfa_enabled:
        return {"error": "MFA is already enabled. Disable it first (a valid code is required)."}
    secret = pyotp.random_base32()
    await _redis().set(f"mfa:pending:{user_id}", _encrypt(secret), ex=PENDING_SECRET_TTL)
    return {"secret": secret, "provisioning_uri": provisioning_uri(secret, user.email),
            "expires_in": PENDING_SECRET_TTL}


async def confirm_setup(user_id: str, tenant_id: str, code: str) -> dict:
    """The only path that sets mfa_enabled. Requires a code generated from
    the pending secret, proving the authenticator actually has it."""
    enc = await _redis().get(f"mfa:pending:{user_id}")
    if not enc:
        return {"error": "No MFA setup in progress, or it expired. Start setup again."}
    secret = _decrypt(enc)
    if not await _totp_ok(user_id, secret, code):
        return {"error": "That code is not valid for the new secret. Check the time on your device and try the next code."}
    codes = generate_backup_codes()
    async with tenant_session(tenant_id) as db:
        user = (await db.execute(select(User).where(
            User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
        if user is None:
            return {"error": "User not found"}
        user.mfa_secret = {"secret": secret}
        user.mfa_enabled = True
        user.mfa_enabled_at = utcnow()
        user.mfa_backup_codes = [_hash_backup_code(c) for c in codes]
        await db.commit()
    await _redis().delete(f"mfa:pending:{user_id}")
    log.info("mfa.enabled", user_id=user_id, tenant_id=tenant_id)
    return {"enabled": True, "backup_codes": codes}


async def disable(user_id: str, tenant_id: str) -> dict:
    async with tenant_session(tenant_id) as db:
        user = (await db.execute(select(User).where(
            User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
        if user is None:
            return {"error": "User not found"}
        user.mfa_secret = None
        user.mfa_enabled = False
        user.mfa_enabled_at = None
        user.mfa_backup_codes = None
        await db.commit()
    log.info("mfa.disabled", user_id=user_id, tenant_id=tenant_id)
    return {"enabled": False}


async def regenerate_backup_codes(user_id: str, tenant_id: str) -> dict:
    codes = generate_backup_codes()
    async with tenant_session(tenant_id) as db:
        user = (await db.execute(select(User).where(
            User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
        if user is None or not user.mfa_enabled:
            return {"error": "MFA is not enabled"}
        user.mfa_backup_codes = [_hash_backup_code(c) for c in codes]
        await db.commit()
    return {"backup_codes": codes}


# ── Verification (second factor) ─────────────────────────────────────────────

async def verify_code_for_user(user_id: str, tenant_id: str, code: str) -> Optional[str]:
    """Returns "totp", "backup", or None. A backup code that matches is
    removed inside the same transaction that reads it."""
    async with tenant_session(tenant_id) as db:
        user = (await db.execute(select(User).where(
            User.id == user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
        if user is None or not user.mfa_enabled or not user.mfa_secret:
            return None
        secret = (user.mfa_secret or {}).get("secret")
        if secret and await _totp_ok(user_id, secret, code):
            return "totp"
        digest = _hash_backup_code(code)
        remaining = list(user.mfa_backup_codes or [])
        for stored in remaining:
            if hmac.compare_digest(stored, digest):
                remaining.remove(stored)
                user.mfa_backup_codes = remaining
                await db.commit()
                log.info("mfa.backup_code_used", user_id=user_id, tenant_id=tenant_id,
                         remaining=len(remaining))
                return "backup"
    return None


# ── Login challenge ──────────────────────────────────────────────────────────

async def create_challenge(user: User, auth_method: str) -> str:
    token = secrets.token_urlsafe(24)
    await _redis().set(f"mfa:challenge:{token}", json.dumps({
        "user_id": user.id, "tenant_id": user.tenant_id, "auth_method": auth_method,
        "attempts": 0,
    }), ex=CHALLENGE_TTL)
    return token


async def resolve_challenge(token: str, code: str) -> dict:
    """Consume the challenge on success. On a wrong code the attempt counter
    is bumped; after MAX_CHALLENGE_ATTEMPTS the challenge is destroyed so a
    guesser has to redo the first factor (and meet its rate limit) to get
    five more tries."""
    key = f"mfa:challenge:{token}"
    raw = await _redis().get(key)
    if not raw:
        return {"status": "invalid"}
    data = json.loads(raw)
    method = await verify_code_for_user(data["user_id"], data["tenant_id"], code)
    if method is None:
        data["attempts"] = int(data.get("attempts", 0)) + 1
        if data["attempts"] >= MAX_CHALLENGE_ATTEMPTS:
            await _redis().delete(key)
            log.warning("mfa.challenge_exhausted", user_id=data["user_id"])
            return {"status": "exhausted"}
        ttl = await _redis().ttl(key)
        await _redis().set(key, json.dumps(data), ex=max(ttl, 1))
        return {"status": "wrong", "attempts_left": MAX_CHALLENGE_ATTEMPTS - data["attempts"]}
    await _redis().delete(key)
    return {"status": "ok", "user_id": data["user_id"], "tenant_id": data["tenant_id"],
            "auth_method": data["auth_method"], "factor": method}


async def status_for(user_id: str, tenant_id: str) -> dict:
    user = await _load_user(user_id, tenant_id)
    if user is None:
        return {"error": "User not found"}
    deadline = enrollment_deadline(user)
    return {
        "enabled": bool(user.mfa_enabled),
        "enabled_at": user.mfa_enabled_at.isoformat() if user.mfa_enabled_at else None,
        "backup_codes_remaining": len(user.mfa_backup_codes or []) if user.mfa_enabled else 0,
        "required": is_mandatory_for_role(user.role),
        "enrollment_deadline": deadline.isoformat() if deadline else None,
        "overdue": bool(deadline and utcnow() > deadline),
    }
