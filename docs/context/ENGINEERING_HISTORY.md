# Engineering History

> Archived verbatim from CLAUDE.md on 2026-08-12, during the account-migration
> checkpoint session. This is the old CLAUDE.md's title/banner chain, section 0
> (Current Position) and section 1 (Architecture Summary), plus the old Archive
> section, all unedited. See `docs/context/SESSION_LOG.md`'s 2026-08-12 entry for
> why this split happened, and the new, lean `CLAUDE.md` for current orientation.

# CLAUDE.md — AXIOM DataOps Agent

> **NEXT SESSION STARTS HERE (as of 2026-08-06).** Item 6 (long-running
> AXIOM tasks) is **fully complete — all 7 stages done and live-verified,
> including the required full end-to-end UI walkthrough.** Stage 7
> (visibility + role gating) closes the arc: a real Tasks nav item + list
> screen, a per-task step timeline reusing the CI/CD/pipeline-runs Table+
> Badge visual language (not a new UI pattern), a real live topbar
> "N active" counter, a chat-inline "Started task: X" card with a "View
> progress" link, best-effort notification wiring at every terminal/
> attention transition (`_notify_task_stopped()`, reusing the already-real
> `NotificationService`), and `tasks.manage_all`'s permission-matrix
> exemption removed now that a real hard-gated endpoint (`GET /tasks/all`)
> exists for it to be tested against like every other capability. New
> `GET /tasks/counts` (`{"active": N}`, terminal-status-excluded, same
> soft own-vs-all filter as `GET /tasks/`) backs the topbar counter,
> polled every 20s — **proven live to be a real poll, not decorative**:
> with the browser sitting on `/dashboard` (never `/tasks`, never
> reloaded), a task was created via a direct API call and the topbar's own
> count genuinely advanced from `1 active` → `2 active` within one 20s
> poll cycle, no navigation involved. Full stack live-verified end-to-end
> through the actual UI, not just the API, per explicit requirement: a
> real chat-driven task creation (`+ Start a Task` → real Gemini/Groq plan
> generation for `diagnose_pipeline_failure`, a real 1-step plan
> referencing the real pipeline) produced a real inline chat card; editing
> the step's description and saving correctly flipped its provenance
> badge from "AXIOM planned" (gray) to "Human edited" (warning-amber),
> visually distinct from a third color reserved for `system_inserted`
> (midnight); approving genuinely queued it; "Run to completion" (a
> client-side loop over the real `POST /advance`, since stage 3's
> "advance is the only way a task progresses" decision is unchanged —
> no backend auto-scheduling was added) drove it to a real
> `paused_failed_step` after 3 real attempts against a real "Pipeline not
> found" domain error, with the reason banner correctly showing the exact
> failed step's own description and real error text, not a generic
> message. **Separately live-verified, via a directly-seeded task (no
> second LLM call spent)**: the mid-task approval gate on a real
> `sync_source` call genuinely blocked with `PAUSED_NEEDS_APPROVAL`, and a
> real "Approve & Resume" click genuinely resumed it — the tool call
> actually ran and succeeded (`total_rows: 10`, real profiled columns).
> **Role-gating proven as hide-not-disable, both directions**: an Admin
> (holds `tasks.manage_all`, not the creator) can view another member's
> draft plan but sees no Edit/Approve/Reject controls, only a
> creator-only note; a Data Analyst (holds neither) correctly gets a real
> `403` from the backend, with zero leaked task content in the DOM and no
> crash. **One real bug found and fixed during this same live pass**: a
> 403 (or any load failure) on the task detail page previously rendered
> an infinite loading skeleton with no way out — fixed with a proper
> `taskQuery.isError` branch (a clear "Can't open this task" empty state
> + a link back to `/tasks`), re-verified live against the same Analyst
> 403 case. Both themes screenshotted across the full flow (list, plan
> review, editing, approval-gate, timeline, terminal states, chat card,
> the create-task modal) — no contrast issues found. Backend: 18 new
> tests (`test_task_notifications.py` ×12, covering exactly which
> transitions notify and which are deliberately silent —
> `paused_failed_step`/`paused_quota_exceeded` don't, to avoid spamming
> on retry — plus a notification-failure-never-breaks-the-real-transition
> case; `test_tasks_all_and_counts_endpoints.py` ×9, including a route-
> registration-order regression guard for `/all` and `/counts` against
> `/{task_id}`), full suite 394 passed. Frontend: `npx tsc --noEmit` and
> `npm run build` (production, Turbopack) both clean, 29 routes including
> the two new `/tasks` routes. **Item 6 (long-running AXIOM tasks) is now
> closed — all 7 stages shipped, tested, and live-verified.** Everything
> below this paragraph is the pre-stage-7 state of the project, kept for
> history.
>
> **Prior banner (as of 2026-08-05, superseded above).** Item 6 (long-running
> AXIOM tasks — see `docs/PRODUCT_AUDIT.md` section 1.8/1.9 for the full
> design) is now the active thread, superseding the banner below until
> it's done. Design fully locked in section 1.9 (5 core questions + 4
> amendments — failure semantics, structural verification, visibility,
> termination, mid-task approvals, plan provenance, role re-read at
> execution time, 3 narrow v1 task shapes) — read that section before
> touching any of this. **Stage 1 (schema + migration + the
> `tasks.manage_all` capability, no behavior) and Stage 2 (planning phase:
> goal+shape → a real persisted, human-reviewable, editable, approvable
> plan) are both done and live-verified** — see the Status Table rows
> below, including the fix for a real enum-label bug stage 1's migration
> shipped with (caught before stage 2 built anything on top of it) and
> the new `TaskStatus.QUEUED` value it prompted. **Stage 3 (execution
> core: the Q1 failure-tier policy + amendment 3's per-step fresh role
> re-check) is also done and live-verified** — see the Status Table row,
> including a real mid-task role demotion (no new token issued) blocking
> the very next step, and a real deleted pipeline triggering a real
> LLM-adapt call. `POST /tasks/{id}/advance` is currently the only way a
> task progresses — no automatic scheduling exists yet, deliberately.
> **Stage 4 (verification, Q2) is also done and live-verified** — a
> dispatching step's async result now spawns a real, separate
> `system_inserted` verify step, polled purely on real elapsed wall-clock
> time; `COMPLETED` is structurally unreachable while a verify step is
> still unresolved (new `TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS`
> covers that honestly instead). Live-verified against real
> infrastructure: a real Celery-dispatched `run_pipeline` call, genuinely
> processed by the real `celery_worker` container, genuinely polled to a
> real terminal state by `execute_next_step()` — not simulated. Note:
> `run_pipeline` is deliberately not in any `TASK_SHAPE_ALLOWED_TOOLS`
> entry yet (no per-step approval gate exists until stage 5), so this was
> exercised via a directly-seeded `TaskStep`, same technique as stage 3.
> **Stage 5 (mid-task approvals + bounded resume context + pause-timeout
> expiry, Q5) is also done and live-verified — the planning-phase design
> arc (stages 1-5) is now complete.** New `POST /tasks/{id}/resume` +
> `.../reject-step`, gated by `approvals.manage` (Owner/Admin, not
> creator-only). All four things explicitly required to be proven live
> were: resume survives a real, full `dataops_backend` container restart
> (two separate script invocations, zero shared memory); a resumed step
> genuinely re-validates real-world preconditions (a real deleted
> `DataSource` was caught, not blindly proceeded past); a resumed step's
> authority is re-checked fresh, independent of the approver's own
> (a demoted initiator blocked correctly even though a different, valid
> Admin's approval succeeded); an expired approval can't be resumed
> (real `409`, real `EXPIRED` status, an honest `expiry_reason`). Real
> token cost of one resume's LLM involvement: 251 tokens — and the
> finding worth keeping is that `resume()` itself never calls the LLM at
> all, so the bounded-context design ended up mattering less than
> expected, not more. **Stage 6 (termination: step/wall-clock/credit
> caps, loop detection, real Cancel, credit-exhaustion pause) is also
> done and live-verified — this closes out item 6's core
> planning-through-termination arc (stages 1-6).** See its own Status
> Table row for the full detail; the short version: loop detection is
> proven as a real positive (a genuine 3-identical-step plan is stopped
> before the 3rd runs, not just proven not to false-positive on a normal
> plan); credit exhaustion is proven with real seeded usage crossing the
> real Starter-tier limit, pausing and then genuinely resuming through
> the real `POST /tasks/{id}/advance` endpoint (which itself had a real
> bug — it never accepted `PAUSED_QUOTA_EXCEEDED` as a runnable status —
> found only by this live pass, not the mocked tests, and fixed); and
> cancel-mid-flight is proven with a real concurrent `asyncio` race, not
> just asserted — an in-flight step (genuinely inside a real backoff
> sleep) is allowed to finish and its real outcome is recorded, but
> `Task.status` is never stomped back from `CANCELLED`. **Item 6's next
> possible stage is 7 (visibility: Tasks screen, timeline, topbar
> counter, chat-inline card) — not yet started.** Everything below this
> paragraph is the pre-item-6 state of the project, kept for history.
>
> **NEXT SESSION STARTS HERE (as of 2026-08-02, superseded above).** All 5 Phase 19 P0 items
> are done, and the **migration-drift session is now also done** (see
> below) — the **dark-theme screenshot verification pass** (token redesign
> already landed in `tokens.css`, the visual pass across every
> screen/both themes is the only thing left open on that thread — needs
> zero LLM calls, so quota isn't a blocker) is the only unstarted item
> left from the two this file's banner had been alternating between.
> Full breakdown of what's done/remaining/undecided/accepted-for-launch/
> domain-gated is in `FRONTEND_BUILD_PLAN.md`'s "Phase 19 partition
> status" section — read that section before picking up any Phase 19
> work.
>
> **Public-launch risk cluster (2026-08-02) — OPEN, approved order:
> (c) → (b) → provision infra → (e) → (a) → (d).** Proposed and approved
> in a docs-only planning pass (size/blast-radius/order for all 5 items),
> then execution started same session. **(c) and (b) are both done, fully
> live-verified — see below.** Next up: **provision `wunomo.in`/
> `api.wunomo.in` infra**, then (e) backups, then (a) flip to paid LLM
> keys (real per-turn token cost already measured — see below — plus a
> live pricing pull still owed before enabling billing), then (d) R2
> migration (confirmed **not** launch-blocking — target host is a plain
> VPS with a persistent Docker volume, so this genuinely follows rather
> than blocks). **Also outstanding from this cluster, not yet done**: pull
> live current Gemini/Groq paid-tier pricing and compute a real monthly
> cost at 20 users × 5 turns/day using the ~3,419 avg-tokens/turn figure
> below; and note in the eventual deployment checklist to set a hard
> spend cap in each provider's own console when paid keys go live — an
> independent, provider-level backstop alongside (b)'s app-layer fix, not
> a substitute for it.
>
> **(b) change-plan free-upgrade hole — RESOLVED (2026-08-02), Option 1:
> disabled self-serve entirely, not the payment_verified/usage-check
> architecture originally proposed as the alternative.** `POST
> /change-plan` now always `501`s for any caller who passes the existing
> role gate — matching the checkout/webhook honest-stub pattern exactly.
> `BillingService.change_plan()` itself is untouched and stays real,
> now documented as the sanctioned way to manually provision a real
> paying customer's plan before Stripe exists (direct service call or a
> raw `Tenant.plan` SQL write — either bypasses the disabled endpoint on
> purpose). Live-verified against the real running server: a real Owner's
> direct `curl` bypass attempt got a real `501` with the plan provably
> unchanged (checked via both the API and a direct DB query); a demoted
> Viewer still correctly `403`s (role gate fires first, unchanged from
> before); the administrative path was exercised for real (a direct
> `BillingService.change_plan()` call inside the container) and
> genuinely persisted. Frontend's plan-picker UI removed, not just
> disabled. Full backend suite: 255 passed. See the now-resolved
> Known-broken row and the new Status Table row for full detail.
>
> **(c) WebSocket chat auth — RESOLVED BY DELETION, not hardened
> (2026-08-02).** Before touching this, grepped the entire frontend
> (`frontend/src/**`) for any WebSocket usage and found zero references —
> confirmed independently by an earlier, already-on-record
> `USER_MANUAL.md` audit finding the identical thing. The only backend
> reference to the route was its own definition; no test file touched it
> either. **Deleted `WS /ws/chat/{tenant_id}/{session_id}` entirely from
> `main.py`** (route handler + the now-unused `WebSocket`/
> `WebSocketDisconnect` imports) rather than adding auth to it, per
> explicit instruction — smaller, safer, permanently removes the attack
> surface instead of hardening a path nothing legitimate depends on.
> Live-verified: backend restarted clean (`Application startup
> complete`), `GET /health` still `200`, and the old WS path now returns
> a plain `404 {"detail":"Not Found"}` — byte-identical to a genuinely
> nonexistent route, confirming it's gone, not just erroring differently.
> Full backend suite: 255 passed, zero regressions (expected — nothing
> real ever called it). See the now-resolved "WebSocket chat auth"
> Known-broken row and the new Status Table row for full detail.
>
> **Migration-drift session (2026-08-02) — done.** Verified
> `alembic upgrade head` against a genuinely empty, isolated scratch
> Postgres 16 container (never the dev DB, never touched or restarted)
> and found real drift: `pipeline_commits`/`pipeline_deployments`
> (`models/cicd.py`) had **no** migration creating them at all — a fresh
> chain died with `UndefinedTable`. Fixed with a new migration,
> `609092d6978f_add_cicd_pipeline_tables.py`, inserted between
> `7e3773979374` and `db3efa7d4d82`, creating both tables plus the 3 enum
> types (`cicdstatus`/`gatedecision`/`deploymentstatus`) that only ever
> existed via `create_type=False` declarations in the model — meaning
> nothing, not even `create_all()`, could ever create them from scratch
> (a real, previously-undocumented manual step this repo has never
> committed anywhere — see the rewritten Alembic Gotcha below). Also
> found and fixed a real, separate gap via an order-independent
> `information_schema` diff (not a raw `pg_dump` text diff): `team_invites`
> was missing its `ix_team_invites_created_at` index in `a4f7c92b1d05`
> even though the model has declared it since Phase 15. The long-suspected
> `incidentstatus` lowercase-vs-uppercase enum drift turned out to be
> **dead code, not live drift** — migration order means the correct
> uppercase type is created first and the wrong-looking later attempt is
> silently swallowed by Postgres's `duplicate_object` exception; corrected
> the misleading value list anyway. **Final proof**: an alembic-upgraded
> schema and a `create_all()`-built "known-good" schema, built on two
> separate empty scratch DBs, diffed via `information_schema` across
> tables/columns/indexes/foreign keys/primary keys/enum labels —
> byte-identical across all 24 tables, zero remaining diff. See the
> Status Table's "Migration-drift verification" row and the rewritten
> Alembic Gotcha for full detail. **The plain-language version of the
> significant finding, stated explicitly per the user's own request:
> neither Alembic nor `create_all()` could bootstrap a genuinely empty
> database — the project was effectively unbuildable from scratch, and
> nothing in the repo would have told anyone that, since the real dev DB
> only ever worked because of an undocumented manual step from
> unknown-when.** **Production domain purchased**: `wunomo.in` (frontend),
> `api.wunomo.in` (API) — recorded in Outstanding items below; nothing is
> configured yet, this was a value-recording pass only, done in the same
> session but kept separate from the migration work.
>
> **Two follow-ups requested and closed in a same-day follow-up pass
> (2026-08-02):** (1) **Idempotency, confirmed for the real deploy case.**
> Re-running `alembic upgrade head` against an already-fully-migrated
> scratch DB (simulating "runs on every deploy, not just the first") is a
> clean no-op — zero SQL executed, exit 0 — because Alembic's own
> `alembic_version` tracking skips every already-applied revision
> entirely; this holds regardless of any individual migration's SQL
> content. Also tested the narrower edge case of *lost* version tracking
> against an already-migrated schema (simulating a corrupted/reset
> `alembic_version` table) — this does fail hard on a full replay, but
> at the very first, oldest, pre-existing migration (`7e3773979374`), not
> the new one this session added; every migration in the chain except
> `db3efa7d4d82`'s two defensively-wrapped statements shares this same
> non-defensive property, so the new migration is no more fragile than
> what was already there. See the new Gotcha for full detail. (2)
> **Drift-detection CI check — proposed and sized, not built**, per
> explicit instruction. A single `compare_metadata()`-based pytest test
> (Alembic's own built-in schema-vs-models diff primitive) against a
> throwaway CI Postgres would have caught this entire migration-drift
> problem months earlier. Estimated **small** — roughly 60-100 lines, one
> new test file, likely no new CI infrastructure since this project's
> test suite already needs a live Postgres. Full proposal, caveats, and
> sizing rationale in the new Gotcha entry right after the idempotency
> one — read it before deciding whether to build it.
>
> **Interleaved YC-demo-prep session (2026-07-23/24, not a Phase 19
> session — the above recommendation still stands for the next real build
> session).** Produced a one-command demo tenant reset
> (`dataops-agent/scripts/demo_reset.mjs` + `demo_unbreak.mjs`), a demo
> runsheet artifact, and `docs/PRODUCT_STATUS.md`. Found and fixed 2 real
> bugs (file connector `rows_processed: 0`; an empty-list tool result
> crashing `POST /chat/` on Groq) and documented 1 critical, unfixed one:
> **`PolicyEngine.execute_approved_action()`'s dispatch is broken for all
> 8 registered actions** — approving a blocked AXIOM action does not
> execute it (see the new Known-broken row). Also removed the topbar's
> decorative notification bell/env dropdown and wired "AXIOM Online" to a
> real `GET /health/db` poll, per explicit user approval. `PRIMARY_LLM_MODEL`
> was temporarily switched to Groq for testing and confirmed restored to
> `gemini-3.5-flash` before ending — see the Gotcha on this pattern.

**Read this file in full before doing any work in this repo.** It is the living contract for how Claude Code operates here. Update it (Status Table + Known Gotchas, at minimum) in the same commit as any fix, feature, or discovery that changes what's true below.

Repo root: `c:\Pratyaksh Personal\My Projects\ai workforce\`. The one real project inside it is `dataops-agent/` — "AXIOM", an autonomous AI DataOps agent (part of the "AI Workforce Systems" product line). Everything else at repo root (`employee_data.csv`, `sales_data.csv`, `pipeline_config.json`, `tree.txt`, `generate_dataops_project.py`, `Document/*.pdf`) is scaffolding/sample/reference material, not application code, **except `FRONTEND_BUILD_PLAN.md`**, which is a real, authoritative planning document — read it before doing any frontend work. `generate_dataops_project.py` is the original scaffold generator that wrote out `dataops-agent/` — treat it as historical, not as the source of truth; the files it once generated have since been hand-edited (see patch scripts in Archive).

This repo now has git history: an initial commit capturing the scaffold as originally built (after cleaning ~11.5k stray `node_modules`/`.next` files out of the index — see Archive), followed by one commit per individually-verified fix. Keep following the one-fix-per-commit rule for everything from here on (Workflow Rule 6).

---

## 0. Current Position (read this first)

**Backend:** feature-complete and verified through Phase 4 of backend testing (see
Status Table below) for the REST API surface — auth, sources, pipelines, quality,
incidents, CI/CD, approvals, governance, transforms are real and live-tested via
direct API calls. **The AXIOM chat agent's tool-calling surface punch list is fully
closed** — the LangChain v0.3→v1.x ecosystem upgrade (`langchain` 1.3.14,
`langchain-core` 1.4.9, `langgraph` 1.2.9, `langchain-google-genai` 3.2.0,
`langchain-groq` 1.1.3, `langchain-community` 0.4.2) landed the `thought_signature`
support Gemini 3 tool-calling needed, and all 22 broken tool call sites across
`governance_tools.py`, `observability_tools.py`, `orchestration_tools.py`,
`quality_tools.py`, `reporting_tools.py`, and `transformation_tools.py` were fixed
file-by-file and live-verified (see the per-file Status Table rows and the resolved
Known-broken entry). Gemini 3.5 tool-calling is proven live as primary with zero
Groq fallback (a real 3-turn, 5-tool-call conversation). Don't trust "the agent can
do X" for anything you haven't personally live-verified through a real chat request
— that discipline is what caught every bug in that punch list.
**Gemini's `limit: 0` dead-end is resolved** — root cause was a deprecated model
(`gemini-2.0-flash`), not billing. Primary model is `gemini-3.5-flash` (switched from
`gemini-3-flash-preview` after hitting a hard daily cap — see the corrected Gotcha
below: **this cap is a flat 20 requests/day tied to this specific key/project, not a
preview-vs-GA distinction** — `gemini-3.5-flash` hits the identical `limit: 20` wall).
The `iteration_count`/`recursion_limit` miscalibration fix and every other hardened
agent mechanism (message bounding, tenant_id force-override, timeout/fallback) are
re-verified live and hold on the current stack. **Both providers' daily quotas are a
real, recurring operational constraint, not a one-off** — Groq's shared org-level TPD
budget and Gemini's 20/day cap have each been independently exhausted mid-session
more than once now. Budget both deliberately in any session doing live-LLM
verification, and when a session's env temporarily points `PRIMARY_LLM_MODEL` at a
different model for testing, always confirm it's restored via a real config check
before ending — `docker compose restart` does not reload `.env` changes, only
`up -d --force-recreate <service>` does (see Gotchas).

**Frontend:** Phase 0 (design sign-off), **Phase 2 (scaffold + design system), and
Phase 3 (auth design) are all complete.** `dataops-agent/frontend/` is a real Next.js 15 App Router project now
(not just reference docs) — locked tokens in `src/styles/tokens.css` (light + dark),
self-hosted real font files in `public/fonts/` (General Sans/Fraunces/JetBrains Mono,
latin subset, no CDN calls), and a 10-component core library in `src/components/ui/`
(Button, Card, Badge, Input/Select, Table, Modal, Toast, Tabs, Progress, Skeleton).
`npm run build` and `npm run dev` both verified clean; component library visually
verified in both themes via Playwright screenshots against a live dev server — this
caught and fixed 3 real dark-mode contrast bugs that code review alone would have
missed (see `tokens.css`/`components.css` comments and the git log). **Phase 3's auth
design is fully locked** — password, Google OAuth, and email-code (passwordless, via
Resend) — see `FRONTEND_BUILD_PLAN.md`'s "Phase 3 decisions" section for the complete
design; zero auth code has been written yet, this was a design-only milestone. Full plan —
19 phases across two parallel backend tracks (auth/profile, and billing/metering/
team) interleaved with frontend build phases — is in **`FRONTEND_BUILD_PLAN.md`**
at repo root; read it before starting any frontend work. Locked decisions:
- Typography: General Sans (UI/body) + Fraunces (display) + JetBrains Mono (code), self-hosted
- Palette: Midnight `#122C4F` / Pearl Perfect `#FBF9E4` / Noir `#000000` / Ocean `#5B88B2` — derived token values in `dataops-agent/DESIGN_TOKENS.md`
- Stack: Next.js 15 App Router, Zustand, Chart.js + react-chartjs-2, ported design-system CSS (not Tailwind), JWT in localStorage for v1

**Next action:** Phase 1 (usage metering foundation) is implemented and mostly
live-verified — see Status Table — with 2 of 3 call sites (`incident_triage`,
`transform_generation`) still needing a live re-check once Gemini/Groq quota
allows (regression-tested and code-identical to the proven path in the meantime).
**Phase 4 (onboarding profile storage) is complete and live-verified.** **Phase 5
("Non-password auth: Google OAuth + email-code") is complete and fully live-verified
end-to-end for all 3 methods** — see Status Table's two rows, including a real user
click-through of Google's actual consent screen (auto-linked onto an existing
email-code-created account, confirming auto-link works from either originating
method). **Phase 6 (Auth + Onboarding UI) is complete and fully live-verified** —
real signup/login/onboarding pages for all 3 auth methods, the login disambiguation
workspace picker, and the non-blocking signup nudge, all wired to the real backend
and live-verified via a Playwright script driving a real browser plus a real user
click-through of Google's consent screen (which surfaced and got a real fix for a
clock-skew bug — see Gotchas). Building this UI also surfaced and fixed a real
backend gap: the workspace-picker resubmit design didn't actually work for
email-code/Google (see Status Table and Gotchas). **Phase 7 (App shell) is
complete and fully live-verified** — sidebar/topbar/command palette
(Ctrl+K)/notifications panel/AXIOM FAB/light-dark theme toggle, wrapping 18
authenticated routes (17 new stubs + the Phase 6 dashboard stub, moved into
a new `(app)` route group) behind its own auth guard. Pure frontend, no
backend changes. **Phase 8 (Chat sessions + tool trace) is complete and
fully live-verified** — `GET /chat/sessions` (private-per-user, no
migration needed) and a real tool-call trace now populate the
previously-unused `ChatMessage.tool_calls` column; the live-LLM round trip
that was blocked by exhausted quota at the end of the Gemini-migration
session was re-attempted successfully once Groq's quota freed up — a real
chat message produced a real Groq tool call (`list_data_sources`, real
tenant_id, real result), correctly stored and retrievable via both the
`POST /chat/` response and `GET /chat/sessions/{id}/history`, and the
session correctly appears in the list. No frontend chat UI was built this
phase — that's Phase 10, which also needs the LangChain v1 upgrade first
for Gemini tool-calling (see Known-broken).
**Phase 9 (Dashboard) is complete and fully live-verified** — 7 KPI cards,
a real-incident-only health banner, two Chart.js trend charts, Recent
Pipeline Runs, a Pending Approvals card wired to real approve/reject
actions, and an AXIOM Activity card reading Phase 8's real session list —
all backed by real endpoints (`GET /analytics`, `/analytics/quality`, and
a new `/analytics/recent-runs`), no fabricated data anywhere. `@tanstack/
react-query` and `chart.js`/`react-chartjs-2` introduced this phase, per
plan. Two real bugs caught by live screenshot verification (not code
review) and fixed in the same commit: `.stats-grid`/`.metric-card`/
`.metric-value`/`.metric-change` were referenced from the prototype but
never actually ported into this project's CSS back in Phase 2 (cards
rendered as unstyled stacked rows); and two KPI cards used
`--midnight-500`/`600` as value text color, the same dark-on-dark
contrast bug documented earlier this project. Also fixed a real
regression this phase would have caused: replacing the dashboard stub
would have removed the only logout affordance in the whole app (Phase
7's topbar avatar only ever showed an identity toast) — added a proper
account dropdown with email/role + Log out.
**Cross-cutting fix, done ahead of Phase 12**: the silent-401-as-empty-state gap
flagged in Phase 9's verification (a Gotcha, not a Known-broken row) is now fixed —
`frontend/src/lib/api.ts`'s shared `request()` function now detects a 401 on any
request that carried a bearer token, clears the session, and redirects to
`/login?expired=1` (toast + URL cleanup on the login page). Live-verified with a
genuinely expired, correctly-signed JWT. See Status Table.
**Phase 12 (Core DataOps screens) is complete and fully live-verified** — Sources,
Pipelines, Quality, Incidents, CI/CD, Approvals (merged), and Governance all built,
replacing their Phase 7 stubs, each wired to real backend endpoints with create/
update/delete/action flows and live-verified via Playwright (both themes
screenshotted, no contrast issues). Pulled ahead of Phase 10 since Phase 10 is
blocked on the LangChain v1 upgrade and Phase 12's backend surface had zero LLM
dependency. Three real bugs found via live verification (not code review) and fixed
in the same commits as the screens that surfaced them — see their own Status Table
rows for detail: `DELETE /pipelines/{id}` 500ing on any pipeline with run history
(found building Pipelines); the merged-approvals endpoint's risk-level bucketing
using a 0-1 scale against a real 0-100 `risk_score` (found building CI/CD); and
Governance's Audit Log tab not invalidating after contract create/validate, showing
a stale pre-mutation snapshot (found building Governance). Also pulled forward
Phase 11's lineage-auto-population half as pre-work (see its own Status Table row)
since Governance's lineage tab needed it to not be empty — Phase 11's remaining
scope (`KpiValue` writes on quality-check runs) is unaffected and still pending.
`npm run build` (production) verified clean after fixing 2 real ESLint errors
(`react/no-unescaped-entities` in Incidents, unused imports in Sources) that the
dev-server-only verification loop for those two screens hadn't caught.
**Phase 10 (AXIOM chat UI) is complete and fully live-verified.** Real 3-panel
screen (`frontend/src/app/(app)/chat/page.tsx` + `src/components/chat/*`) wired to
`GET /chat/sessions`, `GET /chat/sessions/{id}/history`, and a new
`POST /chat/` client — session list, saved prompts (client-side, per the locked
gap-analysis decision), the composer, personality/operation mode selectors, real
tool-call trace rendering, and a real "Attached Context" data-source picker (sends
`context: {source_id, source_name}`, which the agent actually reads — see Status
Table). **Zero-cost checks are fully live-verified** (session list, empty state,
saved prompts, attached-context picker, both themes, via Playwright against the real
backend — no LLM calls needed for any of this). **Live-send checks are only
partially verified**: the graceful-error path is proven live (a real backend 500
degrades to a clear inline message, composer stays usable, no hang — see Status
Table), which also caught and fixed a real dead-code bug (`isError` render branch
was unreachable). **All previously-deferred live-send checks are now closed,
live-verified in a follow-up session** — Gemini's daily quota had reset by then,
confirmed fresh with a cheap probe before spending anything further. Verified live
via a real Playwright-driven browser against a real seeded tenant: multi-turn
continuity (a real 2-turn conversation — turn 2, "how many sources did you find,"
correctly answered by referencing turn 1's tool result with zero re-call of the
tool, confirmed against the real `GET /chat/sessions/{id}/history` payload, not
just the rendered UI); tool-call trace rendering (both the inline per-message block
and the right panel's session-wide aggregate render the same real trace — two
`.chat-tool-name` DOM nodes per call is correct-by-design, one per panel, not a
duplication bug, since `ContextPanel` renders its own `ToolCallBlock` for the
aggregate log); personality/operation mode switching (network-captured the real
`POST /chat/` request payload and confirmed `personality_mode`/`operation_mode`
matched the UI selectors exactly — `founder`/`advisory` selected, `founder`/
`advisory` sent); and the advisory-mode approval-gate flow (a real blocked
`list_data_sources` call under `operation_mode: "advisory"` rendered the correct
"Needs approval" badge and callout copy with a working link to `/approvals`, **and
settled the approval-persistence question with live proof**: a real
`ApprovalRequest` row was written and appeared via both `GET /approvals` and
`GET /approvals/merged` — the prior code-read finding was correct, `api/v1/chat.py`'s
own `ApprovalRequest` creation, not `approval_gate_node` itself, is what persists
these; see the now-resolved Known-broken row). **This same pass caught and fixed a
real, previously-unknown bug**: every blocked call reported `risk_level: "high"`
regardless of its actual tier, because `approval_gate_node` never attached a
`risk_level`/`reason` to the blocked call dict — `chat.py`'s
`pa.get("risk_level", "high")` always hit that hardcoded default. Fixed (now
threads the real `personality.get_risk_level()` per call) and re-verified live: the
same `list_data_sources` call now correctly reports `"low"` with a real reason
string, in both the API response and the DB row. Regression test added
(`test_blocked_tool_call_carries_its_real_risk_level_not_hardcoded_high`,
`test_agent_graph.py`); full suite 103 passed. All Gemini calls in this pass ran on
`gemini-3.5-flash` primary with zero Groq fallback triggered (~5 real Gemini calls
total, well inside the 20/day cap — Groq's own quota was never actually needed for
volume, since Gemini handled every check cleanly). **Phase 10 is now fully complete
and live-verified — no outstanding checks.**
Note: `chart.js`/`react-chartjs-2` installed as of Phase 9 (Dashboard charts, their
trigger point). Zustand still isn't installed — Dashboard's data is all server state via
React Query, no client-side global state complex enough to need it yet; it lands
whenever a phase actually needs it.

**Outstanding on the user's side:** none currently — Google OAuth credentials
(resolved, Phase 5/6/7) and Gemini's `limit: 0` dead-end (resolved, see above) were
the only two open items and both are closed.

**Phase 13 (transform-run persistence + Data Catalog aggregation) is complete and
fully live-verified.** New `TransformRun` table persists every real SQL/pandas
transform execution (never dry-runs/EXPLAIN or generation-only calls) — wired into
`POST /run/sql`/`POST /run/pandas` (`origin: "manual"`) and the chat tools
`execute_sql_transform`(`dry_run=False`)/`run_python_transform`
(`origin: "chat_agent"`), the latter two gaining `user_id`/`session_id` params so
`agent_node`'s existing generic force-override loop covers them automatically (same
pattern already proven for `request_approval`). New `GET /api/v1/catalog/` is a thin,
tenant-scoped aggregation over every `DataSource.schema_snapshot` — no new table —
flattening each source's real per-table-keyed snapshot shape into one normalized
list, including never-profiled sources (`profiled: false`) rather than hiding them.
**Two real bugs found and fixed along the way, both live-verified**: (1)
`TransformGenerator._resolve_schema()` read `snapshot.get("columns", [])` assuming a
flat shape, but `SchemaProfiler` always nests columns under a table-name key with
different column-dict field names (`column_name`/`data_type`/`is_nullable`, not
`name`/`type`/`nullable`) — every NL→SQL/pandas generation had been running
schema-blind regardless of how much real profiling data existed; fixed, and a real
Gemini call now correctly generates SQL referencing real, otherwise-unguessable
column names. (2) `invoke_llm()` (`services/llm_service.py`, a separate call path
from the agent graph — used by `TransformGenerator`, `IncidentManager`, etc.)
crashed on Gemini 3.5's list-shaped structured content blocks, the same failure
class as the agent-graph's `_content_as_text` fix but on an uncovered call path;
fixed by moving that normalization into a shared `content_as_text()` in
`llm_service.py`. All Phase 13 work live-verified against a real CSV file (a
successful filtered `run/pandas` execution and a real syntax-error case, both
correctly persisted; the source's real profiled schema correctly reflected by the
Catalog endpoint). Full suite: 119 passed.

**Phase 14 (Transforms + Data Catalog screens) is complete and fully
live-verified.** A Phase 13 addendum landed first: `GET /api/v1/transformations/runs`
(tenant-scoped, newest-first, `limit`/`offset`/`source_id` filter) — Phase 13 built
`TransformRun` persistence but no read endpoint, and the History tab needed one.
Frontend: `frontend/src/app/(app)/transforms/page.tsx` — 4 tabs (Natural Language,
SQL Editor, Python Editor, History), all wired to real endpoints (`generate/sql`,
`generate/pandas`, `run/sql`, `run/sql/dry-run`, `run/pandas`, `preview/pandas`,
`explain`, and the new `runs` list), a "Send to Editor" handoff from NL results, and
Replay (pure frontend state — loads a past run's code/source back into the right
editor and switches tabs, no backend replay endpoint). `frontend/src/app/(app)/catalog/page.tsx` —
real `GET /catalog/` data, client-side search over table/column/tag names, and a
Sync Metadata action that sequentially calls the existing `POST /sources/{id}/profile`
per unique source with "profiling N of M" progress (Catalog otherwise had no refresh
path). Added a `.code-block` CSS class (`components.css`) — referenced in the master
design prototype but never actually ported, same "prototype class never made it into
our stylesheet" bug class documented elsewhere in this file; used `--midnight-900`/
`--on-dark` per the established permanently-dark-surface pattern. **Live-verified
end-to-end**: a real `employee_data.csv` source uploaded/registered/profiled; a real
Gemini call generated pandas code that correctly referenced real column names
(`department`/`name`/`salary`), confirming Phase 13's schema-grounding fix still
holds on a second, independent source; Execute ran the real code and returned 4 real
filtered rows; the run persisted and appeared in History via the real endpoint;
Replay correctly reloaded the code/source and switched tabs; Catalog showed the real
profiled table with working search, and Sync Metadata's effect was confirmed via the
Last Profiled timestamp genuinely advancing. Both themes screenshotted, no contrast
issues (the dark-mode pure-black page background is intentional — Noir is one of the
4 locked palette colors). `npm run build` (production, Turbopack) clean, 27 routes.

**Phase 15 (Plan/quota + Team, Track 2's largest phase) is complete and fully
live-verified.** Kicked off with a Resend health check (real send confirmed
working, `last_event: "delivered"` via Resend's own API — but the account is still
sandboxed to only the owner's own verified address; real invites to arbitrary
teammates will 403 until a domain is verified at resend.com/domains, a you-side
action) and a real-usage check against the proposed Starter tier before enforcement
shipped, which caught and fixed a real miscalibration before it went live (see
Gotchas and the "Plan/quota enforcement" Status Table row). Six sub-steps, each its
own commit: (1) `require_role()` shared dependency, retrofitted onto CI/CD approve/
reject — closes that Known-broken row; (2) retrofitted onto the rest of the approved
high-priority list (pipeline/source/quality-rule delete, run/sql, run/pandas, cicd
incident resolve); (3) team invites — real `TeamInvite` table, Resend delivery,
accept-into-existing-tenant with a locked role, live-verified with a real delivered
email and a real subsequent login; (4) team member management — list/role-change/
soft-removal, which surfaced and fixed a real gap (`User.is_active` was never
enforced at login, so "removed" members could still log in — now fixed for the
password path, live-verified); (5) plan/quota enforcement — 3 hardcoded tiers
(Starter/Growth/Scale), a documented credit formula, `enforce_quota()` wired onto
the 4 clearest cost/volume drivers, live-verified against *real pre-existing usage
data* (not synthetic seeds) for both the hard-block and soft-warn cases; (6)
`BillingService` interface with Stripe stubbed behind honest `501`s, `change_plan()`
real today as a documented dev-mode stand-in. Also folded in and closed the
long-standing "CI/CD high-risk commits double-book their approval" Known-broken row
(own commit, live-verified with a real non-monkeypatched risk calculation reaching
65/100 through the actual scoring logic). See each sub-step's own Status Table row
for full verification detail — every one was live-verified against the real running
server, not just the pytest suite. All three of the phase's original verification
gates (real invite→accept round trip; a restricted role actually blocked on CI/CD
approve/reject; quota soft-warn/hard-block triggering against real usage data) are
closed.

**Phase 16 (Settings persistence) is complete and fully live-verified.** Five
sub-steps, each its own commit: (1) the `get_agent()` cache re-keying fix + per-tenant
AI model override — closes Phase 0's approved pushback #2, live-verified with two
real, different LLM providers on two real tenants and zero cross-contamination
(the exact test that Gotcha demanded before this could ship); (2) workspace config
(name/timezone/description) via `GET/PATCH /api/v1/settings/`, reusing the
previously-unused `Tenant.settings` JSON column; (3) notification prefs, which
surfaced and fixed a real, separate, deeper bug — `NotificationService` had
referenced entirely nonexistent `AXIOM_*`-prefixed `Settings` fields since it was
written, meaning it could never have sent a single real Slack message or email to
anyone, tenant-specific or global, until this session; (4) theme server-persistence
(`User.theme`, per-user not per-tenant, deliberately not a JWT claim) via
`GET/PATCH /auth/me`; (5) platform API keys — full CRUD (create/list/revoke) with
the raw secret shown exactly once, deliberately scoped short of request
authentication (tracked as its own phase-sized item in Not-yet-built). Building (5)
also caught a second occurrence of Phase 15's `Read`-near-EOF tooling bug, this time
revealing the *original* Phase 15 fix had been incomplete — `TeamInvite.created_at`
had silently carried a real, undocumented index in production since Phase 15
shipped. See each sub-step's own Status Table row for full verification detail —
every one was live-verified against the real running server. Full backend suite:
213 passed.

**Phase 17 (Team, Billing, Settings UI) is complete — all three screens built and
fully live-verified.** The locked spec lives in `FRONTEND_BUILD_PLAN.md` under
"Phase 17 decisions (locked)". **Settings (`/settings`)** — 5 tabs (Workspace,
Notifications, AI Model, Theme, API Keys), all wired to real Phase 15/16
endpoints, no backend changes. Live-verified via two Playwright scripts (owner +
a re-logged-in downgraded viewer) covering every round trip including two
build-session amendments: the `notify_on` explicit-`false` deep-merge survives a
refresh (independently confirmed via raw `curl` first), and the raw API-key
secret is provably absent from both `localStorage`/`sessionStorage` and never
resurfaces in the DOM — see its own Status Table row and the Known-broken row for
the one accepted piece of tech debt (the AI Model tab's allowlist is hardcoded,
not fetched). **Team (`/team`)** — member roster + role change + soft-removal +
invite create/list/revoke, all mutation controls hidden (not just disabled) for
non-Owner/Admin. Building it surfaced a real gap in the original locked spec
(invite *creation* was speced, invite *acceptance* wasn't) — closed with a new
public `/invite/accept` page in the same session, not deferred. Live-verified
end-to-end including a genuine Resend delivery, a real accept round trip through
a clean unauthenticated browser context, 2-owner guard coverage (both the blocked
and the correctly-unblocked direction), and a live JWT-replay-after-removal check
whose result (access persists until expiry, `is_active` isn't re-checked
per-request) is now tracked as a real fix item — **Known-broken, not just a
Gotcha**, with severity and the actual token TTL (`JWT_EXPIRE_MINUTES=60`)
stated, flagged as a Phase 19 candidate. **Billing (`/billing`)** — plan card
with an Owner/Admin-gated upgrade/downgrade picker (`POST /change-plan`) and 4
real usage bars off `GET /billing/usage` colored by the backend's own `status`
field, Stripe-stubbed checkout/invoices honestly labeled "Coming soon." Building
it found and live-confirmed a real backend gap (also tracked in Known-broken, not
just documented): `change_plan()` allows any downgrade unconditionally, even one
that immediately puts current usage over the new plan's limits — no payment
gate either. The UI reflects this honestly (a non-blocking warning naming the
specific over-limit resource, not a fake block) rather than hiding it. All of
Phase 17's own verification gates are closed: invites (Resend delivery + full
accept round trip), roles (guard mirroring in both directions), plan/quota
display (real seeded usage, not all-zero), and every settings tab. No new
backend/migration work was needed anywhere in this phase — every endpoint it
wired to already existed and was live-verified (Phase 15/16).

**Phase 18 (AI Employees + Landing page) is complete — both screens built and
fully live-verified.** AI Employees: 6 tiles (AXIOM real/active + 5
honestly-locked employees), zero backend calls, three deliberate deviations from
the literal master design (no waitlist button, no marketplace button, no
per-tile pricing — deferred until real Stripe pricing exists). Landing page:
replaces the Phase 2 component-showcase scaffold that had silently occupied
root `/` since Phase 2; platform-first copy proposed and signed off in full
before any code was written; social-proof section omitted entirely (no
fabricated testimonials/logos/counts); roster copy shares a single source of
truth with `/ai-employees` via new `lib/employees.ts`/
`components/shared/EmployeeCard.tsx` so the two pages structurally cannot say
different things; auth-aware CTAs (nav + AXIOM tile) verified in both
directions with a real registered user. A real routing mistake (`/register`
instead of the actual `/signup` route) was caught by checking the real `app/`
directory before running any live test, not by a failed assertion. Verification
covered every item both build sessions' standards required: explicit
rendered-text audits (not spot-checks) on both pages, both themes × both
desktop/mobile widths on the landing page, a genuinely clean logged-out
context, every link fetched and confirmed to resolve, and the already-known
app-wide hydration-mismatch warning (root layout's theme pre-paint script,
found during the AI Employees build, confirmed — not re-discovered — on the
landing page too). One small isolated bug (AI Employees' "Coming Soon" scrim
being nearly invisible) was found and fixed in the same session it was found.
**Deployment was explicitly out of scope** — both screens are built and
verified locally only; real production deployment stays gated on the domain
purchase (see Outstanding items), and a new Not-yet-built entry now also flags
Privacy Policy/Terms of Service pages as required before any real production
signup traffic, grouped with that same domain-purchase cluster.

**Next action:** Phase 18 is done. Phase 19 (Polish) is the only phase left;
its full execution plan is locked in `FRONTEND_BUILD_PLAN.md`'s "Phase 19
plan (locked, 2026-07-22)" section. **P0 item 1 (the unified permission
spec) is done and fully live-verified** — see its Status Table row below.
Before continuing to item 2, the commit was checkpointed against the
user's own 3-point confirmation (demote-vs-deactivate distinction proven
live with a real never-reissued JWT; the cross-consumer test pasted and
read, not just reported green; a real SQL-echo capture confirming exactly
1 `users`-table query per request across a multi-capability-check
request) — all 3 held, no gap found. **P0 item 2 (file-upload UI for
CSV/Excel) is now also done and fully live-verified** — see its own
Status Table row below, including a real permission-spec gap it
surfaced and closed (`POST /uploads/register` had no `require_permission`
gate at all). **P0 item 3 is now fully done** — 3(a) (`resolve_identity()`'s
missing `is_active` filter) shipped and live-verified this session, see
its own Status Table row; 3(b) shipped earlier with item 1. **P0 item 4
(invite email link path fix) is now also done and fully live-verified**
— see its own Status Table row, including a real end-to-end proof (a real
Resend-delivered invite email's link opened in a real browser and
correctly resolved). **P0 item 5 (scheduled pipelines cluster) is now also
done and fully live-verified — this closes out P0 entirely.** See its own
Status Table row for the full detail; the short version: the arg-mismatch
bug turned out to be the smaller half of a bigger finding — the entire
dynamic per-pipeline scheduling design (`Scheduler.register()`/`sync_all()`)
was never actually reachable from the running app at all (nothing calls
it, and even if something did, it mutates a schedule dict that isn't
shared across the `backend`/`celery_beat` process boundary). Replaced with
a real, live, static-polling beat task (`check_scheduled_pipelines()`,
every 60s, same proven pattern as the existing `check_all_freshness()`)
that now genuinely fires scheduled pipelines — live-verified against a
real `* * * * *` schedule landing 3 real, correctly-timed runs one minute
apart, exactly the locked plan's own verification gate. Also added
save-time cron validation and real next-run/last-run visibility on the
Pipelines screen. **All 5 P0 items are now done.** See
`FRONTEND_BUILD_PLAN.md` for the full capability table, the P0/P1/P2
partition (now kept current as a **Phase 19 partition status** — see that
file's own top-of-section note), the verification plan (including a
cross-consumer regression test proving REST and chat share one map, not two
copies that happen to agree today). `dataops-agent/USER_MANUAL.md` itself is the
authoritative, code-derived reference for what every screen actually does
today — read it alongside this file for any Phase 19 work.

**Dark theme redesign is started but NOT complete** — the token change
itself landed (`tokens.css`, warm near-black neutral surfaces replacing
the old pure-black-page/Midnight-navy-card pairing, Ocean blue restricted
to accents only, measured 4.5:1+ contrast on every text pair) but that
commit's own message says its required next step — **a screenshot
verification pass across every screen, both themes** — was deferred, and
it still hasn't happened. Two real, unrelated bugs were found and fixed
while starting that verification (own commits, see Status Table): Chart.js
dashboard trend colors were silently never resolving CSS custom properties
at all in *either* theme (Canvas 2D silently no-ops on an unresolved
`var()`, not an error — pre-existing, not introduced by the redesign), and
a pre-existing `react/no-unescaped-entities` production-build failure on
the Team screen (unrelated to dark theme, just surfaced by running
`npm run build` during this work). **Next session's dark-theme work is
exactly that deferred screenshot pass** — not a design decision, a
verification gate that's still open. See `FRONTEND_BUILD_PLAN.md`'s "Dark
theme legibility" section for the token mapping and this file's Status
Table for the three dark-theme-adjacent commits.

**Separately, this session also did a Phase 19 polish pass** (unplanned,
opportunistic — not part of the original P0/P1/P2 partition): fixed the
landing page silently defaulting to dark mode for dark-OS visitors (light
is the signed-off public default); found and fixed a real race condition
in chat's "New Chat" button (not just a missing-feedback UX gap as
originally diagnosed — a stale in-flight response could leave the
composer locked or silently merge into the wrong session); swept the
app's interactive controls for other silent no-ops (none found beyond
New Chat — the remaining decorative elements are all self-disclosing or
already tracked in `FRONTEND_BUILD_PLAN.md`'s P1 list); rebuilt the
landing page in full (real logo, a real screenshot carousel from a
genuinely seeded demo tenant, real About/Contact sections); and
re-verified live, from scratch, the headline claims of the unified
permission spec (demote-vs-deactivate distinction, the cross-consumer
test, the one-query-per-request SQL echo). See each item's own Status
Table row.

---

## 1. Architecture Summary

**Stack:** FastAPI (async, Python 3.11/3.13) + SQLAlchemy 2.0 async + PostgreSQL 16 + Redis + Celery (worker + beat) + LangGraph/LangChain v1.x agent (`gemini-3.5-flash` primary, Llama 3.3 70B via Groq fallback) + Next.js 15/React 19 frontend (source present but incomplete — see §2).

**Services** (`dataops-agent/docker-compose.yml` and `backend/docker-compose.yml` — two near-duplicate compose files exist, see Gotchas):
- `backend` — FastAPI app (`backend/main.py`), port 8000, mounted as a live volume (`./backend:/app`) so container edits are picked up without rebuild.
- `postgres` — Postgres 16-alpine, port 5432, db `dataops`.
- `redis` — Redis 7-alpine, port 6379. DB 0 = general cache, DB 1 = Celery broker, DB 2 = Celery result backend (`config.py`).
- `celery_worker` / `celery-worker` — runs `celery -A services.celery_app worker --concurrency=4`.
- `celery_beat` / `celery-beat` — runs the periodic scheduler (static + dynamically-registered per-pipeline schedules).
- `frontend` — **commented out** in root `docker-compose.yml`. Not started by `docker compose up` even if the source existed and built.

**Core end-to-end flow (chat → agent → tool → approval):**
1. Client calls `POST /api/v1/chat/` (JWT-authed) — the only chat entry point as of the public-launch risk cluster session (2026-08-02): the unauthenticated `WS /ws/chat/{tenant_id}/{session_id}` route this line used to also describe was confirmed dead (zero frontend usage) and deleted outright rather than fixed — see §2/§3 and the now-resolved "WebSocket chat auth" Known-broken row.
2. `agent/dataops_agent.py` runs a LangGraph `StateGraph`: `inject_system` → `agent` (LLM bound to all tools via `.bind_tools`) → `approval_gate` → conditionally `tools` (a stock `ToolNode`) → loops back to `agent`, or `END`. Hard cap of 20 iterations, no config knob.
3. `personality.py` supplies the system prompt per `PersonalityMode` (engineer/founder/analyst/auditor) and gates tool calls per `OperationMode` (advisory/assisted/autonomous/audit) via `requires_approval()`, which checks a hardcoded `RISK_ACTIONS` risk table (low/medium/high).
4. If a tool call requires approval, `approval_gate_node` blocks it and injects an "Approval Required" message into the chat — but (see Gotchas) this in-graph gate is **not the same system** as the DB-backed approval queue read by `GET/POST /api/v1/approvals`.
5. The real, DB-backed approval workflow lives in `modules/governance/policy_engine.py` (`PolicyEngine`): a request is created, an admin/owner calls `POST /approvals/{id}/approve`, which calls `execute_approved_action()` → looks up the action in a hardcoded `TOOL_REGISTRY` dict → dynamically imports and invokes the real function via `importlib`.
6. Tool implementations live in `agent/tools/*.py`, one file per domain (ingestion, transformation, quality, orchestration, observability, governance, reporting, cicd), and call into `modules/*` for the actual work.

**Data model & tenancy:** Postgres, 17 SQLAlchemy models across `models/all_models.py` (13 models: Tenant, User, DataSource, Pipeline, PipelineRun, QualityRule, Incident, LineageNode, LineageEdge, AuditLog, ApprovalRequest, ChatMessage, DataContract, UsageMetric, KpiValue) and `models/cicd.py` (3 models: PipelineCommit, PipelineDeployment, CICDIncident). This is **multi-tenant by convention, not by enforcement**:
- Every model except `Tenant` carries a `tenant_id` column, but only `User`, `DataSource`, and `Pipeline` make it a real FK to `tenants.id` — the other 13 use a bare `String` with no FK constraint.
- Tenant scoping is entirely manual: `get_current_user()` decodes the JWT and returns `tenant_id` straight from client-supplied claims (no DB re-check — **this is still true for `tenant_id` specifically**; as of Phase 19's unified permission spec, `get_current_user()` *does* now re-read `is_active`/`role` fresh from the DB every request, see the new Status Table row, but `tenant_id` itself is not re-verified against anything); every endpoint/manager class is individually responsible for adding `.where(Model.tenant_id == tenant_id)`. There is no base query class, no session-level hook, no middleware, and **no Postgres RLS** (`create_enums.sql` only defines enum types).
- Spot-checked call paths (`dag_manager.py`, `policy_engine.py`, `run_tracker.py`, `rule_engine.py`, `connector_manager.py`, `schema_profiler.py`, `sql_runner.py`, all of `api/v1/`) do filter correctly today. The invariant holds only as long as every future query remembers to add the filter — nothing in the framework enforces it. Treat "did you scope this query by tenant_id?" as a mandatory review question for every new query in this codebase.

**Background jobs (Celery):** static beat schedule in `services/celery_app.py` — freshness check every 15 min (real), anomaly detection hourly (stub, logs only), daily reports every 24h (stub, logs only), CI/CD post-deploy health check every 60s (real), **scheduled-pipeline check every 60s (real, Phase 19 — see below)**. `modules/orchestration/scheduler.py`'s `Scheduler` class was originally *designed* to inject dynamic per-pipeline schedules into `celery_app.conf.beat_schedule` at runtime — **this was never actually the live mechanism and is not one now**: confirmed via a repo-wide grep that `Scheduler.register()`/`unregister()`/`sync_all()` are never called from anywhere in the running app (not at pipeline create/update, not at container startup), and even if they were, mutating `celery_app.conf.beat_schedule` from the FastAPI `backend` process has no effect on the actual, separate `celery_beat` process's own in-memory schedule (Celery's default `PersistentScheduler` isn't shared across OS processes) — a genuinely shared store like RedBeat would be needed to make that design work at all. `Scheduler` is kept in place, not deleted (its own logic is internally correct post an earlier enum-case fix, and has its own test coverage), but is dead code relative to what actually runs pipelines on schedule today. **The real, live mechanism (Phase 19)** is `services/tasks.py`'s `check_scheduled_pipelines()` — a static, always-on beat entry (matching the proven pattern of `check_all_freshness()`) that polls every `ACTIVE` pipeline with a `schedule_cron` directly against the DB each tick and fires any whose cron matches the current UTC minute via `croniter.match()` (the already-installed `croniter` dependency, genuinely used now — the old `_parse_cron()` hand-roll in `scheduler.py` is only reachable through the still-dead `Scheduler` path). Each firing creates its own fresh `PipelineRun` row (`triggered_by="scheduled"`) before delegating to the same execution core (`_execute_run()`) the manual/API trigger path uses. Save-time cron validation (`croniter.is_valid()`) is enforced in `api/v1/pipelines.py` on every write path (`create_pipeline`/`update_pipeline`/`set_schedule`), and `list_pipelines()` now reports a computed `next_run_at` (via `croniter`, `None` for anything not `ACTIVE`+scheduled) and the real `last_run` summary per pipeline. Pipeline "DAG" execution (`modules/orchestration/dag_manager.py`) is **not actually a DAG** — no step graph, no topological sort; a "run" is a fixed linear sequence (sync source → run quality checks → mark result).

---


## Archive

*Superseded information kept for history — do not delete, append new superseded items here as they arise.*

- **LLM fallback routing bug (fixed, pre-dates this document).** `services/llm_service.py` previously had `get_fallback_llm` always constructing a `ChatGroq` client regardless of the configured `FALLBACK_LLM_MODEL`. An inline comment at `llm_service.py:35-39` notes this was fixed to route via `_build_llm(settings.FALLBACK_LLM_MODEL, ...)`, matching whatever model name is actually configured.
- **Prior CLAUDE.md content:** none — the file was empty (0 bytes) before this rewrite. This is the first substantive version.
- **Repo previously had zero git commits.** Everything was staged (via an earlier broad `git add -A`-style setup) but never committed, and the git index carried 11,446 `node_modules/` + 84 `.next/` files because `.gitignore` had no Node/Next.js section. Resolved by adding the Node/Next.js block to `.gitignore`, unstaging those ~11.5k files plus one stray garbage index entry (`4))`, then making an initial commit of the clean scaffold baseline, followed by one commit per already-verified fix (message-history reducer bug, tool-output capping, tenant-id injection). See Status Table and the gotchas above for what's fixed.
- **`get_cicd_status` tool called back into this app's own API unauthenticated (fixed).** It took no `tenant_id` and hit `http://localhost:8000/api/v1/cicd/status/summary` via plain `httpx.get()` with no auth header — always 401'd, but silently returned fake empty defaults since `httpx` doesn't raise on 4xx. Fixed by extracting the endpoint's query logic into `services/cicd_service.py:get_status_summary(db, tenant_id)` and having both the REST endpoint and the tool (now `get_cicd_status(tenant_id: str, query: str = "")`) call it in-process. See Status Table and the new general Gotcha above (no tool should call back into this app's own API).
- **"Frontend can't build" / "Frontend directory missing from working tree" (both resolved, discovered during this session).** A prior commit (`220b07a`, "Remove stale, broken original Next.js placeholder scaffold") already deleted the broken legacy Next.js source these two Known-broken rows described (`chat/page.tsx`/`dashboard/page.tsx`/`login/page.tsx` and their missing `lib/api.ts`/`lib/store.ts`) — confirmed via `git ls-files dataops-agent/frontend`, which now lists only 5 reference/design files (`wunomo-ai MASTER DESIGN.html`, `color scheme.png`, `Wunomo ui walkthrough.pdf`, `wunomo_architecture.html`, `design-proposal.html`), all present on disk. `dataops-agent/frontend/` is a clean slate for `FRONTEND_BUILD_PLAN.md` Phase 2 — no legacy broken source to work around or delete first.
- **`RuleEngine` import bug in `business_rules.py` (fixed).** Imported `from modules.quality.rule_engine import RuleEngine` — no such class exists; the real class is `QualityRuleEngine`. Made the entire `BusinessRules` class unimportable (`ImportError` on module load) until fixed alongside the enum-case bug cluster in the same file. See Status Table and Gotchas.
- **`README.md` claims frontend is "(Coming soon)"** (`dataops-agent/README.md` Architecture section) — this is stale. Frontend source exists (partially — see Status Table "Known-broken") and was staged into git, it's just not present on disk in the current working tree and can't build due to missing `lib/api.ts`/`lib/store.ts`. Treat the README's tech-stack and API-endpoint tables as directionally correct but not exhaustive; the endpoint table in this file's Architecture Summary supersedes it for anything not listed there — see the full per-file agent reports that produced this document for the complete endpoint list (chat, uploads, sources, pipelines, quality, incidents, governance, approvals, analytics, transformations, cicd — ~40+ routes total, README only lists 9).
