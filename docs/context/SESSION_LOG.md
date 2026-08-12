# Session Log

Newest entry first. This file exists because chat history does not survive
a Claude account migration, but git does — see
`docs/context/WUNOMO_MASTER_CONTEXT.md` for the standing product/business
snapshot and `CLAUDE.md` for the exhaustive, stage-by-stage engineering
record (Status Table + Known Gotchas). This file is the connective layer
between the two: what happened, in what order, and why — the part that's
otherwise only in someone's head or a chat transcript.

---

## 2026-08-12 — Item 6 stage 7 wrap-up, a beginner self-test guide, and the first account-migration checkpoint

### Context

Two things converged this session. First, "Item 6" (long-running AXIOM
tasks, a 7-stage feature) reached its final stage — visibility and role
gating — closing an arc that started with a schema migration and ended
with a working Tasks screen in the UI. Second, and the reason this file
now exists at all: the user migrated to a new Claude account (the old one
was tied to a college email about to expire, and Anthropic does not
transfer chat history between personal accounts). Rather than lose every
decision that only ever lived in a conversation, the user set a rule for
this project going forward: **context that lives in a chat is temporary;
context that lives in git is permanent.** This session is the first real
exercise of that rule — a full checkpoint of everything unsaved, written
into the repo so it survives independently of any Claude account,
subscription, or machine.

### Done

- **Item 6 stage 7 (visibility + role gating) shipped and closed out the
  whole Item 6 arc.** Full stage-by-stage detail (all 7 stages, live
  verification transcripts, exact test counts) lives in `CLAUDE.md`'s
  Status Table under "Item 6 stage 7" — not duplicated here. Short
  version: a real Tasks nav item + list screen, a per-task step timeline
  reusing the CI/CD screen's existing Table+Badge pattern rather than
  inventing a new one, a topbar "N active" counter proven live (created a
  task via a direct API call while the browser sat on `/dashboard` the
  whole time, watched the counter advance on its own 20-second poll with
  zero navigation), a chat-inline "Started task" card, and best-effort
  notification wiring at 8 real task-lifecycle transitions. Backend: 394
  tests passing. Committed as `83d3870`.
- **Found and fixed one real bug during that stage's own live
  verification**: the task detail page rendered an infinite loading
  skeleton on a 403 or any other load failure, with no way out for the
  user. Fixed with a proper `taskQuery.isError` branch in
  `frontend/src/app/(app)/tasks/[id]/page.tsx` — a clear "Can't open this
  task" state with a link back to the list. Re-verified live against the
  same failure case (a Data Analyst without access hitting a task they
  don't own).
- **Wrote `docs/SELF_TEST_GUIDE.md`** (plus 9 real screenshots in
  `docs/self_test_assets/`) — a beginner-level, click-by-click guide for
  testing the entire product by hand, written assuming zero prior
  familiarity with the UI, including the brand-new Tasks feature. Every
  button label, field name, and modal title in it was pulled from the
  actual component source, not recalled from memory. It deliberately
  picks two specific Task shapes for two specific outcomes — see
  Decisions below — and includes a real per-action LLM-cost table so a
  reader doesn't accidentally burn the day's AI quota. Finished, not a
  draft; not yet committed as of this log entry.
- **Ran this checkpoint** (Phases 1–2 of it, at the point this log entry
  was written): surveyed the full git state, confirmed nothing tracked
  was modified, and traced every untracked file to a concrete origin
  rather than assuming.

### Decisions

- **The self-test guide uses a fresh signup as its primary walkthrough
  account, not the pre-built demo login (`demo@axiom-yc.ai`).** Rejected
  the demo account as the main path because `demo_reset.mjs` (which
  seeds it) predates the Tasks feature entirely and has no Tasks data —
  using it as the primary path would mean improvising the most important
  part of the guide. The demo login is still documented as a fallback for
  someone who just wants to look around.
- **The guide uses "Diagnose pipeline failure" for the clean-completion
  walkthrough and "Sync, profile & quality-check a source" for the
  approval-gate walkthrough — not the same task shape for both.** This
  wasn't arbitrary: read `agent/personality.py`'s `RISK_ACTIONS` map
  directly before choosing. Every tool `diagnose_pipeline_failure` can
  use (`get_pipeline_run_history`, `check_freshness`, `get_cicd_status`,
  `get_system_health`) is tier `"low"` — guaranteed to run straight
  through with no approval gate. Every mutating tool
  `sync_profile_quality` can use (`sync_source`, `profile_schema`,
  `run_quality_checks`) is tier `"medium"` — guaranteed to hit the
  approval gate on its very first real step. Picking one shape for both
  demonstrations would have made one of the two outcomes a coin flip
  instead of a reliable, repeatable result.
- **Kept the existing one-stage-per-commit convention for Item 6 stage 7**
  rather than folding it into a single giant commit — matches how stages
  1–6 were already committed, and it's what let the bug fix above get
  its own clean verification story instead of being buried in a mixed
  diff.
- **Did not touch `.claude/commands/MASTER_CATCHUP_PROMPT.md` this
  session**, even though it's confirmed stale (wrong local path, an
  API-segment list that predates Team/Settings/Billing/Tasks, and
  Groq-primary/Gemini-fallback framing that's the reverse of current
  reality). Asked the user directly rather than silently rewrite or
  silently leave broken; the user chose to leave it as-is for now and
  rewrite it separately later. Logged here instead of fixed — see Open.
- **Did not stage or touch `marketing-site/`.** It's untracked on
  `master` by design — it belongs on the separate `marketing-site` branch
  (confirmed both a local and an `origin` copy of that branch exist).
  Asked the user to confirm rather than assume; confirmed to leave it
  alone.

### Open

- **The credential rotation `docs/context/WUNOMO_MASTER_CONTEXT.md`'s own
  Section 6 flags as urgent has not happened.** Checked directly rather
  than assumed: both `dataops-agent/.env` and `dataops-agent/backend/.env`
  still contain the literal default `changeme` for the Postgres password,
  and `JWT_SECRET` is only 9 characters — far too short to be a real
  rotated secret, still reading as a placeholder. This is dev-only
  (nothing here is deployed), so it isn't an active incident, but it's a
  real, still-open item, not a resolved one.
- **14 commits (the entire Item 6 arc, stages 1–7) exist only on this
  machine.** `git status` shows the branch 14 commits ahead of
  `origin/master`. None of that work — nor anything this checkpoint
  session commits — is actually safe from a lost machine until it's
  pushed. Nothing in this session pushes anything; that's the user's own
  explicit call to make, per the ground rules for this checkpoint.
- **`.claude/commands/MASTER_CATCHUP_PROMPT.md` is stale** (see Decisions)
  and still needs a rewrite whenever the user gets to it — wrong path,
  wrong architecture description, wrong LLM-provider priority.
- **A real, previously-unknown product characteristic was observed live
  during Item 6 stage 7 verification, not fixed**: `Task.step_budget_used`
  only increments when a step *succeeds* — a step that fails and
  exhausts its retry budget consumes none of the step budget. Whether
  that's the intended design or a real gap is genuinely open; it was
  out of scope for stage 7 to change, so it's just recorded here rather
  than silently accepted or silently fixed.
- Everything already listed under `CLAUDE.md`'s own "Not yet built" and
  Known-broken sections is still exactly as true as it was before this
  session (API keys still can't authenticate a request, no CI pipeline
  exists, no frontend test framework exists, Privacy Policy/Terms of
  Service pages still don't exist). Not rediscovered this session — just
  confirmed still accurate, not stale.

### Gotchas

- **Two `.env` files exist and are not identical**:
  `dataops-agent/.env` and `dataops-agent/backend/.env`. Docker Compose
  actually reads `dataops-agent/.env` (`env_file: .env`, resolved
  relative to the compose file's own location) — the `backend/.env` copy
  is not what the running containers see, and the two have already
  drifted slightly (one has a `GITHUB_WEBHOOK_SECRET` line the other
  lacks, minor formatting differences elsewhere). If you ever need to
  change something LLM- or auth-related and it doesn't seem to take
  effect, check you edited the one Docker actually reads.
- **There is no `.gitignore` at the repo root — only inside
  `dataops-agent/`.** The root-level `venv/` and `.ruff_cache/` don't
  show up as untracked purely because each one ships its own internal,
  self-ignoring `.gitignore` (a standard virtualenv/ruff-generated
  pattern) — nothing at the repo root is actually ignoring them. A stray
  file dropped directly at the repo root (outside `dataops-agent/`) would
  not be automatically gitignored by anything in this project today.
- **Playwright screenshots written via a Node script's
  `fs.mkdirSync("/tmp/...")` land under `C:\tmp\...` on Windows**, not a
  real POSIX `/tmp` — Node doesn't do the MSYS/Git-Bash path translation
  the Bash tool does. Cost a failed `Read` call before realizing the
  screenshots weren't missing, just at a different real path than the
  one used to create them.
