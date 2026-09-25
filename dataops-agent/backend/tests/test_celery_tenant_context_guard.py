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
import re

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
        if not any(marker in combined for marker in TENANT_CONTEXT_MARKERS):
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
