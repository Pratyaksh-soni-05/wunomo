"""Adversarial tests for PythonRunner's sandbox.

PythonRunner had ZERO tests against a malicious payload — the same starting
condition SqlRunner had before Item #5 Part 1, and a worse outcome when
measured. A 14-payload battery run against the pre-fix code EXECUTED 14 of 14:
not "reached the interpreter", executed, with results. It recovered `os`, read
`/etc/hostname`, and read `JWT_SECRET`, `ADMIN_DATABASE_URL` (the
SUPERUSER/BYPASSRLS role) and the 44-character `CREDENTIAL_ENCRYPTION_KEY` out
of the running app's settings — defeating Items #1, #2 and #4 from one place.

`test_old_ast_check_missed_every_bypass` reproduces the old `_ast_check`
verbatim from git and asserts it allowed each payload, so the improvement is
measured rather than claimed. This is the same self-check that caught two
mislabelled payloads in the SQL work; here it is stronger than it was there,
because the old checker is small enough to copy in full rather than
paraphrase.

The escape payloads are real and complete, not sketches. They are safe to run
in a test suite because every one is written to prove capability with a benign
observable — a pid, a hostname, the LENGTH of a secret — and never to
exfiltrate anything or write outside /tmp.
"""

import ast
import re
import time

import pandas as pd
import pytest

from modules.transformation import python_guard, python_sandbox
from modules.transformation.python_runner import PythonRunner


# ── The old implementation, reproduced verbatim for the before/after proof ───

# Copied unchanged from python_runner.py as it stood at commit af5212a. Do not
# tidy this — the one-level `isinstance(node.value, ast.Name)` test IS the
# vulnerability, and the point of the copy is that it stays wrong.
_OLD_ALLOWED_IMPORTS = frozenset(["pandas", "pd", "numpy", "np", "re", "datetime", "math"])
_OLD_BLOCKED_NAMES = frozenset([
    "eval", "exec", "compile", "__import__", "open", "input",
    "breakpoint", "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "hasattr",
    "os", "sys", "subprocess", "socket", "shutil",
    "importlib", "builtins", "pickle", "shelve",
])


def _old_ast_check(code: str) -> dict:
    if len(code) > 32_768:
        return {"error": "too long"}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"error": f"syntax: {exc}"}

    for node in ast.walk(tree):
        node_type = type(node).__name__
        if node_type == "Import":
            for alias in node.names:
                if alias.name.split(".")[0] not in _OLD_ALLOWED_IMPORTS:
                    return {"error": f"blocked import {alias.name}"}
        elif node_type == "ImportFrom":
            if (node.module or "").split(".")[0] not in _OLD_ALLOWED_IMPORTS:
                return {"error": f"blocked import from {node.module}"}
        elif node_type == "Name":
            if node.id in _OLD_BLOCKED_NAMES:
                return {"error": f"blocked name {node.id}"}
        elif node_type == "Attribute":
            # The hole: only fires when the value is a bare Name, so any
            # chain two levels deep or more was never examined.
            if isinstance(node.value, ast.Name):
                if node.value.id in _OLD_BLOCKED_NAMES:
                    return {"error": f"blocked attr {node.value.id}.{node.attr}"}
    return {"ok": True}


def _old_allows(code: str) -> bool:
    return "ok" in _old_ast_check(code)


# ── Payloads ─────────────────────────────────────────────────────────────────

# Recovers the real builtins from a class whose __init__ closes over them.
# This is the canonical CPython sandbox escape and the root of family A.
ESCAPE = """
bi = None
for c in ().__class__.__base__.__subclasses__():
    if c.__name__ == 'catch_warnings':
        bi = c.__init__.__globals__['__builtins__']
        break
"""

BYPASS_PAYLOADS = [
    ("escape_to_os_module", ESCAPE + """
os_mod = bi['__import__']('os')
result_df = pd.DataFrame({'pid': [os_mod.getpid()]})
"""),
    ("escape_to_real_open_reads_file", ESCAPE + """
result_df = pd.DataFrame({'host': [bi['open']('/etc/hostname').read().strip()]})
"""),
    ("escape_reads_process_secrets", ESCAPE + """
os_mod = bi['__import__']('os')
result_df = pd.DataFrame({'n': [len(os_mod.environ.get('JWT_SECRET', ''))]})
"""),
    ("escape_to_subprocess", ESCAPE + """
sp = bi['__import__']('subprocess')
result_df = pd.DataFrame({'t': [str(type(sp))]})
"""),
    ("escape_recovers_eval", ESCAPE + """
result_df = pd.DataFrame({'v': [bi['eval']('6*7')]})
"""),
    ("escape_reads_encryption_key", ESCAPE + """
cfg = bi['__import__']('config')
k = str(bi['getattr'](cfg.settings, 'CREDENTIAL_ENCRYPTION_KEY'))
result_df = pd.DataFrame({'key_len': [len(k)]})
"""),
    # No introspection needed at all — pandas is itself the escape.
    ("pandas_read_csv_reads_any_file", """
result_df = pd.read_csv('/etc/hostname', header=None, names=['host'])
"""),
    ("pandas_to_csv_writes_any_path", """
df.to_csv('/tmp/axiom_test_should_not_exist.csv')
result_df = pd.DataFrame({'wrote': [True]})
"""),
    ("pandas_read_pickle_is_rce", """
result_df = pd.DataFrame({'t': [str(type(pd.read_pickle))]})
"""),
    ("numpy_load_is_rce", """
result_df = pd.DataFrame({'t': [str(type(np.load))]})
"""),
    ("pandas_read_sql_reaches_the_database", """
result_df = pd.DataFrame({'t': [str(type(pd.read_sql))]})
"""),
    # Scoping tricks — a comprehension and a lambda get their own scopes, so
    # they were worth checking separately rather than assuming.
    ("comprehension_scope", """
n = [c.__name__ for c in (1).__class__.__mro__[-1].__subclasses__()]
result_df = pd.DataFrame({'n': [len(n)]})
"""),
    ("lambda_defers_to_runtime", """
f = (lambda: __builtins__)
result_df = pd.DataFrame({'t': [str(type(f()))]})
"""),
    ("walrus_in_subscript", """
result_df = pd.DataFrame({'n': [len((z := df.__class__.__mro__)[:])]})
"""),
]

# Variants that probe the NEW rules specifically rather than the old ones.
EVASIONS = [
    ("dunder_via_string_constant", """
name = '__class__'
result_df = pd.DataFrame({'n': [len(name)]})
"""),
    ("private_single_underscore_attribute", """
result_df = pd.DataFrame({'t': [str(type(df._mgr))]})
"""),
    ("df_eval_is_an_expression_evaluator", """
result_df = df.eval('a * 2')
"""),
    ("df_query_is_an_expression_evaluator", """
result_df = df.query('a > 0')
"""),
    ("to_parquet_export", """
df.to_parquet('/tmp/x.parquet')
result_df = df
"""),
    ("np_save_export", """
np.save('/tmp/x.npy', df.values)
result_df = df
"""),
    ("import_os_directly", """
import os
result_df = pd.DataFrame({'p': [os.getpid()]})
"""),
    ("from_os_import", """
from os import getpid
result_df = pd.DataFrame({'p': [getpid()]})
"""),
]

ALL_REJECTED = BYPASS_PAYLOADS + EVASIONS


@pytest.mark.parametrize("code", [p[1] for p in ALL_REJECTED],
                         ids=[p[0] for p in ALL_REJECTED])
def test_guard_rejects_payload(code):
    assert not python_guard.validate(code).ok, f"guard ALLOWED:\n{code}"


def test_old_ast_check_missed_every_bypass():
    """The before/after proof.

    Every payload in BYPASS_PAYLOADS was allowed by the old checker. If a
    future edit adds one the old code would have caught, this fails and names
    it — the list documents the improvement, so a payload that was never a
    bypass does not belong in it.
    """
    caught_by_old = [name for name, code in BYPASS_PAYLOADS if not _old_allows(code)]
    assert caught_by_old == [], (
        "these were already caught by the old check, so they are not bypasses: "
        f"{caught_by_old}"
    )


def test_runner_wires_the_guard_in():
    """The guard is reached through PythonRunner, not merely importable."""
    runner = PythonRunner("test-tenant")
    for _name, code in ALL_REJECTED:
        assert "error" in runner._ast_check(code), f"runner allowed:\n{code}"


# ── Rejections must not leak the rules ───────────────────────────────────────

def test_rejection_messages_do_not_leak_internals():
    """A rejection names the category of rule broken and nothing else.

    These strings become an HTTP 400 detail and go back into the agent's LLM
    context. A message naming the offending identifier lets anything iterating
    against it enumerate the rules one probe at a time — and an LLM retrying
    on error feedback does that by default, without needing to be adversarial.
    """
    leaks = [
        "__class__", "__subclasses__", "__globals__", "__builtins__",
        "catch_warnings", "read_csv", "to_parquet", "_mgr", "getpid",
        "subprocess", "Traceback", "ast.", "BLOCKED", "allowlist", "denylist",
    ]
    for _name, code in ALL_REJECTED:
        message = python_guard.validate(code).error
        assert message.startswith("Code rejected: "), message
        for leak in leaks:
            assert leak.lower() not in message.lower(), (
                f"rejection message leaked {leak!r}: {message!r}"
            )


def test_runtime_failures_do_not_return_a_traceback():
    """A traceback from inside the sandbox carries absolute paths, module
    names and local values. It belongs in the log, not the response."""
    runner = PythonRunner("test-tenant")
    result = runner._execute("result_df = df['nope_missing_column']",
                             pd.DataFrame({"a": [1]}))
    assert "error" in result
    assert "Traceback" not in result["error"]
    assert "/app/" not in result["error"]
    assert "KeyError" not in result["error"]


def test_syntax_errors_do_not_echo_the_source():
    result = python_guard.validate("result_df = df[")
    assert not result.ok
    assert "df[" not in result.error


# ── Runtime backstops: these must hold even if the guard is bypassed ─────────

# Each of these deliberately runs a payload the guard WOULD reject, straight
# past it and into the sandbox process. That is the point: the two layers are
# supposed to be independent, and a test that only ever goes through the guard
# proves nothing about the second one.

def test_environment_is_scrubbed_even_when_the_guard_is_bypassed():
    result = python_sandbox.run_sandboxed(ESCAPE + """
os_mod = bi['__import__']('os')
result_df = pd.DataFrame({
    'n_env': [len(os_mod.environ)],
    'jwt': [os_mod.environ.get('JWT_SECRET', '<absent>')],
})
""", pd.DataFrame({"a": [1]}), timeout=30)

    assert "result_df" in result, result.get("error")
    row = result["result_df"].to_dict("records")[0]
    assert row["n_env"] == 0, "the child process still has an environment"
    assert row["jwt"] == "<absent>"


def test_file_writes_fail_even_when_the_guard_is_bypassed():
    """RLIMIT_FSIZE of 0. This is what lets python_guard's I/O list be honest
    about being a denylist: a name the list misses still cannot produce a
    file."""
    result = python_sandbox.run_sandboxed(ESCAPE + """
f = bi['open']('/tmp/axiom_escape_write_test.txt', 'w')
f.write('x' * 1000)
f.close()
result_df = pd.DataFrame({'wrote': [True]})
""", pd.DataFrame({"a": [1]}), timeout=30)

    assert "error" in result, "a file write succeeded inside the sandbox"
    assert "File too large" in (result.get("detail") or ""), result.get("detail")


def test_infinite_loop_is_actually_killed():
    """The old timeout used thread.join(timeout), which stops WAITING, not
    running — measured at 1.01s return with the thread still alive. Python
    cannot kill a thread, so this had to become a process."""
    start = time.monotonic()
    result = python_sandbox.run_sandboxed(
        "while True:\n    pass\nresult_df = df",
        pd.DataFrame({"a": [1]}), timeout=3)
    elapsed = time.monotonic() - start

    assert "error" in result
    assert elapsed < 15, f"took {elapsed:.1f}s to stop an infinite loop"
    # Negative exit code == terminated by a signal, i.e. actually killed.
    assert "exitcode=-" in (result.get("detail") or ""), result.get("detail")


def test_memory_bomb_is_bounded():
    result = python_sandbox.run_sandboxed(
        "big = [0] * 500000000\nresult_df = pd.DataFrame({'n': [len(big)]})",
        pd.DataFrame({"a": [1]}), timeout=60)
    assert "error" in result, "a 4GiB allocation succeeded inside the sandbox"


# ── Legitimate transformations must still run ────────────────────────────────

LEGITIMATE = [
    ("identity", "result_df = df"),
    ("head", "result_df = df.head(1)"),
    ("fillna_astype", """
clean = df.copy()
clean['amount'] = clean['amount'].fillna(0.0)
result_df = clean.astype({'amount': 'float64'})
"""),
    ("groupby_sum", """
result_df = df.groupby('region', dropna=False)['amount'].sum().reset_index()
"""),
    ("named_agg_and_rename", """
agg = df.groupby('customer').agg(total=('amount', 'sum'), n=('amount', 'count')).reset_index()
result_df = agg.rename(columns={'n': 'order_count'})
"""),
    ("apply_lambda", """
result_df = df.copy()
result_df['tier'] = result_df['amount'].apply(lambda v: 'high' if v > 100 else 'low')
"""),
    ("str_accessor", """
result_df = df.copy()
result_df['upper'] = result_df['region'].str.upper().fillna('UNKNOWN')
"""),
    ("dt_accessor", """
result_df = df.copy()
result_df['month'] = result_df['created_at'].dt.month
"""),
    ("np_where", """
result_df = df.copy()
result_df['flag'] = np.where(result_df['amount'].fillna(0) > 90, 1, 0)
"""),
    ("merge", """
lookup = pd.DataFrame({'region': ['north'], 'code': ['N']})
result_df = df.merge(lookup, on='region', how='left')
"""),
    ("sort_filter_reset", """
result_df = df[df['amount'].notna()].sort_values('amount').reset_index(drop=True)
"""),
    ("pivot_table", """
result_df = pd.pivot_table(df, values='amount', index='region', aggfunc='mean').reset_index()
"""),
    ("concat", "result_df = pd.concat([df.head(2), df.tail(1)], ignore_index=True)"),
    ("safe_to_methods", """
result_df = df.copy()
result_df['amount'] = pd.to_numeric(result_df['amount'], errors='coerce')
rows = result_df.to_dict('records')
result_df = pd.DataFrame(rows)
"""),
    ("underscore_throwaway_in_iterrows", """
totals = []
for _, row in df.iterrows():
    totals.append(row['amount'])
result_df = pd.DataFrame({'amount': totals})
"""),
    ("underscore_prefixed_local", """
_tmp = df['amount'].fillna(0)
result_df = pd.DataFrame({'amount': _tmp})
"""),
    ("underscore_prefixed_column_by_subscript", """
result_df = df[['_internal']].copy()
result_df['doubled'] = result_df['_internal'] * 2
"""),
    ("nested_function_def", """
def bucket(v):
    return 'high' if v > 100 else 'low'

result_df = df.copy()
result_df['bucket'] = result_df['amount'].fillna(0).map(bucket)
"""),
    ("list_comprehension", """
vals = [v * 2 for v in df['amount'].fillna(0)]
result_df = pd.DataFrame({'doubled': vals})
"""),
]


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "region": ["north", "south", "north"],
        "amount": [100.0, 250.5, None],
        "customer": ["Acme", "Beta", "Acme"],
        "created_at": pd.to_datetime(["2026-01-05", "2026-02-11", "2026-02-20"]),
        "_internal": [1, 2, 3],
    })


@pytest.mark.parametrize("code", [c[1] for c in LEGITIMATE],
                         ids=[c[0] for c in LEGITIMATE])
def test_legitimate_transformation_passes_the_guard(code):
    result = python_guard.validate(code)
    assert result.ok, f"guard rejected legitimate code: {result.error}\n{code}"


@pytest.mark.parametrize("code", [c[1] for c in LEGITIMATE],
                         ids=[c[0] for c in LEGITIMATE])
def test_legitimate_transformation_executes(code, sample_df):
    runner = PythonRunner("test-tenant")
    result = runner._execute(code, sample_df)
    assert "error" not in result, f"{result.get('error')}\n{code}"
    assert isinstance(result["result_df"], pd.DataFrame)


ALLOWED_IMPORT_CASES = [
    ("import_re", "import re\nresult_df = pd.DataFrame({'n': [len(re.findall('a', 'aba'))]})"),
    ("import_math", "import math\nresult_df = pd.DataFrame({'n': [math.sqrt(9)]})"),
    ("from_datetime", "from datetime import datetime\nresult_df = pd.DataFrame({'n': [1]})"),
]


@pytest.mark.parametrize("code", [c[1] for c in ALLOWED_IMPORT_CASES],
                         ids=[c[0] for c in ALLOWED_IMPORT_CASES])
def test_allowed_imports_actually_work(code, sample_df):
    """A pre-existing bug, fixed here rather than left standing.

    The allowlist has permitted re/datetime/math since it was written, and
    transform_generator's system prompt tells the model it may use them — but
    the exec namespace had no `__import__`, so every one raised
    "ImportError: __import__ not found". Verified against the pre-fix code
    before changing anything: AXIOM was advertising three imports it had never
    supported.
    """
    runner = PythonRunner("test-tenant")
    result = runner._execute(code, sample_df)
    assert "error" not in result, result.get("error")


def test_import_shim_resolves_only_the_allowlist():
    """The shim must not become a general import mechanism if the static
    guard's import check is ever bypassed."""
    result = python_sandbox.run_sandboxed(
        "os = __import__('os')\nresult_df = pd.DataFrame({'p': [os.getpid()]})",
        pd.DataFrame({"a": [1]}), timeout=30)
    assert "error" in result, "the sandbox imported os"
