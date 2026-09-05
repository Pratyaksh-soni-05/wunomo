"""ASGI middleware establishing the per-request tenant for RLS.

Reads `tenant_id` out of the request's JWT and puts it in the ContextVar that
`database.py`'s `begin` event stamps onto every transaction.

**Deliberately a raw ASGI middleware, not `BaseHTTPMiddleware`.** Starlette runs
`BaseHTTPMiddleware`'s downstream app in a *separate anyio task*, and a
ContextVar set in the middleware does not propagate into that task — the value
would be silently absent by the time an endpoint opened a session, and every
authenticated request would read zero rows. A raw ASGI middleware runs in the
same task as the endpoint, so the ContextVar is visible where it's needed. If
anyone converts this to `@app.middleware("http")` later, tenant scoping breaks
in a way that looks like "the database is empty", with nothing pointing here.

**This is not authentication.** Decoding here is best-effort and never rejects a
request: an absent, malformed, or expired token simply leaves the tenant unset,
which fails closed (RLS returns no rows). `get_current_user()` remains the sole
authority on whether a request is allowed to proceed, and it validates the same
token properly. The two are independent on purpose — this middleware widening or
narrowing access is not a thing that can happen, because it grants nothing.
"""

from jose import jwt

from config import settings
from services.tenant_context import set_current_tenant_id, reset_current_tenant_id


class TenantContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        tenant_id = await self._tenant_from_headers(scope.get("headers") or [])
        token = set_current_tenant_id(tenant_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_tenant_id(token)

    @staticmethod
    async def _tenant_from_headers(raw_headers) -> str | None:
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
                    credentials,
                    settings.JWT_SECRET,
                    algorithms=[settings.JWT_ALGORITHM],
                )
            except Exception:
                # Expired/invalid/garbage — leave the tenant unset and let
                # get_current_user() produce the real 401. Failing closed here
                # means such a request reads nothing rather than everything.
                return None
            # A revoked token must not establish a tenant context. Without
            # this check it would still scope RLS to its tenant on the way to
            # being rejected by get_current_user — the revocation would hold
            # for authorisation but not for data scoping, which is exactly the
            # "second, un-patched validation path" this class of fix has to
            # avoid. Returning None routes the request to the unauthenticated
            # path, which reads nothing.
            from services.token_revocation import is_revoked
            if await is_revoked(claims):
                return None

            value = claims.get("tenant_id")
            return str(value) if value else None
        return None
