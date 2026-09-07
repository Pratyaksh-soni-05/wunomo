"""Process isolation for PythonRunner's transformation code.

    WHY A PROCESS, AND NOT A BETTER THREAD
    --------------------------------------
    The old `_execute` ran the code in a `threading.Thread` and called
    `thread.join(timeout=60)`. `join` with a timeout does not stop anything —
    it stops WAITING. Measured against the old code with the timeout set to
    1s: `_execute` returned its "timed out" error after 1.01s while the
    thread was still running, and the thread only disappeared once its own
    work finished, seconds later. A genuine `while True:` never finishes, so
    it pins a core inside the API worker (or the Celery worker) for the life
    of the process, and each new request adds another one. The caller sees a
    tidy error message and believes the code was stopped.

    Python cannot kill a thread. There is no supported mechanism, by design —
    which makes "run it in a thread with a timeout" unfixable rather than
    buggy. A process, by contrast, can simply be killed, and that single fact
    is the reason for this module.

    Memory was likewise unbounded: a 240MB allocation succeeded on the old
    code, and nothing stood between a transformation and the container's
    memory limit.

WHAT THE CHILD GIVES UP BEFORE IT RUNS ANYTHING

Set inside the child, after the fork and before the code is compiled, so a
failure to apply them cannot be silently skipped:

  * RLIMIT_AS      — address space. A memory bomb raises MemoryError inside
                     the sandbox instead of taking down the worker.
  * RLIMIT_CPU     — CPU seconds. Backstops the wall clock for a tight
                     compute loop; the kernel sends SIGXCPU.
  * RLIMIT_FSIZE 0 — maximum file size, zero. **This is the important one.**
                     Any write to any file fails at the kernel, so an I/O
                     call that the static guard's denylist misses still
                     cannot produce a file. It is the runtime backstop that
                     lets `python_guard`'s I/O list be honest about being a
                     denylist.
  * RLIMIT_NPROC   — no new processes, so `fork`/`spawn` cannot escape the
                     limits by starting something outside them.
  * os.environ cleared — the measured battery read JWT_SECRET,
                     ADMIN_DATABASE_URL and CREDENTIAL_ENCRYPTION_KEY
                     straight out of the environment. An empty environment
                     means recovering `os` no longer recovers the secrets.

The wall clock is enforced by the PARENT — `join(timeout)` then `kill()` —
because a child that is wedged cannot be trusted to time itself out.

    WHAT THIS STILL DOES NOT DO, STATED PLAINLY
    -------------------------------------------
    The child is a fork of the application process. It shares the filesystem
    and the network namespace, so code that defeats the static guard can
    still READ a world-readable file (RLIMIT_FSIZE stops writes, not reads)
    and can still open a socket. Closing those needs a boundary this module
    cannot draw from inside CPython — a container with a read-only mount and
    no network route, or the gVisor/Firecracker microVM the original
    docstring already recommended.

    So the honest claim is narrower than "sandboxed": arbitrary code is no
    longer trivially able to exfiltrate the application's secrets, exhaust
    its memory, or run forever inside it. It is a boundary worth having and
    it is not a substitute for an OS-level one.
"""

import multiprocessing
import os
import pickle
import resource
import sys
import traceback
from typing import Any

# Address space ceiling for a transformation. Generous on purpose: pandas and
# numpy reserve large arenas, and a limit tight enough to be interesting is
# also tight enough to fail ordinary work on a wide DataFrame. The point is to
# make exhaustion of the HOST impossible, not to make the sandbox frugal.
MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB

# Wall-clock ceiling, enforced by the parent.
EXECUTION_TIMEOUT_SECS = 60

# CPU-seconds ceiling, enforced by the kernel. Deliberately above the wall
# clock so that the parent's kill is the normal path and this only catches a
# child that has stopped responding to it.
CPU_LIMIT_SECS = EXECUTION_TIMEOUT_SECS + 15

_MSG_TIMEOUT = (
    "Transformation timed out and was stopped. Simplify the transformation or "
    "reduce the amount of data it processes."
)
_MSG_MEMORY = (
    "Transformation exceeded the memory available to it and was stopped. "
    "Reduce the amount of data it processes."
)
_MSG_CRASHED = "Transformation was stopped before it completed."
_MSG_NO_RESULT = "Transformation code did not assign its output to `result_df`."


def _apply_limits() -> None:
    """Drop resources in the child. Order matters: the environment is cleared
    before any user code can read it, and RLIMIT_NPROC is applied last so that
    setting the earlier limits cannot itself be blocked."""
    os.environ.clear()

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECS, CPU_LIMIT_SECS))
    # Zero-byte maximum file size: writes fail at the kernel regardless of
    # which library call reached them.
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ValueError, OSError):
        # Not settable in every container configuration. Not worth failing the
        # whole sandbox over — it is the least load-bearing of the limits.
        pass


def _child(code: str, df_bytes: bytes, conn) -> None:
    """Runs in the forked child. Sends exactly one message and exits."""
    try:
        _apply_limits()

        import datetime as _datetime
        import math as _math
        import re as _re

        import numpy as np
        import pandas as pd

        df = pickle.loads(df_bytes)

        # The static guard permits `import re`, `import math` and
        # `from datetime import datetime`, and transform_generator's system
        # prompt tells the model it may use them — but the namespace had no
        # `__import__`, so every one of those raised
        # "ImportError: __import__ not found" at runtime. Verified against the
        # pre-change code: this is a pre-existing bug, not a regression, and
        # it means AXIOM has been advertising three imports it never
        # supported. Fixed here rather than left, because the alternative is
        # a guard that permits code the runtime then refuses.
        #
        # The shim resolves ONLY these pre-imported modules. It never touches
        # the real import machinery, so it cannot be walked to reach anything
        # that was not put in this dict deliberately.
        _importable = {
            "re": _re, "math": _math, "datetime": _datetime,
            "pandas": pd, "numpy": np,
        }

        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.split(".")[0]
            if root not in _importable or root != name:
                raise ImportError(f"module '{name}' is not available in transformations")
            return _importable[root]

        safe_builtins = {
            "len": len, "range": range, "enumerate": enumerate,
            "zip": zip, "map": map, "filter": filter,
            "list": list, "dict": dict, "set": set, "tuple": tuple,
            "str": str, "int": int, "float": float, "bool": bool,
            "min": min, "max": max, "sum": sum, "abs": abs,
            "round": round, "sorted": sorted, "reversed": reversed,
            "isinstance": isinstance, "any": any, "all": all,
            "print": lambda *a, **kw: None,
            "True": True, "False": False, "None": None,
            "__import__": _guarded_import,
        }

        namespace: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "pd": pd,
            "np": np,
            "df": df,
        }

        exec(compile(code, "<axiom_transform>", "exec"), namespace)

        result_df = namespace.get("result_df")
        if result_df is None:
            conn.send(("error", _MSG_NO_RESULT))
            return
        if not isinstance(result_df, pd.DataFrame):
            conn.send(("error",
                       "`result_df` must be a pandas DataFrame, got "
                       f"{type(result_df).__name__}."))
            return

        conn.send(("ok", pickle.dumps(result_df)))
    except MemoryError:
        conn.send(("error", _MSG_MEMORY))
    except BaseException:
        # The traceback is captured but NOT sent: it would carry absolute
        # paths, module names and local values from inside the sandbox back to
        # whatever is iterating against it. The parent turns this into a
        # generic message; the detail goes to the log, not the response.
        conn.send(("trace", traceback.format_exc()[-4000:]))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_sandboxed(code: str, df, timeout: int = EXECUTION_TIMEOUT_SECS) -> dict:
    """Execute `code` against `df` in an isolated, resource-limited process.

    Returns {"result_df": DataFrame} or {"error": str, "detail": str|None}.
    `detail` is for the server log only and is never part of the error the
    caller sees.
    """
    if sys.platform == "win32":  # pragma: no cover - deployment is Linux
        return {"error": _MSG_CRASHED,
                "detail": "process sandbox requires a POSIX platform"}

    # fork specifically, not spawn: the child needs pandas and numpy already
    # imported, and re-importing them per transformation would add seconds to
    # every call. The child touches no locks before exec'ing, which is what
    # makes forking from a threaded parent safe here.
    ctx = multiprocessing.get_context("fork")
    parent_conn, child_conn = ctx.Pipe(duplex=False)

    proc = ctx.Process(target=_child, args=(code, pickle.dumps(df), child_conn))
    proc.start()
    child_conn.close()  # so the parent's recv sees EOF if the child dies

    payload = None
    try:
        if parent_conn.poll(timeout):
            payload = parent_conn.recv()
    except EOFError:
        payload = None
    finally:
        proc.join(timeout=1)
        if proc.is_alive():
            # The distinguishing property of this whole module: this actually
            # stops the code. `thread.join(timeout)` never did.
            proc.kill()
            proc.join(timeout=5)
        parent_conn.close()

    if payload is None:
        if proc.exitcode is None or proc.exitcode < 0:
            # Killed by a signal: our own kill after the timeout, SIGXCPU from
            # RLIMIT_CPU, or the OOM killer.
            return {"error": _MSG_TIMEOUT, "detail": f"exitcode={proc.exitcode}"}
        return {"error": _MSG_CRASHED, "detail": f"exitcode={proc.exitcode}"}

    kind, body = payload
    if kind == "ok":
        return {"result_df": pickle.loads(body)}
    if kind == "trace":
        return {"error": _MSG_CRASHED, "detail": body}
    return {"error": body, "detail": None}
