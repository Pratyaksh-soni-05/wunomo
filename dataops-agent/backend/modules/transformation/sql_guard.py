"""Parse-tree SQL safety validation for SqlRunner.

    WHY THIS REPLACED A KEYWORD BLOCKLIST
    -------------------------------------
    The previous control uppercased the query, split it on `\\W+`, and
    rejected it if any resulting token appeared in a 17-word blocklist. It
    failed in both directions, measured rather than assumed — a 17-payload
    battery run against the old `_check_safety` returned ALLOWED on all 17,
    including `SELECT pg_sleep(30)`, `EXPLAIN ANALYZE ...`, `SELECT * INTO
    evil FROM orders` (DDL with no blocked keyword in it), reads of
    `information_schema` and `pg_catalog`, and `SELECT set_config(...)`,
    which can repoint the RLS tenant context the whole of Item #2 rests on.

    In the other direction it rejected `WHERE action = 'delete'`, because a
    string literal tokenises exactly like a keyword — and it rejected the SQL
    AXIOM itself generates, since `transform_generator`'s own system prompt
    tells the model to start its output with `--` and a leading comment makes
    the first token the empty string.

    A tokeniser cannot tell a keyword from a string literal, an identifier, or
    a comment, because that distinction is precisely what parsing is. So this
    module parses.

WHAT IS ENFORCED

Five checks, all on the parse tree rather than on the text:

  1. Exactly one statement, and its root is a SELECT (or a set operation over
     SELECTs). Statement chaining via `;` becomes two parse trees and is
     rejected by counting them, not by hunting for semicolons — which is why
     a semicolon inside a string literal or comment no longer matters.
  2. No write or command node ANYWHERE in the tree, not just at the root.
     This is what catches a write hidden in a CTE. It keys off sqlglot's
     `DDL`/`DML` base classes plus an explicit list, so a new statement type
     in a future sqlglot is covered by the base classes rather than silently
     allowed.
  3. No catalog or system schema access.
  4. No timing, file-I/O, network-egress, or session-mutating functions.
  5. No cartesian product between two real tables.

Anything sqlglot cannot parse becomes an `exp.Command` node, which check 2
rejects. That is the important default: unrecognised syntax fails CLOSED. It
is also what closes `EXPLAIN ANALYZE`, which parses as a Command — the old
code explicitly permitted `EXPLAIN` as a leading token, and `ANALYZE` makes
the planner genuinely execute the query it claims to be merely explaining.

DIALECTS, AND WHY BOTH ARE PARSED

SqlRunner targets postgres and mysql, and the safety verdict must not depend
on guessing which. The query is parsed under both. Every parse that succeeds
must pass every check; if none parses, the query is rejected. Validating only
the dialect that happened to parse would let a query be waved through under a
reading nobody executes, so the conservative reading always wins.

NOT ENFORCED HERE, DELIBERATELY

This is one layer, not the boundary. Postgres RLS (Item #2) still constrains
what the app's own role can see, the `dataops_app` role's own grants still
deny `pg_shadow`/`pg_authid`/`pg_read_file` (verified directly), and the row
cap and statement timeout still bound a query that is merely expensive rather
than malicious. Those are complementary: RLS governs rows, this governs which
SQL is allowed to exist. Neither subsumes the other — and for
`run_on_source`, which connects to a CUSTOMER's warehouse with
customer-supplied credentials, the RLS and role protections do not apply at
all, because that role is whatever the customer configured. This layer is the
only one that travels with the query.
"""

from typing import Optional

import sqlglot
from sqlglot import exp

# Both dialects SqlRunner can execute against. See the module docstring on why
# a query must be safe under every dialect that can parse it.
DIALECTS = ("postgres", "mysql")


def _forbidden_node_types() -> tuple:
    """Node types that must not appear anywhere in the tree.

    `DDL` and `DML` are sqlglot base classes, so they cover Insert/Update/
    Delete/Create/Merge/Copy and anything a future sqlglot adds under them
    without this list needing to change. `Command` is sqlglot's fallback for
    syntax it does not model — VACUUM, EXPLAIN, CALL, DO, GRANT-like
    statements — and rejecting it is what makes unparsed syntax fail closed.

    The named classes are the ones that inherit from neither base (verified:
    Drop, Alter and Grant are all outside DDL/DML in sqlglot 30.x). Resolved
    via getattr so that a version bump which renames or removes one degrades
    to "not checked" rather than crashing every query at import time.
    """
    types = [exp.DDL, exp.DML, exp.Command]
    for name in (
        "Drop", "Alter", "AlterTable", "Grant", "Revoke", "TruncateTable",
        "Set", "SetItem", "Use", "Transaction", "Commit", "Rollback",
        "Analyze", "Refresh", "Attach", "Detach", "Export", "LoadData",
        "Pragma", "Into", "Cache", "Uncache",
    ):
        node = getattr(exp, name, None)
        if node is not None:
            types.append(node)
    return tuple(types)


FORBIDDEN_NODES = _forbidden_node_types()

# A set operation is a legitimate root: `SELECT ... UNION SELECT ...` is still
# a read. Subquery covers a parenthesised root.
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)

# Schemas that expose the server's own metadata. Reading these leaks the
# schema of every tenant's data at once, and RLS does not protect them — the
# catalog is not a tenant-owned table. Confirmed reachable: as `dataops_app`,
# `information_schema.tables` returns 218 rows and `pg_catalog.pg_tables`
# returns 96.
BLOCKED_SCHEMAS = frozenset({
    "information_schema", "pg_catalog", "pg_toast", "pg_temp",
    "mysql", "performance_schema", "sys",
})

# Unqualified catalog tables (`SELECT * FROM pg_tables`) resolve through
# search_path without naming a schema, so the schema check alone misses them.
BLOCKED_TABLE_PREFIXES = ("pg_",)

# Function namespaces, matched by prefix:
#   pg_     — the whole system-function namespace: pg_sleep (timing abuse),
#             pg_read_file / pg_ls_dir (file I/O), pg_terminate_backend.
#             Blocking the namespace wholesale also blocks harmless members
#             like pg_typeof; that is an accepted cost, since transformation
#             SQL has no reason to reach into it and an allowlist of the
#             harmless ones would need maintaining forever.
#   lo_     — large-object I/O, i.e. lo_export writes server-side files.
#   dblink  — outbound network connections from inside a query.
BLOCKED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")

BLOCKED_FUNCTIONS = frozenset({
    # Timing abuse. pg_sleep is covered by the prefix rule; these are the
    # MySQL and SQL-Server spellings, which are not.
    "sleep", "benchmark", "waitfor", "delay",
    # File I/O and command execution (MySQL).
    "load_file", "sys_exec", "sys_eval",
    # set_config writes a session GUC. That matters specifically here:
    # `SELECT set_config('app.current_tenant_id', <other>, false)` would
    # repoint the exact setting every RLS policy from Item #2 reads, turning
    # a read-only query into a cross-tenant one. current_setting() is not
    # blocked — reading the value discloses nothing the caller does not
    # already know.
    "set_config",
})

# Every rejection reason is one of these. Deliberately coarse: the caller sees
# WHICH RULE it broke and nothing about how the rule is implemented. See
# `validate()`'s docstring.
_MSG_UNPARSEABLE = "SQL rejected: the query could not be parsed as valid SQL."
_MSG_NOT_SINGLE = "SQL rejected: exactly one statement is allowed."
_MSG_NOT_SELECT = "SQL rejected: only SELECT queries are permitted."
_MSG_WRITE = "SQL rejected: the query is not read-only."
_MSG_CATALOG = "SQL rejected: system and catalog tables are not accessible."
_MSG_FUNCTION = "SQL rejected: the query uses a function that is not permitted."
_MSG_CARTESIAN = "SQL rejected: joins must specify a join condition."


class SqlGuardResult:
    """Verdict plus the one fact SqlRunner needs to act on: whether the ROOT
    of the query already bounds its own row count.

    That distinction is the point. The old `_inject_limit` searched the raw
    text for `\\bLIMIT\\b`, so `SELECT * FROM big WHERE id IN (SELECT id FROM
    small LIMIT 1)` looked bounded and had no limit added — the subquery's
    LIMIT satisfied the regex while the outer scan stayed unbounded. Reading
    the limit off the root node cannot make that mistake.
    """

    __slots__ = ("ok", "error", "has_root_limit")

    def __init__(self, ok: bool, error: Optional[str] = None, has_root_limit: bool = False):
        self.ok = ok
        self.error = error
        self.has_root_limit = has_root_limit


def _is_trailing_comment(statement: exp.Expression) -> bool:
    """True for a `;` followed only by a comment.

    sqlglot yields a second statement for `SELECT 1; -- done`: an
    `exp.Semicolon` carrying the comment and no executable content. Counting it
    would reject `SELECT * FROM t LIMIT 5;` followed by a trailing comment,
    which is a shape transform_generator actively produces — its system prompt
    tells the model to "add inline SQL comments explaining each major step".

    This is narrow on purpose. Only the Semicolon node type is skipped, and a
    real statement after a comment (`SELECT 1; /* x */ DROP TABLE t`) parses as
    a Drop, not a Semicolon, so it is still counted and still rejected.
    """
    semicolon = getattr(exp, "Semicolon", None)
    return semicolon is not None and isinstance(statement, semicolon)


def _table_is_blocked(table: exp.Table) -> bool:
    schema = (table.db or "").lower()
    name = (table.name or "").lower()
    if schema in BLOCKED_SCHEMAS:
        return True
    # pg_temp_1, pg_toast_temp_3 etc. are numbered per backend.
    if schema.startswith("pg_"):
        return True
    if not schema and name.startswith(BLOCKED_TABLE_PREFIXES):
        return True
    return False


def _function_names(tree: exp.Expression):
    """Every function name in the tree, lowercased.

    sqlglot parses functions it knows into dedicated node types (Sum, Count,
    Coalesce) and everything else into `Anonymous`, which carries the literal
    name. Only the anonymous ones can be dangerous here — a function sqlglot
    has a node type for is a standard SQL function — but both are yielded so
    the check does not depend on that assumption holding.
    """
    for node in tree.find_all(exp.Anonymous):
        if node.name:
            yield node.name.lower()
    for node in tree.find_all(exp.Func):
        if isinstance(node, exp.Anonymous):
            continue
        name = getattr(node, "sql_name", None)
        if callable(name):
            yield name().lower()


def _is_tautology(condition: exp.Expression) -> bool:
    """True for an ON clause that constrains nothing: `ON true`, `ON 1=1`.

    Only the literal spellings. Deciding in general whether a predicate is a
    tautology means evaluating it, which is not something a parser can do, so
    this is explicitly best-effort — `ON a.x = a.x` still gets through. It is
    worth doing anyway because these two spellings are how a cartesian product
    is actually written once someone knows bare CROSS JOIN is refused.

    The real backstop for an expensive-but-legal query is not this check: it is
    the root LIMIT and the statement timeout, which bound the damage regardless
    of how the product was expressed.
    """
    if isinstance(condition, exp.Boolean):
        return bool(condition.this)
    if isinstance(condition, exp.EQ):
        left, right = condition.this, condition.expression
        if isinstance(left, exp.Literal) and isinstance(right, exp.Literal):
            return left.this == right.this
    return False


def _is_base_table(node: exp.Expression) -> bool:
    """True for a real table, false for a table FUNCTION.

    sqlglot wraps both in `exp.Table`; what separates them is the inner node —
    a plain table's `.this` is an Identifier, whereas `generate_series(1, 10)`
    holds the function node there. `unnest(...)` gets its own node type again.
    Distinguishing them matters because `FROM orders o, unnest(o.tags) t` is an
    ordinary transformation shape, not an attack: the right-hand side is
    derived from the left and yields a bounded number of rows per input row.
    """
    if not isinstance(node, exp.Table):
        return False
    return not isinstance(node.this, exp.Func)


def _is_cartesian(join: exp.Join) -> bool:
    """A join that multiplies two real tables together.

    `FROM a, b` and `CROSS JOIN` both land here, as does an ON clause that
    constrains nothing. Only a product of two BASE tables is rejected — that is
    the shape that squares a real row count. Crossing a table with a table
    function is left alone (see `_is_base_table`).

    Known restriction, accepted rather than overlooked: crossing a generated
    series with a real table — the date-spine pattern — is rejected, because the
    joined side is a base table. The workaround is an explicit ON clause, which
    such a query can always be rewritten to use.
    """
    if not _is_base_table(join.this):
        return False
    condition = join.args.get("on")
    if condition is not None:
        return _is_tautology(condition)
    return not join.args.get("using")


def _validate_tree(tree: exp.Expression) -> Optional[str]:
    """Returns a rejection message, or None if the tree is acceptable."""
    if not isinstance(tree, ALLOWED_ROOTS):
        # Covers Command (unparsed syntax, EXPLAIN, VACUUM), Set, Insert at
        # the root, and anything else that is not a read.
        return _MSG_NOT_SELECT

    # Checked over the whole tree, not just the root: this is what catches a
    # write hidden inside a CTE, e.g.
    #   WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x
    # whose root really is a Select.
    if tree.find(*FORBIDDEN_NODES) is not None:
        return _MSG_WRITE

    # `SELECT * INTO evil FROM orders` creates a table. The root is a plain
    # Select carrying an `into` argument, and no keyword in it appears in any
    # blocklist — the old check allowed it.
    if tree.args.get("into"):
        return _MSG_WRITE

    for table in tree.find_all(exp.Table):
        if _table_is_blocked(table):
            return _MSG_CATALOG

    for name in _function_names(tree):
        if name.startswith(BLOCKED_FUNCTION_PREFIXES) or name in BLOCKED_FUNCTIONS:
            return _MSG_FUNCTION

    for join in tree.find_all(exp.Join):
        if _is_cartesian(join):
            return _MSG_CARTESIAN

    return None


def validate(sql: str) -> SqlGuardResult:
    """Validate a query for read-only execution.

    On rejection, `error` names the rule that was broken and nothing else. It
    does not echo the offending token, name the function or table that
    tripped the check, or expose the parser. That is deliberate: the caller is
    an LLM-generated or user-supplied query, and these messages are returned
    verbatim over the API (`transformations.py` raises them as a 400 detail)
    and fed back to the model. An error saying `blocked keyword 'DROP'
    detected` — which is what the old check returned — hands an attacker the
    blocklist one probe at a time and tells them exactly which spelling to
    try next. The rules are coarse enough that a legitimate author can still
    tell what to fix.
    """
    if not sql or not sql.strip():
        return SqlGuardResult(False, _MSG_UNPARSEABLE)

    parsed_any = False
    has_root_limit = True  # AND-ed across dialects below, so it fails closed.

    for dialect in DIALECTS:
        try:
            statements = [
                s for s in sqlglot.parse(sql, read=dialect)
                if s is not None and not _is_trailing_comment(s)
            ]
        except Exception:
            # This dialect cannot read the query. Another still might; only if
            # none can is the query rejected as unparseable.
            continue

        parsed_any = True

        if len(statements) != 1:
            # Two trees means two statements. Note this is reached even when
            # the driver would have refused the chained query anyway (asyncpg
            # raises "cannot insert multiple commands into a prepared
            # statement") — that refusal is a property of the postgres wire
            # protocol, not of the safety layer, so it does not cover the
            # MySQL path and is not something to depend on.
            return SqlGuardResult(False, _MSG_NOT_SINGLE)

        error = _validate_tree(statements[0])
        if error:
            return SqlGuardResult(False, error)

        root = statements[0]
        if not (root.args.get("limit") or root.args.get("fetch")):
            has_root_limit = False

    if not parsed_any:
        return SqlGuardResult(False, _MSG_UNPARSEABLE)

    return SqlGuardResult(True, None, has_root_limit)
