"""Standing guard (Security Master Ranking Item #16 follow-up, 2026-10-04):
no module under api/ or services/ may reference ADMIN_DATABASE_URL -- that
setting names dataops_user, a superuser/BYPASSRLS role, and the whole
point of this codebase's RLS design is that no request-serving path ever
runs as a role that can silently bypass it (see CLAUDE.md's Auth/tenancy
section). The one legitimate exception today is services/audit_anchor.py,
a once-daily Celery beat job, not a path a stranger's HTTP request can
reach -- not a precedent for using the admin role on a request path, a
documented, allowlisted carve-out for a job that genuinely needs to read
every tenant unscoped.

This guard exists because api/v1/cicd.py's webhook handler briefly did
exactly the wrong thing: resolve_pipeline_for_webhook() opened a raw
ADMIN_DATABASE_URL connection directly inside the unauthenticated webhook
request path, to resolve a pipeline's tenant before any tenant context
existed. Fixed by moving that one cross-tenant read behind a SECURITY
DEFINER SQL function (migration f2a6f3d01f22) that dataops_app has EXECUTE
on and nothing else -- the admin role's bypass capability is still used,
but entirely encapsulated in a migration-reviewed, two-column,
single-row-by-primary-key function, never as a live connection string in
request-serving Python.

STATIC, COMMENT-AWARE -- deliberately not a plain substring search. A
naive `"ADMIN_DATABASE_URL" in source` check would wrongly flag
api/v1/cicd.py and services/cicd_service.py themselves: both now contain
prose explaining that ADMIN_DATABASE_URL is NOT used there anymore,
which a plain substring check cannot distinguish from an actual
`settings.ADMIN_DATABASE_URL` reference. Tokenizes each file and strips
COMMENT/STRING tokens before searching -- same technique, same reasoning,
as test_celery_tenant_context_guard.py's own 2026-10-04 hardening (see
that file and docs/context/GOTCHAS.md's Item #16 entry).
"""
import io
import pathlib
import tokenize

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("api", "services")

# Reason stated plainly, same convention as every other allowlist in this
# codebase (test_celery_tenant_context_guard.py, test_rls_coverage_guard.py):
#   audit_anchor.py -- reads via ADMIN_DATABASE_URL as the maintenance role
#   by design (services/audit_anchor.py): a once-daily Celery beat job,
#   never a request-serving path, and already independently guarded by
#   test_celery_tenant_context_guard.py's own allowlist for the same file.
ADMIN_URL_ALLOWLIST = {
    "services/audit_anchor.py":
        "once-daily Celery beat maintenance job, reads cross-tenant by "
        "design as the admin role -- not a request-serving path",
}


def _code_only(source: str) -> str:
    """Strip COMMENT and STRING tokens so a marker only counts when it
    appears in real code, not prose explaining its absence. Falls back to
    the raw source on a tokenize failure rather than silently passing
    (fail loud, not silent)."""
    out = []
    try:
        for tok_type, tok_string, _, _, _ in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok_type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok_string)
    except tokenize.TokenError:
        return source
    return "".join(out)


def _python_files_under(*dirnames: str):
    for dirname in dirnames:
        root = BACKEND_ROOT / dirname
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _references_admin_url(source: str) -> bool:
    return "ADMIN_DATABASE_URL" in _code_only(source)


def test_no_request_serving_module_references_admin_database_url():
    violations = []
    for path in _python_files_under(*SCANNED_DIRS):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel in ADMIN_URL_ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        if _references_admin_url(source):
            violations.append(rel)

    assert not violations, (
        "Module(s) under api/ or services/ reference ADMIN_DATABASE_URL "
        "(a superuser/BYPASSRLS role) outside the allowlist -- this is "
        "exactly the shape that let a webhook request path briefly run as "
        "the admin role (see docs/context/GOTCHAS.md, Item #16):\n  "
        + "\n  ".join(violations)
    )


def test_allowlist_entries_are_still_real_and_still_reference_admin_url():
    """The allowlist is a claim, not just an exclusion -- confirms each
    entry still exists and still genuinely uses ADMIN_DATABASE_URL, so a
    stale entry (the file renamed, or the usage removed) doesn't silently
    keep granting an exemption nothing needs anymore."""
    for rel, _reason in ADMIN_URL_ALLOWLIST.items():
        path = BACKEND_ROOT / rel
        assert path.is_file(), f"Allowlisted path {rel!r} no longer exists -- remove this entry"
        source = path.read_text(encoding="utf-8")
        assert _references_admin_url(source), (
            f"Allowlisted {rel!r} no longer references ADMIN_DATABASE_URL in real code -- "
            "its exemption reason no longer matches its source, remove the entry"
        )


def test_naive_substring_check_would_wrongly_flag_the_fixed_files():
    """Negative control: the two files this guard's own docstring names
    (cicd.py, cicd_service.py) now contain prose explaining ADMIN_DATABASE_URL
    is NOT used -- proving a plain substring check would have produced a
    false positive on the very files that document the fix, which is why
    this guard strips comments/strings instead."""
    cicd_py = (BACKEND_ROOT / "api" / "v1" / "cicd.py").read_text(encoding="utf-8")
    cicd_service_py = (BACKEND_ROOT / "services" / "cicd_service.py").read_text(encoding="utf-8")

    assert "ADMIN_DATABASE_URL" in cicd_py, "fixture assumption broken: expected a prose mention in cicd.py"
    assert "ADMIN_DATABASE_URL" in cicd_service_py, "fixture assumption broken: expected a prose mention in cicd_service.py"

    # The naive check (what this guard does NOT do) would flag both --
    # the comment-aware check correctly clears both.
    assert _references_admin_url(cicd_py) is False
    assert _references_admin_url(cicd_service_py) is False
