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