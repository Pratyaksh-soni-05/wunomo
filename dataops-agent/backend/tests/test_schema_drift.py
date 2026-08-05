"""Schema drift detection: does `alembic upgrade head`, run from a
genuinely empty database, produce a schema that matches what the
SQLAlchemy models actually declare? `create_all()` (this project's real
running source of truth) has silently masked any gap between the two for
this project's entire history - see CLAUDE.md's migration-drift Gotcha.
This test is what would have caught it.

Runs against a throwaway, real Postgres database created on the same
server the rest of the test suite already talks to - never the shared
dev/test `dataops` database itself, always dropped in teardown.
"""
import os
import uuid

import psycopg2
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url

from config import settings
from database import Base
import models.all_models  # noqa: F401 - registers tables on Base.metadata
import models.cicd  # noqa: F401 - registers CI/CD tables on Base.metadata

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations"
)


def _url(dbname: str) -> str:
    # render_as_string(hide_password=False), not str(url) -- SQLAlchemy's
    # URL.__str__ masks the password as a literal "***" by default, which
    # psycopg2 would then try to authenticate with verbatim.
    url = make_url(settings.DATABASE_URL).set(drivername="postgresql", database=dbname)
    return url.render_as_string(hide_password=False)


@pytest.fixture
def drift_db():
    """Creates a throwaway sibling database, yields its plain
    `postgresql://` URL, drops it afterward. Only ever creates/drops this
    one throwaway name - never touches the real `dataops` database."""
    db_name = f"schema_drift_check_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(_url("postgres"))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    admin.close()

    try:
        yield _url(db_name)
    finally:
        admin = psycopg2.connect(_url("postgres"))
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin.close()


def test_migrations_match_the_models(drift_db):
    """Migrate a genuinely empty DB to head, then diff the result against
    Base.metadata via Alembic's own compare_metadata. Any real diff means
    a model changed without a matching migration, or vice versa."""
    # migrations/env.py reads DATABASE_URL directly from the environment
    # (not from the Config object passed to `command.upgrade`), so this
    # is the only way to point it at the throwaway DB instead of the real
    # one this env var normally names.
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = drift_db
    try:
        cfg = Config()
        cfg.set_main_option("script_location", MIGRATIONS_DIR)
        command.upgrade(cfg, "head")
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original

    engine = create_engine(drift_db)
    try:
        with engine.connect() as connection:
            diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()

    assert not diffs, (
        f"Migration chain and models have diverged ({len(diffs)} diff(s)) - "
        "a model changed without a matching migration, or vice versa:\n"
        + "\n".join(repr(d) for d in diffs)
    )


def test_migrated_task_enum_labels_match_the_python_enum_member_names(drift_db):
    """compare_metadata() (the test above) doesn't diff enum LABEL content
    -- only table/column/index/FK existence -- so a migration that lists
    the wrong Postgres enum labels for a real Python enum column passes
    that check cleanly while being genuinely broken: SQLAlchemy's default
    Enum(PythonEnumClass) behavior stores the member .name (e.g.
    'DRAFT_PLAN'), not .value ('draft_plan'), and every enum in this
    codebase already relies on that (confirmed live against pg_enum for
    personalitymode/runstatus/etc. before this test was written). An
    earlier draft of 509a9b8715f2 got this backwards for all 4 new Task
    enum types -- caught by directly querying pg_enum, not by
    compare_metadata(), which is exactly why this check exists now."""
    from models.all_models import TaskShape, TaskStatus, TaskStepStatus, TaskStepSource

    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = drift_db
    try:
        cfg = Config()
        cfg.set_main_option("script_location", MIGRATIONS_DIR)
        command.upgrade(cfg, "head")
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original

    conn = psycopg2.connect(drift_db)
    try:
        with conn.cursor() as cur:
            for pg_type_name, enum_class in [
                ("taskshape", TaskShape),
                ("taskstatus", TaskStatus),
                ("taskstepstatus", TaskStepStatus),
                ("taskstepsource", TaskStepSource),
            ]:
                cur.execute(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t "
                    "ON e.enumtypid = t.oid WHERE t.typname = %s",
                    (pg_type_name,),
                )
                migrated_labels = {row[0] for row in cur.fetchall()}
                expected_labels = {member.name for member in enum_class}
                assert migrated_labels == expected_labels, (
                    f"{pg_type_name}: migration produced {migrated_labels}, "
                    f"but {enum_class.__name__}'s real member names are "
                    f"{expected_labels}"
                )
    finally:
        conn.close()
