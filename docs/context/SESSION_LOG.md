# Session Log

Newest entry first. This file exists because chat history does not survive
a Claude account migration, but git does — see
`docs/context/WUNOMO_MASTER_CONTEXT.md` for the standing product/business
snapshot and `CLAUDE.md` for the exhaustive, stage-by-stage engineering
record (Status Table + Known Gotchas). This file is the connective layer
between the two: what happened, in what order, and why — the part that's
otherwise only in someone's head or a chat transcript.

---

## 2026-08-19 — ⚠️ BLOCKING BACKEND ESCALATION: `_check_freshness()`'s unbounded incident-creation loop, read this before touching `services/tasks.py` or the `incidents` table

**If you are a backend-focused session picking up work in this repo, read this
entry first, before `docs/context/STATUS_TABLE.md`'s Known-broken table or
anything else — this is the single most urgent item in that table right now.**

### What this is

Not a new bug — the already-documented "Freshness checker creates duplicate
open incidents" Known-broken row (`services/tasks.py`'s `_check_freshness()`,
runs every 15 min via Celery beat, creates a brand-new `Incident` row every
tick a source is still stale, with no dedup check against an already-open
incident for the same asset first). What changed today: a frontend session
(`feat/futurewave` branch, Phase 6 part 2 table-density work) needed to
screenshot the real Incidents screen and, while doing so, measured this bug's
true current scope for the first time — it had previously only ever been
checked one tenant at a time.

**The real, system-wide numbers, queried directly against the dev DB
2026-08-19:** 51,719 `OPEN` incidents, across **339 distinct tenants**
simultaneously exhibiting the identical bug, growing at a measured
**~700–875 new rows/hour** in steady state (hourly buckets immediately
before the check: 175, 874, 701, 700, 700, 700). Two tenants independently
tracked across the same day show the same pattern at smaller scale: the
"Email Code Verify Corp" QA tenant went 7 → 324 → 329 → 355; the
`demo@axiom-yc.ai` / "AXIOM YC Demo" tenant (the frontend's own screenshot
tenant) went 109 → 123 → 151. One leftover test tenant ("Run Status Test
Corp") alone holds 33,857 of the system-wide total (65.5%) — but the bug is
not specific to that tenant; every one of the 339 affected tenants is
independently hitting the same unconditional `db.add(incident)` inside
`if hours_since > sla_hours:`.

### Why this is blocking, not backlog

This has sat in `STATUS_TABLE.md`'s Known-broken table as "flagging only"
since it was first observed (7 near-duplicates for one source). It is no
longer safe to treat as low-priority: this is live, unbounded,
production-shaped write-loop code, currently consuming real DB storage at a
measured, non-trivial rate, with no cap and no sign of self-limiting. The
same code path will hit any real production tenant whose source goes stale
and stays stale — this isn't a dev-environment-only artifact, even though
today's volume is dominated by leftover test tenants.

### What this session did and did not do about it

This was a frontend/design-system session, out of scope for `services/tasks.py`
by design — **not fixed here, on purpose, not by oversight.** What this
session did do: escalated the severity in `STATUS_TABLE.md`'s Known-broken
row (now marked Severity: CRITICAL / BLOCKING) and in
`docs/context/WALKTHROUGH_FINDINGS_2026-08.md` items 48/49/53 (now marked
BLOCKING, with the full trajectory above recorded in each). Also found and
logged, as a **separate, frontend-only bug** (item 55 in the same findings
file, distinct from this one): the Incidents screen's `GET /api/v1/incidents/`
endpoint hardcodes `limit: int = 50` with no pagination and a `count` field
that echoes the truncated page size rather than a true total — meaning the
screen currently has no way to show how bad this actually is, independent of
whether/when this backend bug gets fixed.

### What still needs deciding (not decided here)

1. The real fix: a dedup query against existing open incidents for the same
   `affected_assets` before `db.add(incident)` in `_check_freshness()`.
2. What to do with the already-created rows — a cleanup/backfill decision,
   not made by this session.
3. The frontend's separate pagination gap (item 55) — real paginated
   endpoint + a frontend pager, matched pair, not just a `limit` bump.
4. **Added same day, see follow-up below**: a real test-suite teardown for
   the "Run Status Test Corp" pytest fixture, which currently manufactures a
   brand-new leftover tenant on every run instead of reusing/cleaning one up.

Full detail and exact queries: `docs/context/WALKTHROUGH_FINDINGS_2026-08.md`
items 48, 49, 53, 53-correction, 55; `docs/context/STATUS_TABLE.md`'s
Known-broken row.

### Same-day follow-up — the "one dominant tenant" framing above was wrong

The initial escalation (above) attributed 33,857 of the 51,719-then-current
`OPEN` total to one tenant, "Run Status Test Corp," at 65.5% — asked to
verify this before treating it as final, since a single tenant looping
faster than 338 others would itself be a diagnostic lead worth a separate
flag. **It isn't one tenant.** `SELECT DISTINCT id FROM tenants WHERE
name='Run Status Test Corp'` returns **101 distinct tenant rows** — a
pytest fixture that creates a fresh tenant of this name on every test run
and never tears it down, created repeatedly 2026-07-14 through 2026-08-18
(over a month of accumulation), each with a synthetic
`runstatus-<hex>@example.com` user and exactly one `DataSource` named
`"missing file source"`, profiled once at creation then abandoned forever —
the identical "one dead source, never revisited" shape items 48/49 already
documented on two other tenants. 97 of the 101 currently have `OPEN`
incidents (33,954, current count). Checked and ruled out that any one of
them loops faster than the others: the largest individual tenant ID in this
cohort has 504 `OPEN` incidents, the same order of magnitude as every other
affected tenant system-wide — the total is large because there are ~100 of
them, not because one is anomalous.

**Corrected, both figures kept (neither replaces the other):** including
this cohort, 51,894 `OPEN` across 339 tenants (the real current row count);
**excluding it, 17,940 `OPEN` across 242 genuinely distinct tenants** — this
is the number that should anchor any severity conversation going forward,
since it isn't inflated by one repeated fixture. Growth rate excluding the
cohort: ~300–390 rows/hour, still spread across 242 tenants with no single
dominant one (largest is 9.6% of that total) — if anything, this is
*stronger* evidence the underlying bug is systemic rather than tenant-
specific, not weaker. Per explicit instruction, none of the 33,954 rows
were deleted. `STATUS_TABLE.md`'s Known-broken row and
`docs/context/WALKTHROUGH_FINDINGS_2026-08.md`'s items 48/49/53 updated
with a new "53-correction" row carrying the full detail.

### Second same-day follow-up — the fixture leak is its own bug, logged separately

The 101-tenant pytest fixture behind "Run Status Test Corp" isn't just
context for the escalation number above — it's a real, independent defect:
the test suite writes permanent tenant/user/source rows to the shared dev
database and never tears them down. Logged as its own new finding, walkthrough
item 56, and its own new `STATUS_TABLE.md` Known-broken row, specifically so
it doesn't get marked resolved the day someone fixes `_check_freshness()`'s
dedup — that fix stops these tenants from accumulating more incidents, it
does nothing about the 101 leftover rows or the fixture minting a 102nd on
the next test run. Backend/test-infrastructure, not fixed here. Also: the
escalation summary above and in `STATUS_TABLE.md` now lead with the
corrected 17,940/242-tenant figure, with the 9.6%-largest-contributor number
positioned as the thing that rules out a single misconfigured tenant, per
explicit instruction on how to present it.

### Third same-day follow-up — near-black-ceiling re-audit, three fixes applied

Asked to re-audit every place the original (pre-amendment) near-black-ceiling
rule landed, since it had already been given wrong twice (first as a fill,
then as a neutral-grey border) and both failed the same way. Grepped every
explicit citation of the rule plus every other selection/active state built
around the same period: found three real instances, `.sidebar-item.active`
(Phase 5), `.chat-session-item.active` (AXIOM chat's session list), and
`.cmd-item.selected` (command palette).

`.sidebar-item.active` (dark mode): confirmed defective, same shape as item
54 — `--border-strong` measured 1.75:1 against the sidebar's own base, 1.04:1
fill-vs-fill against `:hover`. `.chat-session-item.active` (dark mode):
screenshot-verified with a real hovered session beside a real active one —
confirmed indistinguishable, `--border` measured 1.24:1. Both fixed with the
same left-edge `box-shadow: inset 3px 0 0 var(--brand-blue)` mechanism as
item 54, verified live at 100% zoom in both themes and (for the sidebar)
both workspace and AXIOM domain modes — confirmed no collision with the
sidebar's own `border-right` (different element, different edge). New
`--sidebar-active-border` dark value points at `--brand-blue` instead of
`--border-strong`; light's value (`--accent-fill`) was already correct and
untouched. `.cmd-item.selected` turned out to have no live consumer at all —
`CommandPalette.tsx` never applies the `.selected` class anywhere (matches
the already-documented "Command Palette's keyboard navigation doesn't exist"
gap in this file's Known-broken table) — so it's dead CSS today, not a live
defect, left as-is. Brief §4 and every component/token comment citing the
pre-amendment rule updated to point at the amendment instead.

### Fourth same-day follow-up — Phase 6 parts 3-5 closed, both carry-forwards corrected

Audited the remaining screens (Quality, Governance, Analytics, Catalog,
Transforms, Automations, CI-CD, Approvals, Settings, Billing, Tasks + Tasks
detail) via a background research pass plus live screenshots in both themes.
Zero console errors, zero hardcoded colors, zero new near-black-ceiling
states. Both carry-forward risks flagged at the start of this session turned
out not to apply — corrected rather than assumed still true:

- `--code-comment` isn't a real token — it's the `.code-comment` CSS class,
  reaching `var(--midnight-300)` directly. Used once across these screens
  (Transforms' empty-state placeholder, confirmed legible live). The Tasks
  detail page doesn't use it at all — its `tool_args` JSON displays are
  plain text. The original "Transforms and Tasks detail both use it" premise
  was half wrong.
- `--chart-accent` + a status colour never share a canvas on Analytics or
  Governance, because neither renders a chart — Analytics is a routable
  stub, Governance's Lineage tab is a plain table, not a graph. The only
  chart code in the app belongs to Dashboard (out of scope here), and even
  there the predicted pairing doesn't occur.

Bonus find, not a defect: the Tasks detail page's failed-step banner already
uses a `var(--${reason.variant})`-driven left-edge coloured bar
(`tasks/[id]/page.tsx:293`) — an independent, pre-existing precedent for
exactly the shape-over-tint approach this session's near-black-ceiling
amendment formalizes, confirmed live in the screenshot evidence.

Full detail in `dataops-agent/frontend/design/CLAUDE_CODE_BRIEF_full_frontend.md`'s
Phase 6 items 3-5 closure note.

---

## 2026-08-17 — Argument resolution live-verified (findings 8/9/16 closed), two new findings surfaced, metering test fixed

### Context

Direct continuation of 2026-08-16: the resolution fix (Tier 1 deterministic
+ Tier 2 LLM-adapt, plus the new `list_pipelines` tool) was built,
unit-tested, and committed, but explicitly marked UNVERIFIED pending a
real live run, per Workflow Rule 10. Today's session did that verification,
plus two small pieces of cleanup work requested first: fixing
`test_llm_usage_metering.py`'s own contamination of the real
`llm_usage_events` table, and a fresh quota check before spending anything.

### Done

- **`test_llm_usage_metering.py` rewritten.** Three of its tests
  monkeypatched `get_primary_llm` and then called the real `invoke_llm()`,
  so `log_llm_usage()`'s real DB commit ran every time regardless of the
  LLM being fake — 3 phantom `gemini`-labeled rows per full suite run.
  Rewritten so only one test (`test_log_llm_usage_persists_a_real_row`,
  calling `log_llm_usage()` directly) still writes a real row — the one
  genuinely unavoidable case, since testing "does this function persist a
  row" requires it to persist a row. Committed as `fe2c782`.
- **Historical audit**: of 348 all-time `gemini`-labeled rows in
  `llm_usage_events`, 222 (63.8%) were provably fake, all traceable by
  tenant name to this one file's old pattern (`Usage Test Corp` 89,
  `Reasoning Test Corp` 80, `List Content Test Corp` 53 rows). Confirmed
  via grep that no other current test file reproduces the anti-pattern.
  Full detail in `docs/context/GOTCHAS.md`.
- **Fresh quota check, before spending anything**: `gemini: 1` for today,
  and that one row was known precisely — the synthetic row from the
  metering-test fix above, run moments earlier. Real Gemini spend before
  live verification: 0. New calendar day (2026-08-17), fresh quota window.
- **Three real, human-run tasks reached `COMPLETED`, live, on Gemini, via
  Playwright driving the actual running app** — the core proof this whole
  arc was building toward:
  - `sync_profile_quality` on the real "Sales Orders" source. All 4 steps
    succeeded (`list_data_sources` → `sync_source` → `profile_schema` →
    `run_quality_checks`). Approval gates for `sync_source` and
    `profile_schema` both displayed the real resolved `source_id`
    (`2bc8a71d-c518-449d-aa87-bdb4f6e922df`), not the plan-time
    placeholder, and executed args matched exactly.
  - `diagnose_pipeline_failure` against the real "HR Sync Pipeline,"
    referenced by name only — no ID supplied by the human at any point.
    Step 0 used the new `list_pipelines` tool to find it
    (`20b0cca2-b089-4de5-871d-a0b66f7fd614`); step 1's `pipeline_id`
    resolved automatically (auto-run tier, no approval gate needed for
    this low-risk tool) with no error.
  - `investigate_incident` against the real HR Sync incident. It was
    already `RESOLVED` (resolved manually outside the Tasks feature,
    2026-08-16 09:42) — reset to `OPEN` directly in the DB first, to let
    the Tasks feature process real, pre-existing data for the first time
    rather than fabricating a new incident. 5 steps, real `resolve_incident`
    mutation confirmed in the `incidents` table
    (`resolved_at: 2026-08-17T07:23:47`). Two steps (`triage_incident`,
    `resolve_incident`) hit a live, unforced Tier 1 miss — 0 candidates,
    because the step's own generated description didn't literally quote
    the incident's title — and both were correctly recovered by Tier 2's
    LLM adapt using the task's real prior discovered data.
  - Approval-gate screenshots captured at every gate across all three
    runs (session scratchpad, not repo-committed) confirming resolved
    real values shown pre-execution matched what actually executed.
- **Forced a genuine, unrecoverable resolution failure and captured the
  new honest error message live.** A 4th task (`investigate_incident`,
  run when the tenant genuinely had zero open incidents) exhausted all 3
  attempts and failed with: *"Could not determine the real value for
  'incident_id' (no match for this step's description among what this
  task discovered earlier). Real error: Incident INC-HR-SYNC-001 not
  found."* — the commit-4 honest-failure message, working exactly as
  designed, live.
- **Two new findings surfaced by this same live testing, not swept in
  with the closure above** — logged as findings-index items 31 and 32
  (`docs/context/WALKTHROUGH_FINDINGS_2026-08.md`), both `Open`, not fixed:
  - **Item 31**: `run_quality_checks` accepts any `pipeline_id`, including
    one matching no real pipeline, and returns a false "100% passed, no
    active rules" result instead of erroring
    (`modules/quality/rule_engine.py:92-103` has no existence check).
    Compounded by `sync_profile_quality`'s own allowed-tools list having
    no pipeline-discovery tool at all, so this task shape can structurally
    never resolve a real `pipeline_id` for its last step. The live
    `sync_profile_quality` run above reached `COMPLETED`, but its last
    step's "success" was hollow — zero quality rules were ever actually
    evaluated.
  - **Item 32 (the more serious one)**: Tier 2's LLM adapt
    (`_adapt_step_args`) can silently substitute a real but *wrong* entity
    when the one the plan actually meant doesn't exist at all, and the
    step reports success. Proven live: a `diagnose_pipeline_failure` task
    deliberately targeting a nonexistent "Zephyr Cargo Manifest Pipeline"
    had its `pipeline_id` replaced with the real ID of the unrelated
    "Sales Ingestion Pipeline" (visible in the task's own `prior_results`),
    the tool call succeeded against that wrong pipeline, and the task
    reached `COMPLETED` reporting on the wrong entity — no error anywhere.
    Tier 1 has an explicit never-guess guardrail; Tier 2 has no equivalent
    one, since its prompt just asks the LLM to "fix" the arguments and a
    plausible real ID satisfies that even when nothing actually supports
    it being correct.
- **Closed findings 8, 9, and 16** (`docs/context/WALKTHROUGH_FINDINGS_2026-08.md`)
  on the strength of the three live `COMPLETED` runs above — see that
  file's "Closure notes (2026-08-17)" section for the full reasoning.
  Updated `docs/context/STATUS_TABLE.md`'s 2026-08-16 qualifier row to
  `[RESOLVED: 2026-08-17]` with a new row documenting the live evidence,
  per Workflow Rule 9 (never leave a stale known-broken row riding once
  its fix lands).

### Decisions

- **Reset the HR Sync incident from `RESOLVED` to `OPEN` via direct SQL**
  rather than fabricating a new incident, since the real incident already
  existed with real prior data (detection, root cause, pipeline linkage)
  and had simply never been run through the Tasks feature specifically —
  restoring its pre-resolution state let `investigate_incident` process
  real, existing data for the first time, which is what the verification
  needed to prove.
- **Created two extra throwaway tasks (targeting a nonexistent pipeline,
  and a tenant with zero open incidents) specifically to force resolution
  failure**, beyond the three the plan called for — the three planned runs
  all resolved cleanly or recovered via Tier 2, so none of them naturally
  produced the honest-failure-message proof the original plan also
  required; forcing it was the only way to actually see that code path
  live rather than trust the unit test alone.
- **Did not attempt to fix items 31 or 32 this session** — out of scope
  for what was approved (live verification of the existing fix, not new
  changes), and item 32 in particular needs its own design discussion
  (how should Tier 2 signal "no real match exists" instead of always
  returning a corrected value) rather than a reactive patch.
  **Superseded later the same day** — see "Done (follow-up)" below; the
  user asked for both fixed immediately after this report went out.

### Open

- `sync_profile_quality`'s allowed-tools list (`task_planner.py`) still
  has no way to discover a real `pipeline_id` for its own last step —
  item 31's fix (below) makes `run_quality_checks` fail honestly on a
  bogus one instead of lying about success, but doesn't give this task
  shape any way to find a *real* one. A `sync_profile_quality` task will
  still legitimately fail at its last step for any pipeline whose
  quality checks were meant to be reachable this way — not regressed
  today, just not what today's follow-up work was scoped to fix either.

### Done (follow-up, same day — items 31 & 32 fixed)

Immediately after the report above, asked to fix both, no new features.

- **Item 31**: `QualityRuleEngine.run_checks()` and the same-shape
  `BusinessRules.run_all()` (`modules/quality/business_rules.py`) now
  check the pipeline exists before reporting a result — a bogus
  `pipeline_id` returns `{"error": "Pipeline ... not found"}` instead of
  a false "100% passed, no active rules." Checked every other
  `pipeline_id`/`source_id`-taking function in `modules/` for the same
  shape first, per explicit instruction: `get_pipeline_run_history`,
  `detect_anomalies`, `get_pipeline_stats` already validated existence
  correctly; `business_rules.run_all()` had the identical gap, fixed
  alongside `run_checks()` since it's the same bug, not a new feature.
  Live-verified against the real dev DB, both functions, plus confirmed
  a real ruleless pipeline still correctly reports 100%/no-rules (that's
  a true statement for a real pipeline, unlike for a fake one). Commit
  `f6b4028`.
- **Item 32**: ported Tier 1's never-guess guardrail to Tier 2. New
  `_reject_ungrounded_adaptation()` runs after every `_adapt_step_args`
  call — an `_id`-shaped key Tier 2 changed is only kept if the new value
  is a real id this task actually discovered for that key AND the
  discovery pool has exactly one member; otherwise it reverts to the
  pre-adaptation value, so the step fails again and, once attempts are
  exhausted, the existing honest-failure message reports it truthfully.
  `_candidate_ids_for_arg` (Tier 1) and the new
  `_all_discovered_ids_for_arg` (Tier 2's guardrail) now share one
  `_discovered_records_for_arg` helper. New test
  `test_tier2_never_substitutes_an_undiscovered_or_ambiguous_entity`
  reproduces the live bug's exact shape. One pre-existing test
  (`test_domain_error_triggers_exactly_one_adapt_call_then_succeeds`) had
  no real discovery step behind its test double's "corrected-id" — given
  one real matching candidate so it still tests retry mechanics, not the
  new guardrail it wasn't written to exercise.
  **Live-verified for both a read-only and a mutating shape**, per
  explicit instruction that the mutating case is the one that matters:
  re-ran the exact Zephyr Cargo Manifest Pipeline scenario
  (`diagnose_pipeline_failure`, read-only `get_pipeline_run_history`) —
  now fails honestly after 3 attempts instead of completing against
  Sales Ingestion Pipeline. Then a `sync_profile_quality` task naming a
  nonexistent "Zenith Marketing Leads" source, with the 2 real sources
  (Employee Records, Sales Orders) in the discovered pool — `sync_source`
  (a real mutation) correctly kept the unresolved placeholder at its
  approval gate, and after approval failed honestly rather than silently
  syncing either real source; confirmed directly against the DB that
  neither source's `last_profiled_at`/`updated_at` changed. Commit
  `e312212`.
- Full backend suite: 397 passed, 1 pre-existing unrelated flake
  (`test_freshness_check_notifies_once_per_newly_stale_source_not_every_tick`,
  already documented in `STATUS_TABLE.md`'s Known-broken table as
  order/state-dependent on other tenants' stale sources in the shared
  dev DB — confirmed by re-reading that row before concluding this
  wasn't a regression, not assumed).
- Both findings closed in `WALKTHROUGH_FINDINGS_2026-08.md`.

### Gotchas

- Quota tracking via `llm_usage_events` is only as clean as the tests
  writing to it — see `docs/context/GOTCHAS.md`'s updated entry for the
  full historical contamination numbers (222 of 348 all-time `gemini`
  rows). Fixed going forward, not retroactively — the historical rows
  themselves weren't deleted or relabeled, just documented as unreliable.
- Total real Gemini spend today: 5 `task_planning` + 4 `task_step_adapt` +
  1 `incident_triage` = 10 real calls, all on primary (no Groq fallback
  triggered at any point) — well inside the ~20/day budget, no need to
  stop early or ration across the verification runs.

---

## 2026-08-16 — Findings 8/9's real root cause, argument resolution built (4 commits, UNVERIFIED), and a quota-estimate lesson

### Context

The user ran the first real end-to-end self-test walkthrough against the
expanded `SELF_TEST_GUIDE.md`, logged 28 raw findings
(`docs/context/WALKTHROUGH_FINDINGS_2026-08.md`), and asked for a
diagnosis session on 7 of them before any fix. Findings 8/9 ("after
Approve & Resume, the continue buttons don't come back") turned out to be
the significant one — the investigation is what this whole session grew
out of.

### Done

- **Diagnosed findings 8/9 to their real root cause, live, not from code
  alone.** The buttons correctly do not reappear — `PAUSED_FAILED_STEP`
  is genuinely not advanceable, by design. The real bug is upstream:
  `task_planner.py`'s plan generation writes a step's entire `tool_args`
  in one LLM call, before any earlier step (e.g. `list_data_sources`) has
  actually run, so a step needing an ID discovered by an earlier step gets
  a fabricated placeholder (`"source_id": "sales_orders_source_id"`)
  instead of a real one. Reproduced live via a real Playwright-driven
  task run, then confirmed via direct DB query — step 0's own persisted
  `raw_result` contained the real UUID (`"id":
  "2bc8a71d-c518-449d-aa87-bdb4f6e922df", "name": "Sales Orders"`) right
  next to step 1's placeholder that never used it.
- **Checked all three task shapes, not just the one that failed** — found
  a second, worse pattern (call it "Pattern B"): `get_pipeline_run_history`
  needs `pipeline_id`, and *no tool in the entire registered set* could
  ever discover one — not "the shape doesn't call the discovery tool,"
  there was no discovery tool to call, in any shape. Confirmed this isn't
  theoretical: queried the real `tasks`/`task_steps` tables for the last 7
  days of genuinely human-run tasks (filtering out the years of automated
  pytest fixture noise in that table) and found exactly one real
  completion ever, a maximally vague "help" goal that happened to only
  need zero-argument tools. Every real run that named a specific pipeline
  or source — including both of the user's own real Part C and Part D
  self-test attempts — hit `PAUSED_FAILED_STEP`. This is the finding
  behind the new Workflow Rule 10 below: stages 1–7 verified every piece
  of the Tasks machinery without ever verifying that a real, non-trivial
  plan could reach `COMPLETED`.
- **Proposed and got approval for the fix design** before writing code
  (execution-time resolution, not plan-time — the planner structurally
  cannot know an ID that doesn't exist yet). Built as 4 separate,
  individually-tested commits:
  1. `fdd8ece` — new `list_pipelines` tool (closes Pattern B for
     `DIAGNOSE_PIPELINE_FAILURE`/`INVESTIGATE_INCIDENT`). Found and fixed
     a self-inflicted collision while getting this green: `DAGManager`
     already had a `list_pipelines()` method backing the real
     `GET /pipelines/` REST endpoint; the new one silently shadowed it
     (Python keeps the later definition) until the existing
     `test_list_pipelines_reports_next_run_and_last_run` caught it.
  2. `d3c0fc3` — Tier 1 deterministic resolution: matches a step's
     `_id`-shaped arg against a prior successful discovery step's real
     `raw_result` by name/title, no LLM call. Two insertion points, not
     one (verified by reading the full execution flow before writing
     anything, per explicit instruction not to assume) — before the
     approval gate is created (so what's displayed on the card is what
     runs) and before an auto-run step's first attempt, mutually
     exclusive by risk tier so a step is never resolved twice.
  3. `ee9fa93` — Tier 2: `_adapt_step_args` (the existing LLM-correction
     fallback) now sees the same accumulated prior real results, for the
     ambiguous/uncovered cases Tier 1 didn't resolve.
  4. `f68b62d` — honest failure messaging: a step that still can't be
     resolved by either tier now says so explicitly, alongside (not
     instead of) the real underlying tool error.
- **Idempotency and human-edit-safety proven with real tests, not just
  argued for.** `test_resolution_is_noop_on_resume` monkeypatches
  `_resolve_step_args` to raise if called a second time, then resumes an
  already-resolved step and asserts the executed args are byte-identical
  to what was on the approval card. `test_resolution_skips_human_edited_args`
  confirms a human-typed value that deterministic matching *could* have
  "corrected" is left exactly as typed.
- **Discovered mid-build that the full pytest suite itself spends real
  Gemini quota** — `test_real_live_llm_generates_a_valid_reviewable_plan`
  is a genuine, unmocked LLM call, and re-running the full suite after
  each commit (standard practice, to confirm zero regressions) cost 5
  real `task_planning` calls plus 1 `task_step_adapt` call across the
  session — quota that hadn't been budgeted for, since the original
  estimate given at the start of the build only counted the *intentional*
  live verification work, not the incidental cost of routine suite
  re-runs along the way. By the time this was noticed, 18 of ~20 daily
  Gemini calls were gone and live verification (which needs 3+ fresh plan
  generations minimum) hadn't started. Fixed properly, not just
  noted: the test is now `@pytest.mark.live_llm`, excluded from the
  default `pytest tests/` run (`pytest.ini`'s `addopts`), run explicitly
  via `pytest tests/ -m live_llm` — see `docs/context/GOTCHAS.md`'s new
  entry for the full detail and the confirmed collection counts
  (397 default / 1 live-LLM-only).
- **Verifying that fix surfaced a second, more unsettling discovery: the
  "18 of ~20" quota number above was itself measured with a query that
  can overcount.** The confirming default-suite run (397 passed, 0
  deselected... 1 deselected) still added 3 new rows genuinely labeled
  `provider='gemini'` in `llm_usage_events` — traced to
  `test_llm_usage_metering.py`'s three tests, which mock `get_primary_llm`
  (returns a fake object) rather than `invoke_llm()` itself, so
  `invoke_llm()`'s real body — including its real usage-logging call —
  still runs and writes a real "gemini"-labeled row for a call that never
  touched the network. `SELECT count(*) ... WHERE provider='gemini'` (the
  self-test guide's own documented zero-cost quota check) cannot tell
  these apart from real spend. This means the "18 of ~20" figure reported
  to the user mid-session was an upper bound, not an exact count — if the
  backend suite had already run earlier the same day (plausible, given
  how much of today's session involved it), the true remaining quota was
  probably somewhat higher than stated. Reported to the user as soon as
  found; did not unilaterally revise the earlier stop-for-quota decision
  on the strength of this — that's the user's call, not something to
  quietly resolve by continuing. Full detail in the same new
  `docs/context/GOTCHAS.md` entry.

### Decisions

- **Deterministic resolution first, LLM-adapt only as fallback** — not
  the user's own initial framing (which leaned toward feeding prior
  results straight into the existing LLM-adapt call). Argued and agreed:
  an LLM correcting a bad ID from a schema and an error message alone is
  guessing blind with no way to know the real value; a deterministic
  name-match against the actual fetched record is both free and more
  reliable than a guess informed by the same data would be.
- **Resolution happens before the approval gate renders, not after
  approval, not lazily on resume.** This was the user's explicit,
  named-as-most-important requirement: what's displayed on an approval
  card and what later executes must be the same value, or approving
  something becomes meaningless. Verified this holds by construction
  (two mutually-exclusive, risk-tier-gated insertion points, no code path
  that resolves a step twice) and by a test that would fail loudly if a
  future refactor broke it.
- **Human-edited steps are never touched, using the existing
  `TaskStepSource.HUMAN_EDITED` provenance signal** — not new state, per
  explicit instruction. A human who typed a value meant that value, even
  if deterministic matching disagrees.
- **Pattern B (`list_pipelines`) built and shipped as its own first
  commit**, not folded into the resolution commits — it's a real,
  separate gap (no tool could ever discover a pipeline ID, in any shape),
  not a symptom of the same argument-threading bug the other three
  commits fix.
- **Stopped before live verification rather than push through on the
  Groq fallback.** Quota was the explicit, pre-agreed stop condition
  ("stop if it would exhaust quota mid-run... I'd rather resume tomorrow
  than have a half-verified claim"). Given the choice explicitly, the
  user chose to resume tomorrow on Gemini rather than let the three
  required live runs land partly on the fallback provider.

### Open

- **Commits `fdd8ece`/`d3c0fc3`/`ee9fa93`/`f68b62d` are built, unit-
  tested, and committed — but UNVERIFIED against the actual product.**
  Per the new Workflow Rule 10 this same session added, none of this
  counts as done until a real task reaches `COMPLETED` through the real
  UI. `docs/context/STATUS_TABLE.md` has deliberately **not** been
  updated to mark any of this fixed — see its own new note. Tomorrow's
  first action, before anything else: the zero-cost quota check
  (`SELECT provider, count(*) ... FROM llm_usage_events WHERE created_at
  >= CURRENT_DATE`) — **treat the result as an upper bound, not exact**,
  per the measurement-contamination discovery two bullets up; if the
  backend suite hasn't run yet today, the count is clean. Then the three
  live verifications to `COMPLETED`:
  `sync_profile_quality` on the demo tenant, `diagnose_pipeline_failure`
  using the new `list_pipelines` step (no ID supplied by the user),
  `investigate_incident` against the real, never-yet-run HR Sync incident.
  Screenshot every approval gate hit along the way and confirm the
  `tool_args` shown are the resolved real values, not placeholders, and
  that what executed matches what was displayed — the exact property the
  idempotency tests already assert, now checked against the real running
  app instead of a test double.
- **`docs/context/WALKTHROUGH_FINDINGS_2026-08.md` items 8, 9, and 16
  deliberately left `Open`, not `Closed`** — the original instruction was
  to mark them closed as "not bugs," but that was written before the
  quota discovery interrupted the plan. Given the fix itself isn't yet
  live-verified, closing the findings that motivated it would be the same
  kind of premature claim Workflow Rule 10 exists to prevent. Revisit
  once tomorrow's live runs land.
- **Findings 12, 13, 14, 15, 21, 18, 2/3, 20** from the original 7-item
  diagnosis batch are unrelated to this fix and remain wherever that
  diagnosis session left them — not touched this session.

### Gotchas

- See `docs/context/GOTCHAS.md`'s new entry for the pytest live-LLM-cost
  discovery in full — not duplicated here.
- Refactoring `_resolve_step_args`'s per-arg matching logic out into a
  shared `_candidate_ids_for_arg()` helper (so the honest-failure-message
  check in Commit 4 and the resolution itself in Commit 2 can never
  disagree about what counts as a match) was decided *after* Commit 2
  already shipped — worth doing this extraction up front next time a
  "resolve X" and "explain why X wasn't resolved" pair is being built
  together, rather than writing the check twice and unifying it later.

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
