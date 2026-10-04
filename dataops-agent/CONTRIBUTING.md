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

## Secret scanning

If secret-scan fails on your PR: remove the secret. If it is a verified
false positive, add that exact fingerprint to `.gitleaksignore` with a
comment saying why, and say so in the PR description. Never add path or
wildcard rules.

## Workflow

Before switching branches, run `git status` and commit or stash uncommitted
work. Branch switches carry uncommitted changes across and it is easy to
commit them to the wrong branch.

## Test-seeding gotchas

Seeding a RUNNING task in tests: the live Celery beat reaps plain RUNNING
tasks within a minute. Use a PAUSED_* status or stop celery_beat first.

Seeding a SUPERVISOR_RUNNING task for UI verification: it needs a real
TaskStep row (step_index=0, status=RUNNING) in the same seed, or
`current_step` comes back null and the step line falls back to "Waiting
to start" while the badge still says "running" — a visibly contradictory
render that looks like a real bug but is only a seeding gap. The real
orchestration path (`modules/orchestration/supervisor.py`) always creates
the TaskStep in the same commit as the Task, before the status ever
flips to SUPERVISOR_RUNNING (see `_run_ready_wave`), so this combination
can't happen against real data — confirmed from code, not just assumed,
after exactly this contradiction showed up in seeded Command Center
screenshots (2026-10-02).

## Connecting GitHub (CI/CD webhook)

Security Master Ranking Item #16. Each pipeline has its own webhook
secret — there is no single, shared secret for the whole deployment.

1. Generate the secret: `POST /api/v1/pipelines/{pipeline_id}/webhook-secret`
   (requires the `pipelines.create` capability — Owner/Admin/Data Engineer,
   not Viewer). The response's `webhook_secret` field is shown exactly
   once; it is never retrievable again afterward. Calling this a second
   time rotates the secret and invalidates the old value immediately.
2. In the repository's GitHub settings → Webhooks → Add webhook:
   - **Payload URL**: `https://<your-host>/api/v1/cicd/webhook/{pipeline_id}`
     (the same `webhook_secret` response includes this exact URL).
   - **Content type**: `application/json`.
   - **Secret**: the generated value from step 1.
   - **Which events**: `push` (`event = push`) — nothing else is handled.
   - **SSL verification**: on. Leave it on; this endpoint does not exist
     to be reachable over plaintext.
3. Existing pipelines created before this fix have no secret yet — their
   webhook is refused (the identical generic 401 every other rejection
   reason gets) until step 1 is run for them.

The old, global `POST /api/v1/cicd/webhook` (no pipeline id) is retired
and returns 410 — it is not a fallback for a pipeline with no secret
configured.
