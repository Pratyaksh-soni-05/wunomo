"""Request/task-scoped tenant identity, used to drive Postgres Row-Level Security.

Every tenant-scoped table carries an RLS policy of the form

    tenant_id = current_setting('app.current_tenant_id', true)

so the database itself refuses to return another tenant's rows. Something has to
put a value into that setting, per transaction. That is what this module does.

**Why a ContextVar and an engine-level event, rather than passing a tenant_id
down to each query.** There are ~160 `AsyncSessionLocal()` call sites across
this codebase. Threading an explicit argument through all of them would leave
the guarantee exactly as fragile as the manual `WHERE tenant_id = ...`
convention RLS exists to replace — one missed call site and the protection is
gone. A ContextVar read by a single `begin` event on the engine means no call
site can forget, because no call site is involved.

**Fail closed.** If nothing has set the tenant, the setting is written as the
empty string, which matches no row (`tenant_id` is NOT NULL on every scoped
table). An unscoped session therefore sees zero rows rather than every row.
`current_setting(..., true)` — the `true` is `missing_ok` — is what makes an
*unset* variable return NULL instead of raising, so the failure mode is "no
data", never "500 error".

**Scope of the setting.** `set_config(..., true)` is transaction-local, so it is
reset automatically at COMMIT/ROLLBACK and cannot leak to the next user of a
pooled connection. This is the reason the setting is applied on transaction
`begin` rather than on pool checkout: a checkout happens outside any
transaction, where `SET LOCAL`/`set_config(..., true)` has nothing to attach to
and silently does nothing.
"""

import functools
import inspect
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Optional


# None = no tenant established. Deliberately distinct from "" so callers can
# tell "never set" from "explicitly cleared", even though both fail closed.
_current_tenant_id: ContextVar[Optional[str]] = ContextVar(
    "current_tenant_id", default=None
)


def get_current_tenant_id() -> Optional[str]:
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id: Optional[str]):
    """Set the tenant for this context. Returns the token needed to reset it."""
    return _current_tenant_id.set(tenant_id)


def reset_current_tenant_id(token) -> None:
    _current_tenant_id.reset(token)


@contextmanager
def tenant_context(tenant_id: Optional[str]):
    """Sync scope guard — for Celery task bodies before the event loop starts."""
    token = _current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(token)


@asynccontextmanager
async def async_tenant_context(tenant_id: Optional[str]):
    """Async scope guard — for per-tenant iterations inside a sweeper task.

    Used by the cross-tenant Celery jobs, which legitimately need to touch many
    tenants but must do so one explicitly-scoped tenant at a time rather than
    with a blanket bypass.
    """
    token = _current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(token)


@asynccontextmanager
async def tenant_session(tenant_id: str):
    """Open an AsyncSession already inside `tenant_id`'s RLS context.

    Equivalent to nesting `async_tenant_context(...)` around
    `AsyncSessionLocal()`, as one step. Primarily used by tests, which seed rows
    directly and therefore have neither the HTTP middleware nor a Celery task
    wrapper to establish the context for them — a bare `AsyncSessionLocal()`
    there has no tenant, and RLS correctly refuses the write.

    Lives here rather than in `tests/conftest.py` because conftest is loaded by
    pytest as a plugin, not importable as a module (`import conftest` raises
    ModuleNotFoundError), and because nothing about this is test-specific.
    """
    from database import AsyncSessionLocal
    async with async_tenant_context(tenant_id):
        async with AsyncSessionLocal() as db:
            yield db


async def apply_tenant_to_session(db, tenant_id: str) -> None:
    """Stamp the tenant onto an ALREADY-OPEN session's transaction.

    `database.py`'s `begin` event covers the normal case, but it only fires when
    a transaction starts. The pre-authentication flows need something different:
    they read a row *without* a tenant (that's what the `pre_auth_read` policy
    on `users`/`team_invites` is for), learn the tenant from what they read, and
    only then write — all inside one already-open transaction. Setting the
    ContextVar at that point would be too late to trigger the event, so the
    setting is issued directly on the live session instead.

    Still `set_config(..., true)` — transaction-local, cleared at COMMIT/ROLLBACK,
    so it cannot leak to the next user of a pooled connection.
    """
    from sqlalchemy import text
    await db.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tenant_id or ""},
    )


def tenant_scoped(cls):
    """Class decorator: every async method runs in `self.tenant_id`'s RLS context.

    The module classes in `modules/*` all take `tenant_id` in `__init__` and then
    open their own sessions in each method — `ConnectorManager(tenant_id).sync()`,
    `IncidentManager(tenant_id).resolve()`, and so on. In an HTTP request the
    middleware has already set the context, so they worked; called from anywhere
    else they silently saw nothing. `IncidentManager.resolve()` returning
    "Incident … not found" for a row that exists is the shape of that bug, and
    `_create_scheduled_run` returning None when called directly is the same thing
    one layer down: correct *by convention of the caller*, not by construction.

    Applied at the class rather than per method (99 across 16 classes) so a
    newly added method is covered automatically instead of depending on someone
    remembering the decorator — the same reasoning behind putting the request
    context on the engine's `begin` event rather than at ~160 session sites.

    Nesting is harmless: ContextVar set/reset is stack-like, so an inner call
    re-setting the same tenant is a no-op in effect, and a sweeper that wraps a
    class call in its own `async_tenant_context` still wins for its own scope.
    """
    for name, attr in list(cls.__dict__.items()):
        if name.startswith("__") or not inspect.iscoroutinefunction(attr):
            continue

        def _wrap(method):
            @functools.wraps(method)
            async def inner(self, *args, **kwargs):
                tenant_id = getattr(self, "tenant_id", None)
                if not tenant_id:
                    return await method(self, *args, **kwargs)
                async with async_tenant_context(tenant_id):
                    return await method(self, *args, **kwargs)
            return inner

        setattr(cls, name, _wrap(attr))
    return cls


def with_tenant_context(fn):
    """Scope a service-layer coroutine to the `tenant_id` it was handed.

    For functions that take an explicit `tenant_id` and open their own session.
    Most are called from a request, where the middleware has already set the
    context — but not all are, and the ones that aren't fail in the worst
    possible way: RLS rejects the write, and if the caller swallows exceptions
    the data simply stops being recorded with nothing surfaced. Setting the
    context from the argument the function already has makes it correct
    regardless of who calls it, which is the same reasoning applied to the
    Celery task wrappers.

    Deliberately a no-op when `tenant_id` is falsy — some of these take it as an
    optional argument, and setting an empty context would be strictly worse than
    inheriting whatever the caller established.

    NOT for pre-authentication functions (`resolve_password_login`,
    `resolve_pending_identity`): those run before a tenant is known, read
    through the `pre_auth_read` policy on purpose, and must not be pinned to a
    single tenant. See migration b7d419e3f2a8's pre-auth block comment.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            bound = signature.bind_partial(*args, **kwargs)
            tenant_id = bound.arguments.get("tenant_id")
        except TypeError:
            tenant_id = None
        if not tenant_id:
            return await fn(*args, **kwargs)
        async with async_tenant_context(tenant_id):
            return await fn(*args, **kwargs)

    return wrapper
