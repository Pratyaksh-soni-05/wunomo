# Contributing

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
Guard-test wiring in `.github/workflows/guard-tests.yml` currently runs only
the two standing guard tests on every push/PR — the full suite
(`docker compose exec backend python -m pytest tests/ -v --tb=short`, see
root `CLAUDE.md`) is not yet wired into CI, so until it is, running it
yourself before a larger or riskier change is still on you.

## Workflow

Before switching branches, run `git status` and commit or stash uncommitted
work. Branch switches carry uncommitted changes across and it is easy to
commit them to the wrong branch.
