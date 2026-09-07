"""Regression tests for SQL injection through a DataSource's table name.

`PythonRunner._load_dataframe`'s postgres branch built its query as
`f'SELECT * FROM {table} LIMIT {row_limit}'`, interpolating a value taken
straight from `DataSource.connection_config`. Nothing constrains that value:
`POST /sources` accepts `connection_config: dict` and stores it verbatim, so
anyone able to create or update a source could put a payload there and have it
executed on every pandas transformation against that source — a stored
injection, not a reflected one, and one that never passes through
`sql_guard.py` because it is not user-submitted SQL.

Found while auditing python_runner.py for the Python sandbox work (Item #5
Part 2) and fixed narrowly: the identifier is validated and quoted, and the
row limit is bound rather than interpolated. The two known Hard Rule 1 and
Hard Rule 4 violations in the same function -- the hand-built asyncpg
connection and `config.get("host", "localhost")` -- are deliberately untouched
and remain separately tracked.
"""

import uuid

import pytest
import pytest_asyncio

from models.all_models import DataSource, SourceType
from modules.transformation.python_runner import (
    MAX_ROWS_INPUT,
    PythonRunner,
    _safe_row_limit,
    _safe_table_identifier,
)
from services.tenant_context import tenant_session


MALICIOUS_TABLE_NAMES = [
    ("statement_chaining", "orders; DROP TABLE tenants"),
    ("chained_with_comment", "orders; DROP TABLE tenants; --"),
    ("union_select", "orders UNION SELECT * FROM pg_shadow"),
    ("nested_select", "(SELECT passwd FROM pg_shadow)"),
    ("line_comment", "orders--"),
    ("block_comment", "orders/*x*/"),
    ("quote_breakout", 'orders" ; DROP TABLE tenants; --'),
    ("single_quote_breakout", "orders' OR '1'='1"),
    ("appended_clause", "orders LIMIT 1 OFFSET 0"),
    ("newline_smuggling", "orders\nUNION SELECT 1"),
    ("three_part_name", "a.b.c"),
    ("empty", ""),
    ("whitespace_only", "   "),
    ("not_a_string", 12345),
    ("none", None),
]


@pytest.mark.parametrize("table", [t[1] for t in MALICIOUS_TABLE_NAMES],
                         ids=[t[0] for t in MALICIOUS_TABLE_NAMES])
def test_malicious_table_name_is_rejected(table):
    assert _safe_table_identifier(table) is None, (
        f"injection payload accepted as a table name: {table!r}"
    )


LEGITIMATE_TABLE_NAMES = [
    ("simple", "orders", '"orders"'),
    ("schema_qualified", "public.orders", '"public"."orders"'),
    ("leading_underscore", "_internal", '"_internal"'),
    ("mixed_case_preserved", "Order2", '"Order2"'),
    ("dollar_sign", "tbl$x", '"tbl$x"'),
    ("surrounding_whitespace_trimmed", "  orders  ", '"orders"'),
    # Quoting is not only about safety: a table legitimately named after a
    # reserved word is unaddressable without it.
    ("reserved_word", "select", '"select"'),
]


@pytest.mark.parametrize("table,expected",
                         [(t[1], t[2]) for t in LEGITIMATE_TABLE_NAMES],
                         ids=[t[0] for t in LEGITIMATE_TABLE_NAMES])
def test_legitimate_table_name_is_quoted(table, expected):
    assert _safe_table_identifier(table) == expected


def test_row_limit_is_coerced_and_bounded():
    """Typed as Optional[int] on the HTTP request, but run_on_source is also
    called directly by the agent tool and by preview(), and a caller that is
    correct today is not a control."""
    assert _safe_row_limit(100) == 100
    assert _safe_row_limit("500") == 500          # coerced, not trusted
    assert _safe_row_limit(-5) == 1               # floored
    assert _safe_row_limit(10 ** 9) == MAX_ROWS_INPUT   # capped
    assert _safe_row_limit(None) == MAX_ROWS_INPUT
    assert _safe_row_limit("not a number") == MAX_ROWS_INPUT
    assert _safe_row_limit([1]) == MAX_ROWS_INPUT


# ── The payload must not reach a connection, let alone a query ──────────────

async def _register(client) -> dict:
    email = f"inj-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "Sup3rSecret!",
        "full_name": "Injection Test", "tenant_name": "InjTest",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest_asyncio.fixture
async def tenant_id(client) -> str:
    return (await _register(client))["tenant_id"]


# A database name no real connection in this suite uses, so the patched
# asyncpg.connect below can tell OUR call apart from SQLAlchemy's own. Patching
# asyncpg.connect unconditionally breaks the engine itself -- the async
# dialect opens its pool connections through exactly the same function -- which
# is how the first version of these tests failed.
PROBE_DB = "inj_probe_db"


async def _make_source(tenant_id: str, table_value) -> str:
    async with tenant_session(tenant_id) as db:
        source = DataSource(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="inj-source",
            source_type=SourceType.POSTGRES,
            connection_config={
                "host": "postgres", "port": 5432, "database": PROBE_DB,
                "username": "dataops_app", "password": "x", "table": table_value,
            },
        )
        db.add(source)
        await db.flush()
        source_id = source.id
        await db.commit()
        return source_id


def _patch_connect(monkeypatch, handler):
    """Intercept only the connection PythonRunner makes, and let every other
    asyncpg.connect through to the real driver so the test session's own
    database access keeps working."""
    import asyncpg
    real_connect = asyncpg.connect

    async def _dispatch(*args, **kwargs):
        if kwargs.get("database") == PROBE_DB:
            return await handler(*args, **kwargs)
        return await real_connect(*args, **kwargs)

    monkeypatch.setattr(asyncpg, "connect", _dispatch)


class _FakeConn:
    """Records the SQL and bind parameters instead of executing anything."""

    def __init__(self, seen: dict):
        self._seen = seen

    async def fetch(self, sql, *args):
        self._seen["sql"] = sql
        self._seen["args"] = args
        return []

    async def close(self):
        self._seen["closed"] = True


@pytest.mark.asyncio
async def test_injection_payload_never_opens_a_database_connection(
        tenant_id, monkeypatch):
    """The strongest form of the property.

    Not "the malicious query was rejected by the database" and not "the table
    survived" -- the payload never causes a connection to be opened at all,
    because the identifier is validated before `asyncpg.connect`. The
    interceptor fails loudly if it is ever reached.
    """
    async def _explode(*args, **kwargs):
        raise AssertionError(
            "asyncpg.connect() was called despite a rejected table name")

    _patch_connect(monkeypatch, _explode)

    source_id = await _make_source(tenant_id, "orders; DROP TABLE tenants; --")
    result = await PythonRunner(tenant_id)._load_dataframe(source_id, 100)

    assert "error" in result
    assert "invalid table name" in result["error"]


@pytest.mark.asyncio
async def test_rejection_message_does_not_echo_the_payload(tenant_id, monkeypatch):
    """Same standard as the rest of Item #5: this error goes back over the API
    and into the agent's LLM context, so it must not quote the offending
    value."""
    async def _explode(*args, **kwargs):
        raise AssertionError("connected")

    _patch_connect(monkeypatch, _explode)

    payload = "orders; DROP TABLE tenants; --"
    source_id = await _make_source(tenant_id, payload)
    result = await PythonRunner(tenant_id)._load_dataframe(source_id, 100)

    assert "DROP" not in result["error"].upper()
    assert payload not in result["error"]


@pytest.mark.asyncio
async def test_legitimate_table_is_quoted_and_the_limit_is_bound(
        tenant_id, monkeypatch):
    """Proves the fix at the point it matters: the SQL that actually reaches
    the driver carries a quoted identifier and a BIND PARAMETER for the limit,
    rather than two interpolated strings."""
    seen: dict = {}

    async def _handler(*args, **kwargs):
        return _FakeConn(seen)

    _patch_connect(monkeypatch, _handler)

    source_id = await _make_source(tenant_id, "widgets")
    result = await PythonRunner(tenant_id)._load_dataframe(source_id, 250)

    assert "error" not in result, result
    assert seen["sql"] == 'SELECT * FROM "widgets" LIMIT $1'
    assert seen["args"] == (250,)
    assert seen.get("closed") is True


@pytest.mark.asyncio
async def test_row_limit_is_bound_even_when_a_caller_passes_a_string(
        tenant_id, monkeypatch):
    seen: dict = {}

    async def _handler(*args, **kwargs):
        return _FakeConn(seen)

    _patch_connect(monkeypatch, _handler)

    source_id = await _make_source(tenant_id, "widgets")
    await PythonRunner(tenant_id)._load_dataframe(source_id, "9999999")

    # Coerced to int and capped, and passed as a parameter rather than spliced
    # into the SQL text.
    assert seen["args"] == (MAX_ROWS_INPUT,)
    assert "9999999" not in seen["sql"]


def test_a_catalog_sounding_name_is_allowed_because_it_is_a_valid_identifier():
    """Documents the boundary of this fix rather than overstating it.

    `pg_shadow` is a perfectly valid identifier and is accepted. This change is
    scoped to injection -- stopping a config value from becoming SQL syntax --
    not to catalog policy. It is also the right call here: run_on_source
    connects to a CUSTOMER's database with their credentials, where a table
    named like a catalog table may simply be theirs, and the app's own
    `dataops_app` role cannot read `pg_shadow` regardless (verified in Part 1).

    This test was written because the first draft of the malicious list
    wrongly included it and the parametrised test failed, which is the check
    working.
    """
    assert _safe_table_identifier("pg_shadow") == '"pg_shadow"'
