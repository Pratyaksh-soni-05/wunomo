"""Platform API keys (Phase 16) - CRUD only. See models/all_models.py's
ApiKey docstring: nothing in this app accepts one of these as a request
credential yet - that's a deliberately separate, larger feature (tracked
in CLAUDE.md's Not-yet-built), not silently implied by this module.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import ApiKey

KEY_PREFIX = "axm_live_"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _mask(key: ApiKey) -> dict:
    return {
        "id": key.id, "name": key.name, "key_prefix": key.key_prefix,
        "created_by_user_id": key.created_by_user_id,
        "last_used_at": key.last_used_at, "revoked_at": key.revoked_at,
        "created_at": key.created_at, "is_revoked": key.revoked_at is not None,
    }


async def create_api_key(tenant_id: str, name: str, created_by_user_id: str) -> dict:
    if not (name or "").strip():
        return {"error": "Key name cannot be empty"}

    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
    display_prefix = raw_key[:len(KEY_PREFIX) + 8]

    async with AsyncSessionLocal() as db:
        key = ApiKey(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name=name.strip(),
            key_hash=_hash_key(raw_key), key_prefix=display_prefix,
            created_by_user_id=created_by_user_id, created_at=utcnow(),
        )
        db.add(key)
        await db.commit()
        await db.refresh(key)

    # raw_key is shown exactly once - only this response ever carries it,
    # matching TeamInvite's create-response pattern (Phase 15).
    return {**_mask(key), "raw_key": raw_key}


async def list_api_keys(tenant_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.desc())
        )
        return [_mask(k) for k in r.scalars().all()]


async def revoke_api_key(tenant_id: str, key_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
        )
        key = r.scalars().first()
        if not key:
            return {"error": "API key not found"}
        if key.revoked_at is None:  # idempotent - a retried revoke call is a no-op, not an error
            key.revoked_at = utcnow()
            await db.commit()
            await db.refresh(key)
        return _mask(key)
