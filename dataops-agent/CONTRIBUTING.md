# Contributing

See `docs/context/WORKING_AGREEMENT.md` for how a session is expected to
work on this repo — branching, lanes, what you decide yourself, and the
definition of done for a PR.

## Before opening a PR: fast local test subset

Run this from `dataops-agent/` before pushing:

```bash
./scripts/fast_pretest.sh
```

It runs, against the running `docker compose` stack:

- `tests/test_rls_coverage_guard.py` and `tests/test_celery_tenant_context_guard.py`
  (the two standing guard tests — see `docs/context/STAGE_OWNERSHIP.md`), always.
- Any test file your branch's diff against `master` touches directly.
- For any other changed `backend/*.py` file, its same-named test
  (`services/foo.py` -> `tests/test_foo.py`) if one exists.

Takes well under a minute (~30-40s typical). Verified 2026-09-27: 25 tests,
33.57s.

**This is a fast sanity check, not a substitute for the full suite.** It
won't catch a regression in code you didn't touch, or one only covered by a
test whose name doesn't match the changed file's basename by convention.
The full suite runs in `.github/workflows/full-suite.yml` on every push to
master, nightly, and on demand. Before asking for a merge, trigger it on
your own branch (Actions -> Full Suite -> Run workflow -> choose your
branch) and put the run link in the PR description. `guard-tests.yml`
remains the fast per-push check and runs only the two guard tests. Running
the whole suite locally is still useful for risky changes but is slow on a
database with accumulated data.

## Workflow

Before switching branches, run `git status` and commit or stash uncommitted
work. Branch switches carry uncommitted changes across and it is easy to
commit them to the wrong branch.

## Test-seeding gotchas

Seeding a RUNNING task in tests: the live Celery beat reaps plain RUNNING
tasks within a minute. Use a PAUSED_* status or stop celery_beat first.
