from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, create_engine
from alembic import context
import sys, os


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import models.all_models  # noqa: F401
from database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


# Read from environment variable and force sync psycopg2 driver
_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://dataops_user:changeme@postgres:5432/dataops"
)
# Alembic needs sync driver — replace asyncpg with psycopg2 if needed
DB_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DB_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()