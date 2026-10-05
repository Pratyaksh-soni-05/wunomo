"""Standing guard test (Integration Phase 5, per GOTCHAS' own overdue note):
every Celery task registered on celery_app -- every beat_schedule entry
and every @celery_app.task/@shared_task definition, found the same way
Celery itself finds them (its own task registry, not a hand-maintained
list here that could itself drift) -- must establish real tenant context
(tenant_context/async_tenant_context/with_tenant_context) somewhere in
its call path, or be on the explicit, named allowlist below with a
reason.

Six confirmed, independently-discovered instances of "this task/route
never established tenant context, so RLS silently hid every row, on
every run, forever, with no error" is what makes this overdue rather
than optional (see GOTCHAS): modules/orchestration/supervisor.py,
services/tasks.py's check_scheduled_agent_tasks/fire_scheduled_task
(Item 1), services/tasks.py's advance_active_tasks/advance_one_task
("C4"), services/cicd_monitor.py's check_post_deploy_health, and
main.py's GET /health/tasks (not Celery-scheduled, out of this guard's
scope by construction -- see test_rls_coverage_guard.py's sibling
note and the FastAPI-route half of GOTCHAS' proposed guard, not yet
built).

STATIC, NOT LIVE -- a real but bounded limitation, named plainly rather
than hidden: this checks that the right call reaches the source code
text of the task function or a function it calls one level deep in the
same module, not that the call actually executes with the right
argument at runtime. Every instance found this session needed a real
seeded row and a real call to catch what code reading alone did not
(Test C, C4, the cicd_monitor fix) -- this guard is the cheap, always-on
first line, not a replacement for that standard. It exists to make the
NEXT instance of this exact shape impossible to miss for free, on every
test run, not to certify correctness of the policy itself.
"""
import inspect
import io
import re
import tokenize

import pytest

# Reason each entry is exempt, stated plainly so a future reader (or a
# future addition to this set) has to justify itself, not just extend a
# bare list:
#   anchor_audit_chains -- reads via ADMIN_DATABASE_URL as the maintenance
#     role on purpose (see services/audit_anchor.py); it is SUPPOSED to
#     see every tenant, unscoped, which is the opposite of what
#     tenant_context exists for.
#   run_anomaly_detection / generate_daily_reports -- confirmed, live-read
#     placeholders (services/tasks.py: "Placeholder — full implementation
#     in Phase 3", log.info() only, zero DB access) -- nothing to scope
#     because nothing is read or written yet. Remove from this allowlist
#     the day either gains a real body.
ALLOWLISTED_TASKS = {
    "services.tasks.anchor_audit_chains":
        "reads via ADMIN_DATABASE_URL as the maintenance role by design (services/audit_anchor.py)",
    "services.tasks.run_anomaly_detection":
        "confirmed no-op placeholder, zero DB access (services/tasks.py)",
    "services.tasks.generate_daily_reports":
        "confirmed no-op placeholder, zero DB access (services/tasks.py)",
}

TENANT_CONTEXT_MARKERS = ("tenant_context(", "async_tenant_context(", "with_tenant_context")


def _strip_comments_and_strings(source: str) -> str:
    """Found 2026-10-04 (Item #16 follow-up): the main check below used to
    do a plain substring search over raw source text, which a comment
    mentioning "tenant_context(" -- explaining why a task does NOT need it,
    say -- or a string literal containing the same text would satisfy
    exactly as well as a real `with tenant_context(...):` statement. No
    real task was ever caught by this (every one genuinely calls one of
    the three markers for real -- see each test function below), but the
    guard itself was gameable, which defeats its own point: a future task
    with a comment-only mention would pass this guard while establishing
    no real context at all.

    Tokenizes the source and reproduces it with every COMMENT and STRING
    token (which covers docstrings -- Python has no separate docstring
    token) blanked out, so a marker only counts when it appears in actual
    code: a name followed by `(`, or (for `with_tenant_context`, used as a
    decorator/bare name rather than a call) a bare name token. NAME/OP
    tokens -- the only place a real call or decorator can appear -- are
    left untouched.
    """
    out = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok_type, tok_string, _, _, _ in tokens:
            if tok_type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok_string)
    except tokenize.TokenError:
        # A snippet that doesn't tokenize cleanly on its own (e.g. a
        # function body dedented without its def) falls back to the raw
        # text rather than silently returning an empty, always-failing
        # string -- same fail-loud-not-silent standard as the rest of this
        # file's checks.
        return source
    # No separator: a real call's NAME and "(" tokens are adjacent in the
    # original source (tenant_context(...), not tenant_context (...), and
    # the old substring check already required that exact adjacency) --
    # joining with "" preserves that, where joining with a space would
    # silently break every real match this guard exists to find.
    return "".join(out)


def _establishes_tenant_context(combined_source: str) -> bool:
    """The real check, now against code with comments and string literals
    removed -- see _strip_comments_and_strings' docstring for why."""
    code_only = _strip_comments_and_strings(combined_source)
    return any(marker in code_only for marker in TENANT_CONTEXT_MARKERS)


def _discover_registered_tasks():
    """Every task Celery itself knows about, found the same way a real
    worker/beat process finds them -- importing celery_app.conf.include's
    modules and reading celery_app.tasks after finalize(), not a
    hand-maintained name list in this file that could itself drift from
    the real registry (exactly the "second list describing what
    ALL_TOOLS/the real registry already describes" pattern GOTCHAS names
    three separate times elsewhere in this codebase)."""
    import importlib
    from services.celery_app import celery_app

    for module_name in celery_app.conf.include:
        importlib.import_module(module_name)
    celery_app.finalize()

    tasks = {}
    for name, task in celery_app.tasks.items():
        if name.startswith("celery."):
            continue
        fn = getattr(task, "__wrapped__", None) or task.run
        tasks[name] = fn
    return tasks


def _same_module_helper_source(fn) -> str:
    """One hop of call-path expansion: every top-level function in fn's
    own module that fn's source textually calls by name, concatenated.
    Covers every current task -- each one either references
    tenant_context/async_tenant_context/with_tenant_context directly in
    its own body (including nested closures, which inspect.getsource
    already includes), or calls exactly one same-module helper that
    does (e.g. advance_active_tasks -> _select_tasks_to_advance,
    check_all_freshness -> _check_freshness). A task that buried its
    context establishment two hops down would need this deepened --
    matches the real shape of every task in this codebase today, not a
    theoretical ceiling."""
    own_source = inspect.getsource(fn)
    module = inspect.getmodule(fn)
    if module is None:
        return own_source

    module_source = inspect.getsource(module)
    called_names = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", own_source))

    helper_sources = []
    for name, member in inspect.getmembers(module, inspect.isfunction):
        if name in called_names and inspect.getmodule(member) is module:
            try:
                helper_sources.append(inspect.getsource(member))
            except (OSError, TypeError):
                continue
    return own_source + "\n" + "\n".join(helper_sources)


def test_every_registered_celery_task_establishes_tenant_context_or_is_allowlisted():
    tasks = _discover_registered_tasks()
    assert len(tasks) >= 14, (
        f"Expected at least 14 registered Celery tasks (the full sweep this "
        f"session found), got {len(tasks)}: {sorted(tasks)}. A number this "
        f"low means task discovery itself is broken (an include module "
        f"failed to import), not that the task count shrank -- check that "
        f"before trusting a 'pass' below."
    )

    violations = []
    for name, fn in tasks.items():
        if name in ALLOWLISTED_TASKS:
            continue
        combined = _same_module_helper_source(fn)
        if not _establishes_tenant_context(combined):
            violations.append(
                f"{name} ({fn.__module__}.{fn.__qualname__}): no "
                f"tenant_context/async_tenant_context/with_tenant_context found "
                f"in its own source or a same-module function it calls"
            )

    assert not violations, (
        "Celery task(s) with no detectable tenant-context establishment "
        "(this is exactly the bug shape found 5 times this integration pass "
        "-- see GOTCHAS):\n  " + "\n  ".join(violations)
    )


def test_allowlist_entries_are_still_real_and_still_justify_their_exemption():
    """The allowlist is a claim, not just an exclusion -- confirms each
    entry still exists as a registered task (an allowlist entry for a
    renamed/removed task would silently stop meaning anything) and that
    anchor_audit_chains genuinely still uses ADMIN_DATABASE_URL rather
    than having quietly grown a tenant_context call that would make its
    exemption stale."""
    tasks = _discover_registered_tasks()
    for name in ALLOWLISTED_TASKS:
        assert name in tasks, f"Allowlisted task {name!r} is no longer registered -- remove this entry"

    # anchor_audit_chains delegates to services.audit_anchor.anchor_audit_chains,
    # a different module -- checked directly rather than via the same-module
    # one-hop helper above (that helper is scoped to the main guard's shape,
    # not this cross-module case). The real ADMIN_DATABASE_URL usage lives
    # in compute_anchors(), one call further in -- checking the whole
    # implementing module rather than chasing another hop.
    import services.audit_anchor
    anchor_impl_source = inspect.getsource(services.audit_anchor)
    assert "ADMIN_DATABASE_URL" in anchor_impl_source, (
        "anchor_audit_chains's allowlist reason (reads via ADMIN_DATABASE_URL "
        "as the maintenance role) no longer matches its source -- re-examine "
        "whether it still needs the exemption"
    )


# ── Guard-hardening negative control (2026-10-04, Item #16 follow-up) ──────
#
# Investigated whether cicd.run_ci_pipeline (services/cicd_tasks.py) was a
# 7th instance of this exact bug shape. It is not: it genuinely wraps its
# whole body in `with tenant_context(tenant_id):` (cicd_tasks.py:338-340),
# confirmed by reading the function in full, not a partial read that
# stopped before that line. So there is no real "pre-fix run_ci_pipeline"
# to demonstrate this against -- the two tests below instead prove the
# guard's OWN detection logic directly, with synthetic source snippets
# standing in for "a task that looks covered but isn't": the comment-only
# case is exactly the shape a future task could ship with and still pass
# the naive substring check this guard used to run.

_COMMENT_ONLY_SNIPPET = '''
def fake_task(tenant_id):
    # NOTE: older versions of this task called tenant_context(tenant_id)
    # here, but it turned out to be unnecessary for this query -- removed.
    return query_something(tenant_id)
'''

_DOCSTRING_ONLY_SNIPPET = '''
def fake_task(tenant_id):
    """Establishes tenant context via async_tenant_context() before doing
    any real work."""
    return query_something(tenant_id)
'''

_REAL_CALL_SNIPPET = '''
def fake_task(tenant_id):
    with tenant_context(tenant_id):
        return query_something(tenant_id)
'''


def _naive_pre_hardening_check(combined_source: str) -> bool:
    """Reproduces exactly what this guard's main check did before the
    2026-10-04 hardening: a plain substring search over the raw,
    unstripped source. Kept here only to prove the negative control below
    -- the real guard never calls this."""
    return any(marker in combined_source for marker in TENANT_CONTEXT_MARKERS)


def test_naive_substring_check_is_fooled_by_a_comment_or_docstring():
    """The negative control: shows the OLD approach (still available as
    _naive_pre_hardening_check, reproduced verbatim from the pre-hardening
    source) would have wrongly accepted both synthetic snippets below as
    'establishes tenant context', despite neither one actually calling
    anything. This is the exact gameability the hardening closes."""
    assert _naive_pre_hardening_check(_COMMENT_ONLY_SNIPPET) is True, (
        "negative control itself is broken: the naive check should wrongly "
        "accept a comment-only mention, demonstrating the bug it has"
    )
    assert _naive_pre_hardening_check(_DOCSTRING_ONLY_SNIPPET) is True, (
        "negative control itself is broken: the naive check should wrongly "
        "accept a docstring-only mention, demonstrating the bug it has"
    )


def test_hardened_check_rejects_a_comment_or_docstring_but_accepts_a_real_call():
    """Passing half of the same negative control: the hardened
    _establishes_tenant_context (comments/strings stripped via tokenize)
    correctly rejects both snippets above, and still accepts the one with
    a genuine `with tenant_context(...):` statement -- proving the fix
    doesn't just reject everything."""
    assert _establishes_tenant_context(_COMMENT_ONLY_SNIPPET) is False
    assert _establishes_tenant_context(_DOCSTRING_ONLY_SNIPPET) is False
    assert _establishes_tenant_context(_REAL_CALL_SNIPPET) is True


@pytest.mark.asyncio
async def test_run_ci_pipeline_genuinely_establishes_tenant_context_live():
    """Live proof, not just a source-text check, that cicd.run_ci_pipeline
    (the task the Item #16 webhook fix queues) actually scopes its queries
    to the right tenant: seed a real commit for a real tenant, call the
    task's own function directly (bypassing Celery's broker, same pattern
    test_cicd_no_duplicate_approval.py already uses), and confirm its
    first query finds the row -- the exact failure mode
    ("cicd.commit_not_found", a silent no-op) every other instance of this
    bug shape in this codebase produces when context is missing."""
    import asyncio
    import uuid as _uuid
    from httpx import AsyncClient, ASGITransport
    import main as main_module
    from models.cicd import PipelineCommit, CICDStatus
    from services.tenant_context import tenant_session
    from services import cicd_tasks

    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        reg = await client.post("/api/v1/auth/register", json={
            "email": f"guardlive-{_uuid.uuid4().hex[:8]}@example.com",
            "password": "test1234", "full_name": "Guard Live",
            "tenant_name": f"Guard Live Corp {_uuid.uuid4().hex[:6]}",
        })
    tenant_id = reg.json()["tenant_id"]

    commit_id = str(_uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        commit = PipelineCommit(
            id=commit_id, tenant_id=tenant_id, pipeline_id=None,
            commit_sha="a" * 40, branch="main", author="guard-live-test",
            repo_url="", changed_files=[], commit_message="guard live test",
            ci_status=CICDStatus.pending, check_results={}, risk_score=0.0,
        )
        db.add(commit)
        await db.commit()

    # The real task function, called directly -- same pattern
    # test_cicd_no_duplicate_approval.py already uses. Wrapped in
    # to_thread because the task body calls asyncio.run() internally
    # (cicd_tasks.py:340), which raises if invoked from a loop that's
    # already running, exactly the one this test function is in.
    await asyncio.to_thread(cicd_tasks.run_ci_pipeline.run, commit_id, tenant_id)

    async with tenant_session(tenant_id) as db:
        from sqlalchemy import select
        result = await db.execute(select(PipelineCommit).where(PipelineCommit.id == commit_id))
        refreshed = result.scalar_one()

    # If tenant context had NOT been established, the task's own first
    # query ("SELECT ... WHERE id = commit_id") would see zero rows under
    # RLS and log cicd.commit_not_found, leaving ci_status stuck at
    # "pending" forever. Reaching "running" or past it proves the task's
    # query found the row -- context was real, not just textually present.
    assert refreshed.ci_status != CICDStatus.pending, (
        "run_ci_pipeline left ci_status at 'pending' -- its own first "
        "query never found the commit, meaning tenant context was not "
        "actually established despite the source-level check passing"
    )
