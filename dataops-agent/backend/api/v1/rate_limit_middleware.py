"""ASGI middleware applying per-minute rate limits to every request.

Sits in front of authentication deliberately: the point of burst protection is
to reject a flood *before* it costs a JWT decode, a database round trip and a
session, so a limiter that only runs after `get_current_user` protects the
expensive work but not the machine.

Why middleware rather than `@limiter.limit()` decorators: there are 126 routes.
Decorating each one means a newly added route ships with no limit and nobody
notices, and a reviewer has 126 places to check instead of one table. Limits are
resolved from the request path by `rate_limit.categorise()`.

Why not slowapi: its dynamic-limit callable is synchronous, and the AXIOM tier
limit needs the tenant's plan, which is not in the JWT and requires an async
database read. Everything else slowapi offers is a thin wrapper over
INCR/EXPIRE, which auth_service already does directly for the email-code
limiter — a second, differently-shaped limiter in the same codebase costs more
than it saves.

    IP ADDRESSES — READ BEFORE DEPLOYING BEHIND ANYTHING
    ----------------------------------------------------
    IP-keyed limits use `request.client.host` and deliberately do NOT trust
    `X-Forwarded-For`. That is correct today (uvicorn is exposed directly on
    8000, nothing in front of it) and becomes wrong the moment a load balancer,
    reverse proxy, ingress or CDN is introduced: every request would then carry
    the proxy's IP, collapsing every user in the world into one shared bucket
    and locking out legitimate traffic at 10 requests/minute.

    Trusting X-Forwarded-For blindly is worse — a header any client can set
    makes the IP limit trivially bypassable. The fix at that point is to trust
    it only from known proxy hops. See GOTCHAS.md.
"""

from jose import jwt
from starlette.responses import JSONResponse

from config import settings
from services.rate_limit import (
    DEFAULT_RPM_PER_TENANT, EXPENSIVE_RPM_PER_TENANT, PREAUTH_RPM_PER_IP,
    UNAUTH_BACKSTOP_RPM_PER_IP, RateLimitCategory, categorise, check_rate_limit,
    rpm_for_plan,
)


def _too_many_requests(retry_after: int) -> JSONResponse:
    """429 with Retry-After and nothing else.

    The body names the limit that was hit only in the broadest terms and never
    the configured value, the window, the remaining count, or the key — telling
    a caller "you may send 10/minute per IP" hands an attacker the exact shape
    of the control they are probing.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limited",
            "detail": "Too many requests. Please retry shortly.",
        },
        headers={"Retry-After": str(retry_after)},
    )


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        category = categorise(path)
        if category == RateLimitCategory.EXEMPT:
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers") or []
        client_ip = self._client_ip(scope)
        tenant_id = await self._tenant_from_headers(headers)

        allowed, retry_after = await self._check(category, tenant_id, client_ip)
        if not allowed:
            await _too_many_requests(retry_after)(scope, receive, send)
            return

        await self.app(scope, receive, send)

    # ── limit selection ──────────────────────────────────────────────────────

    async def _check(self, category: str, tenant_id, client_ip) -> tuple[bool, int]:
        # Pre-auth: IP-keyed, tier-independent, strictest. There is no tenant
        # yet by definition — discovering one is what these endpoints do.
        if category == RateLimitCategory.PREAUTH:
            return await check_rate_limit("preauth", client_ip, PREAUTH_RPM_PER_IP)

        # Unauthenticated traffic to any other path never reaches a tenant
        # bucket, so it needs its own backstop or it would be unlimited.
        if tenant_id is None:
            return await check_rate_limit(
                "unauth", client_ip, UNAUTH_BACKSTOP_RPM_PER_IP)

        if category == RateLimitCategory.EXPENSIVE:
            return await check_rate_limit(
                "expensive", tenant_id, EXPENSIVE_RPM_PER_TENANT)

        if category == RateLimitCategory.AXIOM:
            plan = await self._plan_for_tenant(tenant_id)
            return await check_rate_limit(
                "axiom", tenant_id, rpm_for_plan(plan))

        return await check_rate_limit("default", tenant_id, DEFAULT_RPM_PER_TENANT)

    # ── identity ─────────────────────────────────────────────────────────────

    @staticmethod
    def _client_ip(scope) -> str:
        client = scope.get("client")
        # Deliberately NOT X-Forwarded-For — see the module docstring.
        return client[0] if client else "unknown"

    @staticmethod
    async def _tenant_from_headers(raw_headers):
        """Tenant from the JWT, or None.

        Best-effort and never rejects: an absent, malformed or expired token
        simply means "no tenant", which routes the request to the IP-keyed
        backstop instead. Authentication remains entirely
        `get_current_user()`'s job — this grants nothing and refuses nothing on
        identity grounds.
        """
        for key, value in raw_headers:
            if key.lower() != b"authorization":
                continue
            try:
                scheme, _, credentials = value.decode("latin-1").partition(" ")
            except Exception:
                return None
            if scheme.lower() != "bearer" or not credentials:
                return None
            try:
                claims = jwt.decode(
                    credentials, settings.JWT_SECRET,
                    algorithms=[settings.JWT_ALGORITHM],
                )
            except Exception:
                return None
            # A revoked token must not spend its former tenant's rate-limit
            # budget. Returning None drops it onto the stricter per-IP
            # unauthenticated backstop instead, which is the correct bucket for
            # a request that is about to be rejected anyway.
            from services.token_revocation import is_revoked
            if await is_revoked(claims):
                return None

            value = claims.get("tenant_id")
            return str(value) if value else None
        return None

    @staticmethod
    async def _plan_for_tenant(tenant_id: str):
        """The tenant's plan, for the tier-aware AXIOM limit.

        Read directly rather than via `get_current_user` because this runs
        before dependency resolution — that is the whole point of doing the
        check here. Only AXIOM-category paths reach this, so the extra read is
        confined to chat/task endpoints rather than every request.

        Failure returns None, which `rpm_for_plan()` maps to the *most*
        restrictive tier: if the database is unreachable, a tenant gets throttled
        rather than handed an unlimited allowance.
        """
        try:
            from sqlalchemy import select
            from database import AsyncSessionLocal
            from models.all_models import Tenant
            from services.tenant_context import async_tenant_context

            # Scoped, because `tenants` is RLS-protected by its own id.
            async with async_tenant_context(tenant_id), AsyncSessionLocal() as db:
                r = await db.execute(select(Tenant.plan).where(Tenant.id == tenant_id))
                return r.scalar()
        except Exception:
            return None
