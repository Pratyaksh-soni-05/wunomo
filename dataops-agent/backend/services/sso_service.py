"""Enterprise SSO through WorkOS (Security Master Ranking Item #14).

Shape: a third copy of the Google OAuth flow, deliberately.

    POST /auth/sso/start {email}
        -> email domain -> sso_domains (pre-auth index) -> tenant + connection
        -> single-use Redis state -> WorkOS authorization URL
    POST /auth/sso/callback {code, state}
        -> consume state -> WorkOS get_profile_and_token(code) -> verified profile
        -> domain guard -> resolve_identity(email, "sso", intended_tenant_id=...)
        -> _link_and_issue -> establish_session -> issue_token_and_remember

Everything after "verified profile" is the account-resolution logic Google
already uses (Task 1 of the item measured it and found it reusable as-is),
so an SSO login gets Item #13's MFA fork and Item #4's epoch from the same
one place every other login does. No SAML is parsed here: WorkOS terminates
SAML/OIDC with the customer's IdP and hands back a profile over an
OAuth-shaped code exchange.

Enterprise SSO is TENANT-scoped where Google is user-scoped: an
organisation configures its IdP for its workspace, and its users are
matched by email domain. So the tenant is known before the IdP is ever
contacted, `resolve_identity` is called with intended_tenant_id, and the
"choose workspace" branch never applies.

THE DOMAIN GUARD -- the SSO equivalent of Google's email_verified check.
Google's auto-link (attach a Google identity to an existing password
account) is allowed only when Google asserts the email is verified. For
SSO the assertion comes from the customer's IdP, which is authoritative
for ITS domain and no other; so an SSO login auto-links / logs in only
when the asserted email's domain equals the domain configured on the
tenant's connection. Anything else is refused, whatever the IdP claims --
an IdP that asserts ceo@othercompany.com must not obtain that account.

MFA COMPOSITION (decided): Option A, strict, by default -- SSO is a first
factor like any other, and an account with mfa_enabled still completes
Wunomo TOTP. Option B -- `satisfies_mfa` on the tenant's SSO config -- is
an explicit, audited, OWNER-only opt-in: SSO-authenticated sessions then
skip Wunomo TOTP and carry a signed `mfa_via_idp` claim that also
satisfies the owner/admin mandate for that session. The weakening is
visible on the Security tab and in the audit log, so it is a decision the
customer made, never our default.

SSO configuration lives in Tenant.settings["sso"] (one source of truth,
edited through settings_service like every other tenant setting).
sso_domains is a derived index written by the same code path -- not a
second list anyone maintains by hand.
"""

import asyncio
import secrets
from datetime import datetime
from typing import Optional

import structlog
from redis import asyncio as aioredis
from sqlalchemy import select, delete

from config import settings
from database import AsyncSessionLocal
from models.all_models import SsoDomain, Tenant
from services.tenant_context import tenant_session

log = structlog.get_logger()

STATE_TTL_SECONDS = 600
SSO_CONFIG_KEYS = ("connection_id", "email_domain", "enabled", "satisfies_mfa")

_redis_client: Optional[aioredis.Redis] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _redis() -> aioredis.Redis:
    global _redis_client, _redis_loop
    loop = asyncio.get_event_loop()
    if _redis_client is None or _redis_loop is not loop:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis_client


def is_configured() -> bool:
    return bool(settings.WORKOS_API_KEY and settings.WORKOS_CLIENT_ID)


WORKOS_AUTHORIZE_URL = "https://api.workos.com/sso/authorize"
WORKOS_TOKEN_URL = "https://api.workos.com/sso/token"


def authorization_url(connection_id: str, state: str, login_hint: str) -> str:
    """WorkOS's SSO authorize endpoint. Plain httpx rather than the workos
    SDK: the SDK pins cryptography~=50 and httpx~=0.28 against this repo's
    load-bearing cryptography==49.0.0 (Item #1) and httpx==0.27.2 (test
    client + request spies); two REST calls are not worth moving those."""
    import httpx
    params = {"client_id": settings.WORKOS_CLIENT_ID, "connection": connection_id,
              "redirect_uri": settings.SSO_REDIRECT_URI, "response_type": "code",
              "state": state, "login_hint": login_hint}
    return f"{WORKOS_AUTHORIZE_URL}?{httpx.QueryParams(params)}"


def email_domain(email: str) -> str:
    return (email or "").rsplit("@", 1)[-1].strip().lower()


def normalise_config(raw: dict) -> dict:
    """Validate and shape a tenant's SSO config. Raises ValueError with a
    user-facing message."""
    if not isinstance(raw, dict):
        raise ValueError("sso must be an object")
    unknown = set(raw) - set(SSO_CONFIG_KEYS)
    if unknown:
        raise ValueError(f"Unknown sso keys: {sorted(unknown)}")
    connection_id = str(raw.get("connection_id") or "").strip()
    domain = str(raw.get("email_domain") or "").strip().lower().lstrip("@")
    enabled = bool(raw.get("enabled", False))
    satisfies_mfa = bool(raw.get("satisfies_mfa", False))
    if enabled:
        if not connection_id.startswith("conn_"):
            raise ValueError("connection_id must be a WorkOS connection id (conn_...)")
        if "." not in domain or "@" in domain or "/" in domain or " " in domain:
            raise ValueError("email_domain must be a bare domain such as acme.com")
    return {"connection_id": connection_id, "email_domain": domain,
            "enabled": enabled, "satisfies_mfa": satisfies_mfa}


# ── Config: Tenant.settings["sso"] + the derived sso_domains index ───────────

async def get_config(tenant_id: str) -> dict:
    async with tenant_session(tenant_id) as db:
        t = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    cfg = ((t.settings or {}) if t else {}).get("sso") or {}
    return {"connection_id": cfg.get("connection_id", ""), "email_domain": cfg.get("email_domain", ""),
            "enabled": bool(cfg.get("enabled", False)), "satisfies_mfa": bool(cfg.get("satisfies_mfa", False))}


async def set_config(tenant_id: str, raw: dict, *, actor: str, actor_role: str) -> dict:
    """Write Tenant.settings["sso"] and rewrite the tenant's sso_domains rows
    in the same transaction. `satisfies_mfa` may only be CHANGED by an
    owner -- it weakens the account guarantee for every user in the
    tenant, and it is audited as its own action so the decision is visible."""
    new = normalise_config(raw)
    async with tenant_session(tenant_id) as db:
        t = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if t is None:
            raise ValueError("Tenant not found")
        current = dict((t.settings or {}).get("sso") or {})
        prev_trust = bool(current.get("satisfies_mfa", False))
        if new["satisfies_mfa"] != prev_trust and actor_role != "owner":
            raise PermissionError("Only an owner can change whether the IdP's MFA is trusted.")
        merged = dict(t.settings or {})
        merged["sso"] = new
        t.settings = merged
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(t, "settings")

        # Derived index: exactly one row per (domain -> tenant) while enabled.
        await db.execute(delete(SsoDomain).where(SsoDomain.tenant_id == tenant_id))
        if new["enabled"]:
            taken = (await db.execute(select(SsoDomain).where(
                SsoDomain.email_domain == new["email_domain"]))).scalar_one_or_none()
            if taken is not None and taken.tenant_id != tenant_id:
                raise ValueError(f"{new['email_domain']} is already claimed by another workspace")
            db.add(SsoDomain(email_domain=new["email_domain"], tenant_id=tenant_id,
                             connection_id=new["connection_id"], updated_at=datetime.utcnow()))
        await db.commit()

    from modules.governance.audit_trail import AuditTrail
    await AuditTrail(tenant_id).log_action(
        actor=actor, action="sso.config_updated", resource_type="tenant", resource_id=tenant_id,
        payload={k: new[k] for k in ("connection_id", "email_domain", "enabled")})
    if new["satisfies_mfa"] != prev_trust:
        await AuditTrail(tenant_id).log_action(
            actor=actor, action="sso.mfa_trust_changed", resource_type="tenant", resource_id=tenant_id,
            payload={"satisfies_mfa": new["satisfies_mfa"],
                     "meaning": ("SSO logins now skip Wunomo TOTP; the IdP's MFA is trusted"
                                 if new["satisfies_mfa"] else
                                 "SSO logins now require Wunomo TOTP again")})
    log.info("sso.config_updated", tenant_id=tenant_id, enabled=new["enabled"],
             satisfies_mfa=new["satisfies_mfa"])
    return new


async def lookup_by_email(email: str) -> Optional[dict]:
    """Pre-auth: which tenant (if any) owns SSO for this email's domain.
    Reads sso_domains under its pre_auth_read policy; no tenant context."""
    domain = email_domain(email)
    if not domain:
        return None
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(SsoDomain).where(
            SsoDomain.email_domain == domain))).scalar_one_or_none()
    if row is None:
        return None
    cfg = await get_config(row.tenant_id)
    if not cfg["enabled"] or cfg["connection_id"] != row.connection_id:
        return None
    return {"tenant_id": row.tenant_id, **cfg}


# ── The flow ─────────────────────────────────────────────────────────────────

async def start(email: str) -> dict:
    if not is_configured():
        return {"error": "SSO is not configured on this deployment", "code": "not_configured"}
    found = await lookup_by_email(email)
    if found is None:
        return {"error": "Single sign-on is not set up for this email domain", "code": "no_sso"}
    state = secrets.token_urlsafe(24)
    await _redis().set(f"oauth_state:sso:{state}", found["tenant_id"], ex=STATE_TTL_SECONDS)
    url = authorization_url(found["connection_id"], state, email)
    # Pre-auth response: the URL and the state only. The tenant id is
    # deliberately NOT returned -- an unauthenticated caller already learns
    # "this domain has SSO here" from the 200/404 split (inherent to
    # email-domain SSO discovery, and rate limited); it must not also learn
    # the workspace's identifier.
    return {"url": url, "state": state}


async def consume_state(state: str) -> Optional[str]:
    """Single-use: returns the tenant_id the state was minted for, or None."""
    key = f"oauth_state:sso:{state}"
    tenant_id = await _redis().get(key)
    if tenant_id:
        await _redis().delete(key)
    return tenant_id


async def fetch_profile(code: str) -> dict:
    """WorkOS code exchange (POST /sso/token). Returns the fields we act on,
    nothing else. The API key is the client_secret; it never leaves the
    server, and the code is single-use on WorkOS's side."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(WORKOS_TOKEN_URL, data={
            "client_id": settings.WORKOS_CLIENT_ID, "client_secret": settings.WORKOS_API_KEY,
            "grant_type": "authorization_code", "code": code,
        })
        r.raise_for_status()
        p = r.json().get("profile") or {}
    return {"id": p.get("id"), "email": (p.get("email") or "").strip().lower(),
            "connection_id": p.get("connection_id"), "organization_id": p.get("organization_id"),
            "first_name": p.get("first_name"), "last_name": p.get("last_name"), "idp_id": p.get("idp_id")}


async def complete(code: str, state: str) -> dict:
    """Callback: state -> tenant, profile -> domain guard -> account resolution."""
    tenant_id = await consume_state(state)
    if not tenant_id:
        return {"status": "invalid_state"}
    cfg = await get_config(tenant_id)
    if not cfg["enabled"]:
        return {"status": "disabled"}
    try:
        profile = await fetch_profile(code)
    except Exception as exc:
        log.error("sso.exchange_failed", error=str(exc), error_type=type(exc).__name__)
        return {"status": "exchange_failed"}

    # A profile from a different connection than the tenant configured would
    # mean someone replayed a code minted for another org's IdP.
    if profile["connection_id"] != cfg["connection_id"]:
        log.warning("sso.connection_mismatch", tenant_id=tenant_id, got=profile["connection_id"])
        return {"status": "connection_mismatch"}

    domain_ok = email_domain(profile["email"]) == cfg["email_domain"]
    if not domain_ok:
        log.warning("sso.domain_mismatch", tenant_id=tenant_id, domain=email_domain(profile["email"]))
        return {"status": "domain_mismatch", "email": profile["email"]}

    from services.auth_service import resolve_identity
    identity = await resolve_identity(
        profile["email"], "sso", intended_tenant_id=tenant_id,
        sso_subject=profile["id"], provider_email_verified=domain_ok,
        sso_satisfies_mfa=cfg["satisfies_mfa"],
        full_name=" ".join(x for x in (profile["first_name"], profile["last_name"]) if x) or None,
    )
    identity["tenant_id"] = identity.get("tenant_id", tenant_id)
    identity["profile_email"] = profile["email"]
    return identity
