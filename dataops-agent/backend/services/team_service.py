"""Team invite lifecycle (Phase 15): create, send (Resend), accept, revoke.

Mirrors services/auth_service.py's established patterns deliberately:
token hashing (SHA-256, not bcrypt - TTL + single-use is the real
protection here, same reasoning as EmailLoginCode.code_hash), and
_send_code_email's "never raise on delivery failure" contract for the
Resend call (a Resend outage/misconfiguration must not 500 an invite
creation that otherwise succeeded in the DB).
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models.all_models import TeamInvite, Tenant, User
from services.auth_service import hash_password, issue_token_for_user
from services.rbac import ALL_ROLES

log = structlog.get_logger()

INVITE_TTL_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _invite_link(token: str) -> str:
    base = settings.APP_CORS_ORIGINS.split(",")[0].strip()
    return f"{base}/accept-invite?token={token}"


async def create_invite(*, tenant_id: str, email: str, role: str, invited_by_user_id: str) -> dict:
    """Returns {"error": ...} | {"invite": TeamInvite, "token": <raw token, shown once>}."""
    if role not in ALL_ROLES:
        return {"error": f"Invalid role '{role}'. Valid: {list(ALL_ROLES)}"}

    async with AsyncSessionLocal() as db:
        existing_member = await db.execute(
            select(User).where(User.tenant_id == tenant_id, User.email == email)
        )
        if existing_member.scalars().first():
            return {"error": "This email is already a member of this workspace"}

        # A fresh invite supersedes any still-pending one for the same
        # (tenant, email) - avoids stacking multiple live invite links.
        stale = await db.execute(
            select(TeamInvite).where(
                TeamInvite.tenant_id == tenant_id,
                TeamInvite.email == email,
                TeamInvite.status == "pending",
            )
        )
        for old in stale.scalars().all():
            old.status = "revoked"

        token = secrets.token_urlsafe(32)
        invite = TeamInvite(
            id=str(uuid.uuid4()), tenant_id=tenant_id, email=email, role=role,
            invited_by_user_id=invited_by_user_id, token_hash=_hash_token(token),
            status="pending", expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
            created_at=utcnow(),
        )
        db.add(invite)
        await db.commit()
        await db.refresh(invite)
        return {"invite": invite, "token": token}


async def send_invite_email(*, email: str, token: str, tenant_name: str, inviter_email: str, role: str) -> Optional[str]:
    """Never raises - a Resend failure must not undo the already-committed
    invite row; logged loudly instead, same contract as auth_service's
    _send_code_email."""
    if not settings.RESEND_API_KEY:
        log.warning("resend_not_configured")
        return None
    link = _invite_link(token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [email],
                    "subject": f"{inviter_email} invited you to join {tenant_name} on AXIOM",
                    "text": (
                        f"{inviter_email} has invited you to join {tenant_name} on AXIOM "
                        f"as {role}.\n\nAccept your invite: {link}\n\n"
                        f"This link expires in {INVITE_TTL_DAYS} days."
                    ),
                },
            )
            r.raise_for_status()
            return r.json().get("id")
    except httpx.HTTPError as exc:
        log.error("invite_email_send_failed", email=email, error=str(exc))
        return None


async def get_invite_by_token(token: str) -> Optional[dict]:
    """Public lookup (no auth) for an accept-invite UI to show who's
    inviting/what role/which workspace before the user commits."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TeamInvite).where(TeamInvite.token_hash == _hash_token(token)))
        invite = r.scalars().first()
        if not invite or invite.status != "pending" or invite.expires_at < utcnow():
            return None
        tr = await db.execute(select(Tenant).where(Tenant.id == invite.tenant_id))
        tenant = tr.scalars().first()
        return {
            "email": invite.email, "role": invite.role,
            "tenant_name": tenant.name if tenant else None,
        }


async def accept_invite(*, token: str, password: str, full_name: str) -> dict:
    """Returns {"error": ...} | a real issued-token dict, same shape as
    register()'s response. tenant_id and role come from the invite, never
    from caller input (Phase 3's locked invite-join design)."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TeamInvite).where(TeamInvite.token_hash == _hash_token(token)))
        invite = r.scalars().first()
        if not invite or invite.status != "pending" or invite.expires_at < utcnow():
            return {"error": "Invalid or expired invite"}

        already = await db.execute(
            select(User).where(User.tenant_id == invite.tenant_id, User.email == invite.email)
        )
        if already.scalars().first():
            # Don't mark the invite accepted here - it wasn't actually
            # consumed to create anything; leave it pending so a retry
            # with correct state (or an admin revoking it) still works.
            return {"error": "This email is already a member of this workspace"}

        user = User(
            id=str(uuid.uuid4()), tenant_id=invite.tenant_id, email=invite.email,
            hashed_password=hash_password(password), email_verified=False,
            full_name=full_name or invite.email.split("@")[0],
            role=invite.role, created_at=utcnow(),
        )
        db.add(user)
        invite.status = "accepted"
        invite.accepted_at = utcnow()
        await db.commit()
        await db.refresh(user)

        token_str = issue_token_for_user(user, "password")
        return {
            "access_token": token_str, "token_type": "bearer",
            "tenant_id": user.tenant_id, "user_id": user.id, "role": user.role,
        }
