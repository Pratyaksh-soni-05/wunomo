from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from config import settings


# NullPool in test env prevents asyncpg connections leaking across event loop boundaries
_pool_kwargs = (
    {"poolclass": NullPool}
    if settings.APP_ENV == "test"
    else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    **_pool_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@event.listens_for(engine.sync_engine, "begin")
def _apply_tenant_rls_context(conn):
    """Stamp the current tenant onto every transaction, for RLS to read.

    Registered on the engine rather than at each `AsyncSessionLocal()` call site
    (there are ~160) so that no query path can be written that forgets it — see
    services/tenant_context.py for the full reasoning.

    `set_config(..., true)` is transaction-local: Postgres resets it at
    COMMIT/ROLLBACK, so a pooled connection cannot carry one request's tenant
    into the next request's. This runs on `begin` and not on pool checkout
    precisely because a checkout is not inside a transaction, where a
    transaction-local setting has nothing to attach to.

    An absent tenant is written as '' — matching no row, since `tenant_id` is
    NOT NULL everywhere — so an unscoped session reads nothing rather than
    everything. Executing SQL from this synchronous handler is safe on the async
    engine because SQLAlchemy's asyncio layer runs it inside its greenlet
    context.
    """
    from services.tenant_context import get_current_tenant_id

    conn.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": get_current_tenant_id() or ""},
    )


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()