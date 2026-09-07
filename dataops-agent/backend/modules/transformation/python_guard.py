"""Static validation for PythonRunner's transformation code.

    WHY THE PREVIOUS AST CHECK FAILED COMPLETELY
    --------------------------------------------
    The old `_ast_check` walked the tree and rejected: imports outside a
    six-name allowlist, `Name` nodes in a 23-word blocklist, and `Attribute`
    nodes **whose `.value` was itself a `Name`** in that same blocklist.

    That last clause is the hole, and it is one line of code:

        if isinstance(node.value, ast.Name):
            if node.value.id in BLOCKED_NAMES:

    An attribute chain deeper than one level has an `Attribute` as its
    `.value`, not a `Name`, so the check simply did not apply. Nothing
    examined `__class__`, `__mro__`, `__subclasses__`, or `__globals__` at
    all — the entire Python-sandbox-escape literature was unreachable by the
    check that was supposed to stop it.

    A 14-payload battery run against the old code executed **14 of 14**. Not
    "reached the interpreter" — executed, with results. Among them: recovering
    the real `__builtins__` from `catch_warnings.__init__.__globals__`, then
    `__import__('os')`; reading `/etc/hostname`; reading `JWT_SECRET`,
    `ADMIN_DATABASE_URL` (the SUPERUSER/BYPASSRLS role) and the 44-character
    `CREDENTIAL_ENCRYPTION_KEY` out of the app's own settings. That last set
    means this one function defeated Items #1, #2 and #4 at once: the Fernet
    key decrypts every stored warehouse credential, the admin DSN bypasses
    every RLS policy, and the JWT secret mints tokens that revocation cannot
    reach because they were never issued.

    Two of the fourteen needed no introspection at all:
    `pd.read_csv('/etc/hostname')` read a file and `df.to_csv('/tmp/x')` wrote
    one, using nothing but the pandas the feature exists to provide.

TWO RULES, ONE STRUCTURAL AND ONE NOT — THE DIFFERENCE MATTERS

1. NO PRIVATE ATTRIBUTE ACCESS. Every ATTRIBUTE beginning with an underscore
   is rejected, at every level of a chain. This is structural, not a list of
   known escapes: every published CPython sandbox escape traverses private
   attributes (`__class__`, `__bases__`, `__subclasses__`, `__globals__`,
   `__builtins__`, `func_globals`, `gi_frame`), because that is the only
   route from an ordinary object to the interpreter. Rejecting the namespace
   closes the technique rather than the instances, so an escape published
   tomorrow is already covered. An underscore-prefixed COLUMN is still
   reachable as `df['_internal']` — a subscript, not an attribute.

   VARIABLES are held to the looser dunder-only rule, and the asymmetry is
   deliberate; see `_is_private_name`. Rejecting every `_`-prefixed variable
   broke `for _, row in df.iterrows()` and ordinary `_tmp` locals in testing
   while buying nothing, because a local name reaches only this sandbox's own
   namespace.

2. NO I/O SURFACE. This one IS a denylist, and calling it anything else
   would be dishonest. pandas and numpy must be in the namespace for the
   feature to work at all, and they expose file reads, network fetches,
   `pickle` deserialisation (`read_pickle`, `np.load`) and file writes as
   ordinary methods. There is no structural rule separating "pandas that
   transforms" from "pandas that reaches the disk"; there is only a list.
   The list is maintained here, and it is backstopped at runtime by the
   sandbox process's `RLIMIT_FSIZE` of 0 and scrubbed environment, so a name
   this list misses still cannot write a file or read a secret.

WHAT THIS CANNOT DO

This is static analysis of code that will be handed to `exec`. It is one
layer of two, and the weaker one. In-process `exec` of adversarial Python is
not a solvable problem — the namespace shares an interpreter, a heap, an
environment and a file table with the application. The real boundary is the
process isolation in `python_runner._execute`; this layer exists to make
that boundary hard to reach rather than to be sufficient on its own.
"""

import ast
from typing import Optional

MAX_CODE_LENGTH = 32_768

# Modules a transformation may import. `pd`/`np` are here because the old
# allowlist had them; they are aliases, not modules, but removing them would
# be a behaviour change unrelated to this fix.
ALLOWED_IMPORTS = frozenset(["pandas", "pd", "numpy", "np", "re", "datetime", "math"])

# Names that must never be referenced, even though most are already absent
# from the sandbox namespace. Belt and braces: a name that is absent produces
# a confusing NameError at runtime, whereas rejecting it here produces a clear
# message before anything executes.
BLOCKED_NAMES = frozenset([
    "eval", "exec", "compile", "open", "input", "breakpoint",
    "globals", "locals", "vars", "dir", "help", "memoryview",
    "getattr", "setattr", "delattr", "hasattr", "super", "object",
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "importlib", "builtins", "pickle", "shelve", "marshal", "ctypes",
    "threading", "multiprocessing", "signal", "gc", "inspect", "types",
    "code", "codeop", "runpy", "tempfile", "atexit", "traceback",
])

# `to_*` methods that stay in memory. Everything else beginning with `to_` is
# an export — to_csv, to_pickle, to_sql, to_excel, to_parquet, to_hdf,
# to_feather, to_clipboard, to_gbq, to_stata — and is rejected by the prefix
# rule below without needing to be enumerated.
SAFE_TO_METHODS = frozenset([
    "to_dict", "to_list", "to_numpy", "to_frame", "to_series", "to_records",
    "to_datetime", "to_numeric", "to_timedelta", "to_period", "to_timestamp",
    "to_string", "to_flat_index", "to_pydatetime", "to_pytimedelta",
    "to_native_types", "to_julian_date", "to_orginal", "to_bytes",
])

# Attribute names rejected outright. Every one is a file, network, database or
# deserialisation entry point, or an expression evaluator.
BLOCKED_ATTRS = frozenset([
    # Deserialisation and persistence.
    "load", "loads", "save", "savez", "savez_compressed", "dump", "dumps",
    "memmap", "fromfile", "tofile", "genfromtxt", "loadtxt", "savetxt",
    "fromregex", "frombuffer", "getbuffer", "setbuffer",
    # Expression evaluation. pandas' own parser is restricted, but it is
    # still a code-execution surface and no generated transformation needs
    # it — ordinary indexing does the same work.
    "eval", "query", "exec", "compile",
    # Process, import and introspection surfaces reachable as attributes.
    "system", "popen", "spawn", "fork", "execv", "execve", "kill",
    "import_module", "reload", "find_spec", "get_data",
    "mro", "subclasses", "register", "unregister",
])

# `read_*` is rejected wholesale by prefix: read_csv, read_pickle, read_sql,
# read_json, read_excel, read_parquet, read_html, read_hdf, read_feather,
# read_gbq, read_orc, read_sas, read_spss, read_stata, read_xml, read_fwf,
# read_table, read_clipboard. None has any place here — the DataFrame to
# transform arrives as `df`, already loaded, already tenant-scoped.
BLOCKED_ATTR_PREFIXES = ("read_", "from_file", "open_")

_MSG_TOO_LONG = "Code rejected: the transformation exceeds the maximum allowed length."
_MSG_SYNTAX = "Code rejected: the transformation is not valid Python."
_MSG_IMPORT = "Code rejected: that import is not available in transformations."
_MSG_NAME = "Code rejected: that name is not available in transformations."
_MSG_PRIVATE = (
    "Code rejected: private attributes are not available in transformations. "
    "Use df['column_name'] to reach a column whose name starts with '_'."
)
_MSG_IO = (
    "Code rejected: transformations cannot read or write files, databases, or "
    "the network. The input data is already provided as `df`."
)


class PythonGuardResult:
    __slots__ = ("ok", "error")

    def __init__(self, ok: bool, error: Optional[str] = None):
        self.ok = ok
        self.error = error


def _is_private_attr(name: str) -> bool:
    """Attributes: ANY leading underscore is rejected.

    Strict on purpose. `__class__` and friends are the escape route, but
    single-underscore internals (`df._mgr`, `df._data`) hand back live
    internal objects that exist to be traversed, and no generated
    transformation has a reason to touch one. An underscore-prefixed COLUMN is
    still reachable as `df['_internal']`, which is a subscript, not an
    attribute — so the restriction costs nothing real.
    """
    return bool(name) and name.startswith("_")


def _is_private_name(name: str) -> bool:
    """Variables: only DUNDERS are rejected.

    This is deliberately looser than the attribute rule, and the asymmetry is
    the point. A local variable called `_rows` cannot escape anything — it is
    a slot in a namespace that holds only df, pd, np and the safe builtins.
    Meanwhile `for _, row in df.iterrows()` is idiomatic pandas (this repo's
    own `_serialize_df` is written that way), and a `_`-prefixed temporary is
    ordinary style. Rejecting those broke four legitimate transformations in
    testing and bought no security: what a Name can actually reach that
    matters is `__builtins__`, and that is a dunder.
    """
    return bool(name) and name.startswith("__") and name.endswith("__")


def _attr_is_io(attr: str) -> bool:
    if attr in BLOCKED_ATTRS:
        return True
    if attr.startswith(BLOCKED_ATTR_PREFIXES):
        return True
    if attr.startswith("to_") and attr not in SAFE_TO_METHODS:
        return True
    return False


def validate(code: str) -> PythonGuardResult:
    """Validate transformation code before it is executed.

    Rejection messages name the CATEGORY of rule broken and never the
    offending identifier, the list it appeared on, or the parser. These
    strings are returned as an HTTP 400 detail and fed back into the agent's
    LLM context, so a message that echoed the blocked name would let anything
    iterating against it enumerate the rules one probe at a time — and an LLM
    retrying on feedback does exactly that by design, without needing to be
    adversarial about it. The categories are still specific enough for a
    legitimate author to fix their code.
    """
    if code is None or not code.strip():
        return PythonGuardResult(False, _MSG_SYNTAX)

    if len(code) > MAX_CODE_LENGTH:
        return PythonGuardResult(False, _MSG_TOO_LONG)

    try:
        tree = ast.parse(code)
    except SyntaxError:
        # The parser's own message can quote the offending source line back.
        # That is fine for a human debugging their own code and wrong to hand
        # to an automated caller, so it is dropped.
        return PythonGuardResult(False, _MSG_SYNTAX)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    return PythonGuardResult(False, _MSG_IMPORT)
                if _is_private_name(alias.asname or ""):
                    return PythonGuardResult(False, _MSG_PRIVATE)

        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                return PythonGuardResult(False, _MSG_IMPORT)
            for alias in node.names:
                if _is_private_name(alias.name) or _is_private_name(alias.asname or ""):
                    return PythonGuardResult(False, _MSG_PRIVATE)

        elif isinstance(node, ast.Name):
            # Dunders only -- see _is_private_name on why variables are
            # treated differently from attributes.
            if _is_private_name(node.id):
                return PythonGuardResult(False, _MSG_PRIVATE)
            if node.id in BLOCKED_NAMES:
                return PythonGuardResult(False, _MSG_NAME)

        elif isinstance(node, ast.Attribute):
            # Checked on the attribute NAME itself, at every level of a
            # chain, rather than on what it is being read from. That is the
            # whole difference from the old check: `a.b.__class__` has an
            # Attribute (not a Name) as its value, which is precisely the
            # case the old `isinstance(node.value, ast.Name)` skipped.
            if _is_private_attr(node.attr):
                return PythonGuardResult(False, _MSG_PRIVATE)
            if _attr_is_io(node.attr):
                return PythonGuardResult(False, _MSG_IO)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _is_private_name(node.name):
                return PythonGuardResult(False, _MSG_PRIVATE)

        elif isinstance(node, ast.arg):
            if _is_private_name(node.arg):
                return PythonGuardResult(False, _MSG_PRIVATE)

        elif isinstance(node, ast.keyword):
            # `func(**{'__class__': x})` and `open(file=...)`-style keyword
            # smuggling. node.arg is None for **kwargs, which is caught by
            # the Name/Dict contents instead.
            if node.arg and _is_private_name(node.arg):
                return PythonGuardResult(False, _MSG_PRIVATE)

        elif isinstance(node, ast.Constant):
            # A private name reached by string is still a private name:
            # `getattr` is blocked, but pandas and numpy both expose
            # attribute-by-string paths, and a bare dunder string in
            # transformation code has no legitimate use.
            if isinstance(node.value, str) and node.value.startswith("__") \
                    and node.value.endswith("__") and len(node.value) > 4:
                return PythonGuardResult(False, _MSG_PRIVATE)

    return PythonGuardResult(True, None)
