# UI Rebuild Inventory — Audit Only, No Code Changed

**Date:** 2026-09-13 · **Scope:** `dataops-agent/frontend/` only. No files were edited, deleted, or
committed to produce this document — this session was read-only per instruction.

**Caveat before anything else:** the two HTML previews referenced in the request ("I'll put them in
`docs/design/`") were not present in the repo at the time of this audit — `docs/design/` was empty.
Everything below is derived from the written IA spec in the request (global rail: Home, Scheduled,
Needs you, Projects, + Settings, Team · project container: Chat, Workbench, Tasks, Agents tabs · 7
operational surfaces move inside Workbench · dark neutral theme, no blue except the logo, real
buttons, no underlined-link actions) plus a full read of the current frontend and the backend
mechanisms it depends on. If the previews land and contradict a judgment call below, that call is
what should move, not the codebase facts underneath it.

---

## 1. Reuse map

Legend: **AS-IS** reused verbatim · **RESTYLE** same logic/data, new visual treatment · **MOVE**
same page body, new URL/wrapper/nav source · **REBUILD** logic changes materially · **NO HOME** —
a decision you need to make, not something being quietly dropped.

### Routes — `app/(app)/**`

| Route | Verdict | Why |
|---|---|---|
| `dashboard` | **RESTYLE → Home** | Rich, real screen (7 KPI tiles, health banner, 2 trend charts, recent runs, approvals card, AXIOM activity feed). All of it is already tenant-scoped data, not agent-scoped, so it generalizes to a cross-project "Home" with no data-model change. Only the "Ask AXIOM" CTA and the AXIOM-flavored copy need rewriting once Home isn't implicitly AXIOM's screen. |
| `ai-employees` | **NO HOME** | Standalone roster-browsing page (same `EMPLOYEES` cards `agents/hire` already renders inline, minus the form). Nothing in the new IA is "browse employee types" as a destination. Recommend folding its content into the hire flow (already 90% duplicated there) and retiring the standalone route — but that's your call, not assumed here. |
| `projects` (list) | **RESTYLE** | Becomes the "Projects" global-rail screen. Create/rename/delete logic is untouched; only the list-vs-card presentation likely changes. |
| `projects/[id]` | **MOVE → project container** | Today this page *is* "the agent grid inside a project" — that's almost exactly the future **Agents tab** body. Becomes the container shell that hosts all 4 tabs; its current content is the default/Agents tab content, not new work. |
| `agents` (list, global) | **NO HOME** | The proposal explicitly wants a tenant-wide agents list because a hired agent doesn't always belong to a project (finding 75: an unassigned agent previously had nowhere to be found). The new IA's 4 tabs live *inside* a project, so a global, project-less agents list has no obvious slot in Home/Scheduled/Needs you/Projects. Needs an explicit decision — e.g. a "Projects" landing state that also lists unassigned agents. |
| `agents/[id]` | **MOVE** | Scope grants, token-budget progress bar, offboarding — all reused verbatim inside the project's Agents tab. Also has to keep working for an unassigned agent if the item above keeps a global agents list. |
| `agents/hire` | **REBUILD** (corrected 2026-09-14, was MOVE) | Already accepts `?project_id=` and routes back into the project on success — the *logic* is already project-scoped. But both previews render hiring as a **modal** opened from a project's Agents tab, not a standalone route — same fields (type cards, name, source-scope checkboxes), different form factor. Content/validation reuse is near-total; the shell around it isn't. |
| `chat` | **MOVE, with a real decision inside it** | Becomes the project's Chat tab. `SessionList` renders two sections today: "AXIOM Direct" (1:1 sessions, **no `project_id` on the session model at all**) and "Channels" (which **do** carry `project_id`, confirmed persisted server-side). A project's Chat tab can filter Channels client-side for free; legacy 1:1 AXIOM sessions have no project to filter by. Decide: do 1:1 sessions disappear inside a project's Chat tab, get bucketed under whichever project owns the AXIOM agent, or does Chat need every 1:1 session to become a channel? Not a UI-only call. |
| `tasks` (list, global) | **MOVE, filterable without backend work** | Tasks already carry `agent_id` (used today by `TaskCreateModal`'s agent picker). A project's Tasks tab = filter by `agent_id ∈ project's agents`, joinable client-side with data already fetched. Table/columns/rerun logic unchanged. |
| `tasks/[id]` | **AS-IS** | Plan review, approve/reject, step timeline, cost card, scope-denial card with pre-scoped "Grant access" — none of it references navigation or IA, it's reused wholesale regardless of entry point. |
| `sources` | **MOVE → Workbench** | See §2 — the "which data does a project's Workbench show" question applies to this and the next 8 rows equally. Page body is untouched either way. |
| `catalog` | **NO HOME (within the 7)** | Real, built screen (search, sync-metadata, table/column browser) — not in your named list of 7. Needs a decision: own Workbench sub-nav slot (8th), folded into Sources, or folded into Lineage (it's the closest conceptual sibling — both browse what's known about the data). |
| `pipelines` | **MOVE → Workbench** | Untouched. Already carries `schedule_cron` per pipeline — relevant to the new "Scheduled" screen, see §3. |
| `transforms` | **MOVE → Workbench** | The one operational page that is *not* a simple list/CRUD screen — a 4-tab workspace (Natural Language / SQL Editor / Python Editor / History) with its own internal tab state. Wrapping it in a Workbench sub-nav costs nothing structurally, but it's the highest-surface-area page of the 7, worth flagging so it isn't estimated at "just a table" size. |
| `quality` | **MOVE → Workbench** | Standard CRUD pattern, untouched. |
| `incidents` | **MOVE → Workbench** | Standard pattern, two modals (log + resolve). Also currently has a real, known backend bug (`_check_freshness()` duplicate-incident loop, logged in `SESSION_LOG.md` 2026-08-19, tens of thousands of stray `OPEN` rows in some tenants) and a hardcoded `limit=50` with no real pagination — not caused by and not fixed by this rebuild, but worth knowing before someone screenshots this screen for a new self-test guide. |
| `governance` | **SPLIT DECISION, not a clean MOVE** | This page is 3 tabs: **Lineage**, **Contracts**, **Audit Log**. Your 7-surface list names only "Lineage." Contracts (data-contract CRUD + validation) and this page's own Audit Log tab both need an explicit destination — Contracts is the natural sibling of Quality; this Audit Log tab already duplicates the *concept* of the tenant-wide `audit` route below (see next row), which is currently just an empty stub. Recommend deciding these two together rather than independently. |
| `automations` | **NO HOME (stub)** | `StubPage` — no real content exists. Zero cost to defer indefinitely; flagging only so it's a decision, not a silent drop. |
| `cicd` | **MOVE → Workbench, redundant surface noted** | KPI tiles + 2 tabs (Commits, Deployments). Approve/reject on pending commits happens *both* here and on the tenant-wide Approvals screen (via `getMergedApprovals`) today — pre-existing duplication, not something this rebuild creates, but worth resolving once Approvals becomes "Needs you." |
| `approvals` | **REBUILD → Needs you** | Backing endpoint (`list_merged_approvals`, unifies agent-action + CI/CD approvals with a bucketed risk level) is exactly right for "Needs you" and needs no backend change. The *screen* should absorb this plus the Topbar's existing "active tasks needing attention" rail (`needs_attention`/`action_text`, already computed server-side) — two already-built data sources merging into one new screen, not new plumbing. See §3. |
| `audit` | **NO HOME (stub)** | `StubPage`. Sits awkwardly next to Governance's real, built Audit Log tab (see above) — two "audit" concepts, one real, one placeholder. Resolve together. |
| `team` | **RESTYLE** | Real, built (members table, invites, role gating). Explicitly named as a persistent global item in your spec — survives, restyle only. |
| `billing` | **NO HOME** | Real but functionally inert (plan card, usage/quota bars, "coming soon" checkout). Not named in the global rail. Low risk either way — likely nests under Settings or sits beside Team — needs a decision, not urgent. |
| `settings` | **RESTYLE** | Real, 6 internal tabs (Workspace/Profile/Notifications/AI Model/Theme/API Keys). Explicitly named as persistent — survives, restyle only. |
| `analytics` | **NO HOME (stub)** | `StubPage`, found during this audit, not previously called out. Zero content, zero cost to leave undecided. |

### Outside `app/(app)/` — confirmed untouched by this rebuild

`app/page.tsx` (public landing), `app/login`, `app/signup`, `app/invite/accept`, `app/onboarding`,
`marketing-site/` (separate git branch per `CLAUDE.md`'s repo layout) — none of these render inside
the authenticated app shell this rebuild targets. Per your item 5, the landing page and marketing
site are explicitly out of scope; login/signup/invite use `AuthShell`, a separate two-column layout
that never touches `Sidebar`/`Topbar`/`navItems.tsx`. Not claiming these need zero thought — the auth
panel's brand gradient (`--auth-brand-bg`, `--mesh-glow-1/2`) is intentionally blue/branded and would
read as a decision, not an oversight, if the "no blue except the logo" rule were read to include it.
Flagging so nobody applies the new palette there by accident. **Confirm this is genuinely out of
scope before slice 1 — see §4.**

### Components — `components/**`

Every file was catalogued; the short version: **nothing here is being thrown away.**

- **`components/ui/*`** (Button, Card, Input, Table, Modal, Tabs, Progress, Skeleton, Badge,
  RowActionsMenu, Toast) — all 11 primitives are pure CSS-class consumers, **zero hardcoded colors
  or underline styles inside any `.tsx` file**. This is the best possible starting position for a
  palette swap: repainting the design system is a tokens.css job, not an 11-file refactor. Reused
  as-is structurally; only the CSS underneath changes.
- **`components/chat/*`** (SessionList, MessageThread, ContextPanel, ToolCallBlock) — all reused,
  move into the Chat tab as a unit. `SessionList` already cleanly separates "AXIOM Direct" vs.
  "Channels" into two sections sharing one selection model — exactly the seam a project-scoping
  filter would hook into. `ToolCallBlock` already carries the scope-denial "Grant access" UI and a
  separate source-locked notice — see §5, this survives untouched.
- **`components/dashboard/*`** (KpiCard, HealthBanner, TrendCharts, RecentRunsCard, ApprovalsCard,
  AxiomActivityCard) — all reused by Home. `TrendCharts.tsx` is the one place in the entire
  component tree with hardcoded hex values, but only as Chart.js fallback literals for when a CSS
  `var()` lookup returns empty (canvas can't consume `var()` directly) — the real token wins
  whenever it's loaded. Worth a pass to update the fallback hexes alongside any token repaint, but
  it's not a design-system violation.
- **`components/shell/*`** — `Sidebar.tsx`, `navItems.tsx`, `Topbar.tsx`, `CommandPalette.tsx` are
  the components that **rebuild**, not reuse — they *are* the current IA, hardcoded (domain-based
  sidebar sections, `AXIOM_DOMAIN_PREFIXES` prefix matching, etc.). Expect a full rewrite here, not
  a restyle. `ThemeToggle.tsx` survives as-is. `StubPage.tsx` survives as-is (still useful for
  whatever stays deferred). **`NotificationsPanel.tsx` has zero references anywhere in `app/` today
  — dead code with hardcoded placeholder data, not wired to any backend.** Flagging since "nothing
  gets thrown away" should probably not extend to reviving an already-abandoned placeholder; your
  call whether it's a real component to build into or dead weight to finally drop.
- **`components/tasks/TaskCreateModal.tsx`** — reused as-is; already channel/project-aware (narrows
  the agent picker to a channel's own members when opened from inside one).
- **`components/shared/EmployeeCard.tsx`** — reused as-is, see §5.
- **`components/brand/*`, `components/auth/*`** — untouched, outside this rebuild's scope (see above).

---

## 2. The 7 operational surfaces as Workbench routes

You expected page bodies to be almost untouched. **Correct for the UI; there's one real open
question underneath it that isn't a UI question at all.**

**What definitely changes, and it's cheap:**
- **URL** — `/sources` → something like `/projects/[id]/workbench/sources`.
- **Layout wrapper** — today each page renders under the single app-wide `Sidebar`+`Topbar` shell
  (`app/(app)/layout.tsx`). Inside a project, they'd render under the project container's own
  Workbench sub-nav instead — a new, narrower layout, but the page body (`page-header` +
  `Card > Table` + `Modal`, the pattern every one of these 9 pages already follows) mounts inside it
  unchanged.
- **Nav source** — today's `navItems.tsx` (`AXIOM_DOMAIN_PREFIXES`, domain-based sidebar swap)
  disappears; a project-scoped Workbench sub-nav array replaces it. This is new code, but it's
  routing/config, not page logic.

**Decision (2026-09-13): Option B, project-bounded.** A Workbench that shows every pipeline in the
tenant makes a project a chat folder, not a real boundary. Table-by-table check of whether "a
project's data = the union of sources reachable by that project's agents" resolves through existing
columns, or genuinely needs `project_id` added somewhere:

| Surface | Join path to a project's sources | Clean today? |
|---|---|---|
| **Sources** | `project_agents → agents → agent_sources` (the root set itself). | **Yes** — this is the definition, not a join. |
| **Catalog** | `CatalogEntry.source_id` — direct, one hop. | **Yes.** |
| **Pipelines** | `Pipeline.source_id` — direct, one hop. | **Mostly.** `source_id` is nullable, and the create form genuinely offers "No source (manual)" — a manual pipeline has no source and therefore no project. Real, reachable edge case, not just a defensive DB default. |
| **Quality rules** | `QualityRule.pipeline_id → Pipeline.source_id` — two hops. | **Yes in practice** — the create form makes `pipeline_id` `required`, so no orphan quality rules get created even though the column itself is nullable. Inherits Pipelines' own manual-pipeline gap one hop further out. |
| **Incidents** | `Incident.pipeline_id → Pipeline.source_id` — two hops. | **No — a real gap.** The create form labels this **"Pipeline (optional)"** and the mutation passes `pipeline_id: pipelineId \|\| undefined`. Incidents with no pipeline at all are a normal, reachable state today, not an edge case. |
| **Transforms** (History tab) | `TransformRun.source_id` — direct, one hop, nullable. | **Mostly** — same shape as Pipelines' manual case; a transform run not tied to a source is possible. |
| **CI/CD — Deployments/commits** | `PipelineCommit.pipeline_id → Pipeline.source_id` — two hops. | **Mostly** — `pipeline_id` is nullable on `PipelineCommit` (a webhook-driven commit can arrive before the pipeline mapping is known). |
| **CI/CD — Incidents** | `CICDIncident.pipeline_id → Pipeline.source_id` — two hops. | **Yes** — `pipeline_id` is `nullable=False` here, always resolvable. |
| **Governance — Contracts** | `DataContract.producer_source_id` — direct, one hop. | **Yes in practice** — the create form requires a producer source before enabling Create. |
| **Governance — Lineage** | No `source_id`/`pipeline_id` **column** exists on `LineageNode` at all. | **Convention, not schema.** Every auto-registered source/pipeline/output node does carry `{"source_id": ...}` / `{"pipeline_id": ...}` inside its free-form `node_metadata` JSON (verified in `lineage_tracker.py`), so today's real data is *usually* resolvable — but only via an unindexed JSON scan, and the open `POST /governance/lineage/nodes` endpoint accepts arbitrary metadata with no schema enforcing that key exists at all. This is the one surface where I'd recommend promoting `source_id`/`pipeline_id` to real columns if Lineage needs to be reliably project-bounded, rather than leaning on a convention nothing enforces. |
| **Governance — Audit Log tab** | None — `AuditLog.resource_type`/`resource_id` are deliberately unconstrained free-text (the model's own comment: audit logging must never fail on a referential-integrity conflict), and most audit events (invites, settings changes, contract validations) aren't source-scoped at all. | **No, and it shouldn't be forced to be.** This reinforces §1's recommendation: Audit Log is a tenant-wide concept, not a project-scoped one — keep it out of any per-project Workbench filter regardless of where it ends up living. |

**Bottom line: mostly clean, no schema change required for Sources/Catalog/Contracts, and
Quality/CI-CD-Incidents resolve cleanly in practice even though their FKs are technically nullable.**
Two real, live exceptions to design around rather than assume away: **unscoped Incidents** (a normal,
reachable state via the "optional" pipeline field) and **manual/sourceless Pipelines and Transform
runs**. Recommend a per-Workbench-surface **"Unscoped" bucket** — shown once, tenant-wide, reachable
from Home or a dedicated view, not duplicated into every project — rather than either hiding orphaned
rows entirely or guessing which project they belong to. **Lineage is the one surface that genuinely
benefits from a small migration** (real `source_id`/`pipeline_id` columns on `LineageNode`) if you
want it held to the same bar as the rest of Workbench rather than resolved by convention.

One more thing this join implies, not a defect: a **source can be reachable by agents in more than
one project** (nothing stops two projects' agents from both being granted the same source). Under
Option B that source's pipelines/quality rules/etc. would legitimately appear in both projects'
Workbenches — shared visibility, not a bug, but worth confirming that's the behavior you want rather
than discovering it live.

**What a project with zero agents shows:** empty Workbench, not an empty *tenant*. With no agents,
`agent_sources` resolves to the empty set, so every Workbench surface is legitimately empty — this
is exactly the state `projects/[id]/page.tsx` already handles for its agent grid today ("No agents
yet — agents are assigned to a project when you hire them," with a "+ Hire Agent" CTA). Recommend
reusing that identical empty-state pattern for an empty Workbench rather than inventing new copy —
it's the same underlying cause (no agents → nothing scoped to show) wearing a different surface.

---

## 3. Genuinely new, no existing code

Your count of 5 (home screen, project container + tab shell, Workbench sub-nav, 3-tab project side
panel, Needs you) — confirmed, with one correction and two additions.

**Correction:** "3-tab project side panel" almost certainly maps to **`ContextPanel.tsx`**, the
right-hand rail in today's chat page. It already has exactly 3 stacked sections — Active Tasks In
This Conversation, Attached Context, Tool Calls This Session — just not rendered as tabs. Turning
that into a real 3-tab panel is new *presentation*, not new data plumbing; every data source it
needs already exists and is already fetched there today.

**Three additions you didn't list:**

1. **The persistent global icon rail itself.** Today's `Sidebar` is a wide, multi-section,
   many-item nav with a domain-crossfade animation between "workspace" and "AXIOM" modes. The new
   6-item icon rail (Home, Scheduled, Needs you, Projects, Settings, Team) is a different shape of
   component, not a restyle of the current one — it's new chrome, separate from (and outside) the
   project container's own tab shell.
2. **"Scheduled" needs real aggregation logic, not just a screen.** Two backend sources feed it and
   neither has a unified list surface today: pipeline-level `schedule_cron` (visible today only as
   a column inside the Pipelines table) and a per-agent `ScheduledAgentTask` model (confirmed real
   and already wired to Celery beat — see §5 — but with **no frontend surface at all today**, and
   not confirmed to even have a GET-list REST endpoint; that's worth checking before estimating this
   slice). Building "Scheduled" means deciding whether it shows one merged feed or two sections, and
   confirming the missing list endpoint isn't itself the blocker. Confirmed 2026-09-14 (preview
   read-through, §8): also needs to handle a schedule auto-disabling when its source is deleted, with
   an inline explanation and a re-point path — not covered by the original backend confirmation pass.
3. **Source Detail.** Confirmed 2026-09-14 from `wunomo-all-screens.html` (§8): a drill-down from
   Workbench → Sources into a per-source page with its own 5-tab sub-nav (Schema, Quality, Pipelines,
   Incidents, Lineage). Nothing like this exists today — `sources` is a flat list with row actions,
   no detail route at all. Confirmed genuinely new and intended, not a preview embellishment.

---

## 4. Design system cost

**Status: shipped 2026-09-14 (slice 2).** Both themes now use the neutral treatment described below
— blue reserved for exactly the wordmark and the focus ring, in both, not just dark. `--chart-accent`
keeps its exemption (decorative, functional, not brand — annotated as a decision in `tokens.css`, not
left to read as a miss); the `--accent-fill-a35/-a50` etc. overlay tokens stayed deferred to slice 3
as recommended. One pre-existing bug found and fixed along the way, not introduced by this slice:
`.badge-midnight` had no dark-mode override at all (`WALKTHROUGH_FINDINGS_2026-08.md` item 88).
Analysis below is left as written — it's what was executed, not superseded by shipping it.

**Headline finding: dark mode already mostly *is* the target palette.** Look at `tokens.css`'s own
"Decision 1" (2026-08-19, still in force): *"buttons, active nav state, links, hover states — all
grey [in dark mode]; blue is reserved for exactly the wordmark/monogram and the focus ring."* That
is, almost word for word, "no blue except the logo." `--accent-fill`, `--accent-text`, and the
sidebar's active-state tokens are already re-pointed to neutral greys in dark mode; only
`--focus-ring` stays blue there, as a named, deliberate exception the team already made once. If
"dark neutral theme" means dark mode is the primary/default surface, most of the token work described
below is already done — the open question is really about **light mode**, which is still the full
"Futurewave blue" direction (blue primary buttons, blue links, blue focus ring, blue-tinted subtle
backgrounds, blue sidebar-active state) throughout.

**How many tokens actually change, if light mode goes neutral too:** fewer than the token-name count
suggests, because most of them cascade from just two root values. Concretely: `--accent-fill`,
`--accent-fill-hover`, `--accent-text`, `--accent-text-hover`, `--accent-subtle-bg`,
`--accent-subtle-border`, `--badge-accent-bg`, `--badge-accent-text`, `--sidebar-active-bg`,
`--sidebar-active-border`, `--sidebar-active-text`, `--accent-border`, `--brand-blue` — roughly 13
named tokens, but `--sidebar-active-*`, `--accent-border`, and `--brand-blue` already just *reference*
`--accent-fill`/`--focus-ring` rather than holding independent hex values, so redefining 2–3 root
tokens (mirroring exactly what dark mode already does) cascades through most of the list for free.
The mechanical pattern already exists in the file; light mode just needs the same move.

**The one open call this doesn't answer for you:** does `--focus-ring` also go neutral, or does it
keep the existing "blue is the one legitimate exception, same as the wordmark" precedent from dark
mode? A visible focus ring is a real accessibility signal, not decoration, and the team already chose
to exempt it once under an almost-identical rule. Recommend the same exemption here, but it's your
call to make explicitly rather than have it fall out of an oversight either way.

**What's explicitly NOT in scope for this token change:** `--mesh-glow-1/2`, `--mesh-white`,
`--mesh-lavender`, `--mesh-ramp-1..4`, and `--auth-brand-bg` are all documented in `tokens.css` as
theme-invariant, landing-page/auth-panel-only brand chrome — and the landing page + marketing site
are explicitly out of scope per your item 5. Don't let a global find-and-replace on "blue" catch
these; they're a different surface with a different rule.

**A bigger, more scattered finding: the underline.** `.auth-link-btn` (and its chat-specific sibling
`.chat-approval-notice .link-btn`) is blue, always-underlined (`text-decoration: underline`,
unconditional — not a hover state), and used as the primary "click this to navigate/act" affordance
across **14 files, 28 call sites** — table-row primary links ("Rename," "Connect one," project/agent
names in list tables), every "← Back to X" breadcrumb, and the auth flows. This is the most direct,
most pervasive violation of both "no blue except the logo" and "no underlined-link actions" in the
codebase, but it's mechanically cheap to fix at the CSS layer: it's exactly 2 rule definitions, and
every one of the 28 call sites is a bare `className="auth-link-btn"` reference with no other styling
riding on it — repainting the 2 rules (drop the underline, repoint the color) fixes all 28 for free.
**The more expensive, more faithful option** is what "real buttons everywhere" actually implies:
replacing each of those 28 sites with a real `<Button variant="ghost">` (or a new small text-button
tier) instead of a styled-to-look-like-a-button `<button className="auth-link-btn">`. That's a
per-call-site change, not a CSS-only one — genuinely worth deciding which of the two you want before
slice 1, since it changes the size estimate meaningfully.

**Button system itself needs little work.** The 3-tier button system (`.btn-primary/-danger/-success`
solid-52px, `.btn-secondary/-ghost` transparent-then-bordered-on-hover, `.btn-icon` 44×44 floor) is
already neutral except `.btn-primary`'s light-mode fill (`--accent-fill`) — the same root token the
palette section above already covers. No structural button work needed, only the color cascade.

**WCAG AA risk: low, if you copy the existing pattern rather than inventing new greys.** `tokens.css`
carries an unusually thorough, already-verified AA contrast history for both themes (every semantic
status color has a documented light/dark contrast ratio against `--surface`/`--bg`, with prior
failures and their fixes left in the comments as a paper trail). None of the status colors
(success/warning/danger/info) are touched by a blue-to-neutral swap. The safest path for the accent
tokens is to reuse the exact pairing dark mode already uses (`--accent-fill: var(--text-primary)` /
`--on-accent-fill: var(--bg)`, already verified at 17.7:1) rather than picking new hex values for
light mode — that keeps this a copy of an already-proven pattern, not a fresh contrast audit.

---

## 5. Must-survive checklist

| Item | Status | Where it lives after the rebuild |
|---|---|---|
| 5 Coming Soon employees (`lib/employees.ts`) | **Confirmed, fully decoupled from nav.** `EmployeeCard`'s lock overlay and `agents/hire`'s hardcoded `employee_type: "dataops"` are independent of any routing decision — they survive regardless of where the browsing page ends up (see §1's "no home" note on `/ai-employees` — that's a *navigation* question, not a risk to the lock itself). | Hire flow inside the Agents tab; browsing-page fate is a decision, not a risk. |
| Approval gate + risk tiers | **Confirmed built end-to-end.** `personality.py`'s `RISK_ACTIONS`/`get_risk_level()` for agent actions, `cicd_tasks.py`'s `calculate_risk_score()` for deployments, unified by `list_merged_approvals()` with a bucketed `risk_level`. | Backs "Needs you" wholesale, no backend change required. |
| Scope enforcement + denial messages | **Confirmed built, three independent layers.** `services/agent_scope.py` (`agent_scope_denial_reason`, `missing_sources_for_tool_call`), `task_planner.py`'s plan-time `validate_step_plan_scope()`, `agent_node`'s post-resolution `agent_scope_denied_tool_calls()`, and `task_executor.py`'s per-step `_caller_still_authorized()` — all four consult the same resolution table. Frontend messaging (`ToolCallBlock`'s "Grant access" button, task detail's scope-denial card) is real and role-gated (owner/admin only). | Untouched — none of this logic references navigation or IA. |
| Source locking | **Confirmed built — the proposal doc is stale on this point.** `services/source_lock.py` is a real Redis advisory lock (`SET NX EX`, 300s ceiling), wired into ingestion, profiling, and both transform runners; raises `SourceLockHeld`, which `task_executor.py` turns into `PAUSED_SOURCE_LOCKED` for retry rather than a live queue. | Untouched by the rebuild. |
| Per-agent budgets | **Confirmed built.** `AgentInstance.monthly_token_budget`, `enforce_agent_budget()` (402 on chat send), `GET /agents/{id}/quota`, and the agent detail page's `Progress` bar all connect end to end. | Lives in the Agents tab's agent detail page, reused as-is. |
| Schedules | **Confirmed built server-side, no frontend surface.** Pipeline `schedule_cron` is visible today (Pipelines table). `ScheduledAgentTask` (Phase 4 slice 14) is real — modeled, polled every 60s via Celery beat, fired by `fire_scheduled_agent_task()` — but has zero frontend today. | New home is the "Scheduled" global screen (§3) — confirm a list endpoint exists before sizing that slice. |
| Offboarding | **Confirmed built, matches the frontend's expectations exactly.** 409 + `task_id` block on any non-terminal task (including `paused_needs_approval`), channel membership cleanup, `ScheduledAgentTask` deactivation, history/scope explicitly preserved. | Untouched — Agents tab's agent detail page. |
| Task cost attribution | **Confirmed built.** `get_task_cost()` aggregates `LlmUsageEvent` rows into `task.cost` (credits/calls/tokens), already rendered as a real Cost card on the task detail page. | Untouched — Tasks tab's task detail page. |
| Public landing page + marketing site | **Confirmed out of scope.** Separate route tree, separate git branch, explicitly excluded by your item 5. | Untouched. |

---

## 6. Slice list — approved decisions folded in

Ordered, each independently shippable and verifiable. Sizes are rough (S/M/L) relative to each
other, not calendar estimates. Changes since the first pass: Workbench ships **Option B**
(project-bounded) from the start, not as a later follow-on; the `.auth-link-btn`/`.link-btn` cleanup
is its own slice and is a **real `<Button>` replacement at all 28 call sites**, not a CSS recolor, so
it reviews as one self-contained diff instead of riding along inside feature slices.

1. ✅ **SHIPPED 2026-09-14.** `.auth-link-btn` / `.link-btn` → real `<Button>` components. New
   `variant="text"` (`.btn-text` — no 44px floor, `display: inline` for mid-sentence use). 16 clean
   swaps, 7 real `<Link>`/`<a>` cases kept as anchors with `.btn-text` classes applied directly
   (preserving right-click/middle-click/copy-link), 1 sentence-embedded plain button converted the
   same way, 1 genuine redundant-row case resolved by dropping the inner button. Verified live, both
   themes. Finding 87 logged (no row in the product supports middle-click, pre-existing, not
   introduced here).
2. ✅ **SHIPPED 2026-09-14.** Design tokens — full neutral pass, both themes (see §4 for the complete
   before/after, cascade audit, and contrast table). `--chart-accent` exemption re-confirmed and
   annotated as a decision; `--accent-fill-a35/-a50` etc. overlays deferred to slice 3 as planned;
   `.badge-midnight`'s pre-existing missing dark-mode override fixed and logged as finding 88.
3. ✅ **SHIPPED 2026-09-14.** Global shell rebuild — sidebar rebuilt to match
   `wunomo-all-screens.html` exactly (real WunomoMark, serif wordmark, no "AI" suffix; collapse-to-
   icons retired, findings item 90; icons redrawn to the preview's 7 glyphs; workspace switcher
   folded into a new account-row menu alongside Log out, which moved out of Topbar). Interim
   navigation resolved by pointing every rail item at what's real (Home→`/dashboard`, Needs
   you→`/approvals`, Projects→existing pages, Scheduled→`StubPage`, the one genuinely new route);
   every route the old sidebar carried stays reachable via the command palette
   (`ALL_NAV_ITEMS`, now a superset). Nested project chats use real `getProjectChannels` data,
   deep-linking through the existing `/chat?session=` mechanism. `--accent-fill-a50`/`.badge-live`
   and the dead `--accent-fill-a35` removed (only one of the four deferred overlays was ever
   actually a sidebar token); `--accent-border-a15` repointed to `--focus-ring`;
   `--chart-accent-fill-a12` confirmed exempt, same reasoning as `--chart-accent`. Findings 89
   (slice 2's colour audit missed `rgba()` literals) and 91 (`WorkspacePicker`'s disabled "current"
   row is unreadable in dark mode, pre-existing, newly exercised) logged during this slice.
4. ✅ **SHIPPED 2026-09-14 — scope corrected from the original description.** The original plan
   ("restyle current Dashboard content under the new shell") turned out wrong once checked against
   `wunomo-all-screens.html`'s actual Home panel, which has none of the KPI/chart/approvals/activity
   content at all — just welcome copy, a start-a-project card, and a Recent project grid. Resolution:
   Home is a real, separate, brand-new screen at a real, new route (`/home`); `/dashboard`'s KPI
   content survives completely untouched at its existing URL (no longer the landing page, reachable
   via the command palette and a new "Workspace health" link on Home — the mock's silence on this
   was confirmed as an omission, not a decision). Every post-auth redirect that assumed `/dashboard`
   was the landing page (login, signup, invite-accept, Google OAuth callback, onboarding's own
   completion check, the sidebar's post-workspace-switch reload, Topbar's wordmark-breadcrumb link,
   and the public landing page's logged-in-visitor CTA) was found by grep and repointed to `/home` —
   checked explicitly so Home wouldn't ship as a screen nobody's routing ever reached. Added
   `Project.description` (nullable, migration `a3f7c982e410`) — small backend change, approved
   explicitly rather than deferred, since retrofitting it later would mean a migration *and* a
   backfill. The Recent grid's footer stats have three different real costs, not one: agent count is
   cheap and real; source count needs an N-of-N nested fetch (accepted for now); last activity has no
   data source at all today, so Home shows "Created {date}" instead of fabricating one — the
   `GET /api/v1/projects/summary` endpoint that would fix all three at once is logged as findings
   item 92, not silently absorbed. **Size: M** (bigger than the original S estimate — the scope
   question and the redirect audit were the real work, not the screen itself).
5. ✅ **SHIPPED 2026-09-14.** Projects list + project container shell. `/projects`: whole rows
   clickable (same `<Tr onClick>` pattern as Tasks, inheriting finding 87's already-logged
   middle-click limitation), description shown, and findings item 83 (the ⋮ menu opening below the
   fold) fixed at the shared `RowActionsMenu` component level — benefits every list page that uses
   it, not just Projects. Project container: real 4-tab shell (`/projects/[id]/{chat,workbench,
   tasks,agents}`) with a shared layout (header + tabs); bare `/projects/[id]` redirects to **Chat**,
   not Agents — an explicit correction to this doc's own original proposal, decided because the
   default tab is a product statement ("chat is where work gets asked for"), not just whichever tab
   has real content this slice. Agents tab is the old `/projects/[id]` page moved verbatim. Tasks tab
   is real, not a stub — pulled forward from slice 8, filtered by `agent_id ∈ project's agents`
   client-side (which required a small, genuine backend fix: `GET /api/v1/tasks/` never surfaced
   `agent_id` at all despite the column existing since Phase 0 — findings item 93). Chat tab is an
   honest signpost stub (explains what's coming, links to the real `/chat` in the meantime, not a
   dead end); Workbench is a plain `StubPage`. Hire-agent extracted from the old standalone
   `/agents/hire` page into a shared `HireAgentModal` (project pre-filled from the container header,
   empty from the global `/agents` list) — the standalone page is retired. Six real deep-link sites
   to bare `/projects/[id]` found and repointed to the chat tab (sidebar, Home, the list's own row
   click and post-create redirect; the old hire page's two links disappeared with the page itself).
   **Size: L** (matches the original M–L estimate, landed at the high end — the hire-modal extraction
   and the tasks-tab pull-forward were both real, not wrapper-only work).
6. **Workbench sub-nav, project-bounded (Option B) — split into 6a and 6b (2026-09-14):
   verify the resolver after three surfaces, not seven.**
   - **6a ✅ SHIPPED 2026-09-14.** The Workbench sub-nav shell (all 7 items, matching the preview's
     WBNAV exactly) + the shared resolver (`lib/projectScope.ts`: `project_agents → agents →
     agent_sources`, with pipelines derived from resolved sources) + the three clean surfaces
     (Sources, Quality, CI/CD — no unscoped population per §2's join table). Their old top-level
     routes retired via a real redirect + explanation (`RetiredRouteRedirect`), not a bare 404;
     Pipelines/Incidents/Transforms/Lineage ship as honest `StubPage`s, untouched otherwise. Two
     distinct empty states built (Q3): zero agents (layout-level, replaces the whole sub-nav) vs.
     agents-with-no-sources-granted (per-surface, shared component). Governance's Lineage tab
     replaced with a visible "moved" notice, not silently dropped, plus a second command-palette
     entry so searching "lineage" finds where it went. Home's `ProjectCardStats` refactored onto
     the same shared resolver instead of its own copy. Bonus fix while in the area: `.tab.active`
     was hardcoding a theme-invariant blue primitive slice 2's audit never caught (findings item 95)
     — the project container's own tab bar had been rendering a blue underline since slice 5 shipped.
     **Verified hardest exactly where asked**: two different projects, two different agents, one
     source granted to both — confirmed live it shows in *both* projects' Sources (the union, not
     exclusive), and that a quality rule built on that shared source's pipeline resolves into both
     projects too, not just the literal source-level case.
   - **6b ✅ SHIPPED 2026-09-14.** Pipelines, Incidents, Transforms, Lineage built as filtered copies
     of their old top-level pages, same pattern as 6a's Sources/Quality/CI-CD, plus the two-tier
     Unscoped treatment: an always-visible muted note on each project Workbench sub-page
     (`UnscopedNote`, new shared component) backed by a real `unscoped=true` query param added to
     all three list endpoints (`GET /pipelines`, `/incidents`, `/transformations/runs` — a single
     indexed `COUNT(*)`/list filter each, not N+1; Transforms' endpoint also got finding 55's
     real-COUNT fix, which it had never received). Pipelines/Incidents/Transforms's old top-level
     routes repurposed rather than retired (real unscoped population, unlike 6a's three) — same URL,
     narrowed to unscoped-only, with a new `ScopeBanner` component explaining the change on the page
     itself (same "don't leave a silent gap" rule as Governance/Lineage), plus `ALL_NAV_ITEMS` labels
     updated to match. Lineage built fresh: derives from `LineageTracker.sync_tenant_lineage()`
     (source/pipeline registration metadata, not real query-level tracing), with an Approximate badge
     driven by each node's real `metadata.auto` flag rather than assumed, and an Unresolved badge for
     a pipeline with no lineage edges. Verified both badges render on real, non-fabricated data — but
     doing so surfaced a structural fact: `useProjectScope`'s `pipelineIds` only ever contains
     pipelines that already have a source, so a *project's own* pipeline list can never actually
     produce "Unresolved" (always resolves, always Approximate) — Lineage needed the same two-tier
     Unscoped treatment as the other three surfaces for "Unresolved" to have anywhere real to appear
     (an unscoped/manual pipeline is exactly `sync_tenant_lineage`'s bare-node case). Separately,
     while building the repurposed `/transforms` route, `TransformRun.source_id` turned out to be
     nullable in the schema but never actually nullable in practice — every insert path (UI and
     agent) requires a real `source_id` — so unlike Pipelines/Incidents, Transforms' unscoped bucket
     is correct-but-currently-empty, not a bug in this slice; logged as findings item 97 rather than
     silently building UI for a case the original audit assumed without checking. Catalog/Contracts/
     Audit's placement question (findings item 94) remains open, unrelated to this slice's scope.
     **Verified**: two-project negative control (an unscoped pipeline shows in the muted note but
     never in either project's own list — checked with two separate projects, not one); a
     project-scoped pipeline confirmed absent from the repurposed `/pipelines` view; both Lineage
     badges confirmed on real data, in both themes.
   - **Correction, 2026-09-15 (findings item 97).** Transforms' repurposed unscoped view was retired
     rather than kept — no code path can produce a sourceless `TransformRun` (both API request models
     and both agent tools require a real `source_id`), so the tenant-wide view could only ever show
     empty. `/transforms` now retires outright via `RetiredRouteRedirect`, same as Sources/Quality/
     CI-CD; Pipelines/Incidents keep the real two-tier treatment, both have a genuine reachable
     unscoped case.
7. ✅ **SHIPPED 2026-09-15.** Chat tab — replaces the slice-5 signpost stub with the real thing.
   `MessageThread` reused completely unchanged (composer, @mention autocomplete, drag-and-drop file
   upload, task creation, approvals routing — all pre-existing, none of it new). `SessionList` gained
   one prop (`showDirect`) rather than being forked, hiding "+ New Chat"/AXIOM Direct for the project
   route; channels filtered client-side by `project_id` (free, per the original plan). AXIOM Direct
   stays exclusively at `/chat` — `ChatSession`/`ChatMessage` carry a bare `session_id` with no
   `project_id` anywhere in the schema, confirmed by reading the model, not assumed.
   `ProjectContextPanel` is a new, separate component (not `ContextPanel` made configurable — `/chat`'s
   own AXIOM Direct sessions and non-project channels have no project to show a roster for), tabbed
   Agents / Data / Activity to match `wunomo-redesign-v2.html`'s side panel by tab count. Mapping,
   confirmed before building: **Agents** — new roster (name, employee type, real per-agent source
   count via `useProjectScope`'s already-fetched per-agent queries, zero new network calls;
   deliberately no status dot — `AgentInstanceStatus` is only ACTIVE/OFFBOARDED, a lifecycle flag, not
   a live signal, so a permanently-"idle" dot would be fabricated, same "Created {date}" rule as
   findings item 92). **Data** — project's sources (new list, links out to Workbench, doesn't
   reproduce it) plus the pre-existing Attached Context picker; the preview's own footer note claiming
   Pipelines/Quality/etc. are "reached from the Data panel" predates Workbench as a real tab and was
   deliberately not carried over. **Activity** — Active Tasks and Tool Calls as two labeled
   subsections, not an interleaved merge — different lifetimes (durable cross-session Task vs.
   this-session-only tool log), and merging them would lose that distinction for no real gain.
   Real bug found and fixed during the build: `.chat-layout`'s CSS hardcoded
   `height: calc(100vh - var(--topbar-h))`, correct only when nothing sits above it (true for `/chat`,
   false for the project route, which has the project header + tab row above it) — it overflowed
   `.page-content` and auto-scrolled the header out of view. Fixed to `height: 100%`, which resolves
   correctly against both hosts' actual flexed container height; verified both routes render
   pixel-correct afterward, not just the new one. **Verified**: a channel in Project A is invisible
   from Project B's Chat tab and Project B's from A's, both still visible tenant-wide at `/chat`
   (same union/boundary shape as the Workbench resolver); @mention autocomplete inside a channel
   offers only that channel's real agent *members*, confirmed distinct from the project's full agent
   list and the tenant's; file upload resolves to the channel's real single agent, not a guess; a
   real end-to-end message send round-trips through the actual LLM successfully, in both themes.
8. **Tasks tab.** Filter the Tasks list by `agent_id ∈ project's agents`, client-side join against
   already-fetched agent data. Task list/detail bodies unchanged. **Size: S.**
9. ✅ **SHIPPED 2026-09-15.** Needs You — replaces `/approvals`' old flat, uniform-row list with the
   real combined screen the rail's label always implied. New shared derivation (`lib/needsYou.ts`)
   used by both the Sidebar's "Needs you" badge and this page, so the two can never disagree about
   the count again — before this slice the badge counted `getMergedApprovals().count` only, silently
   blind to every task needing attention (a `DRAFT_PLAN`, a dead `PAUSED_FAILED_STEP`), while the
   Topbar's separate task-rail dropdown counted task `needs_attention` only, blind to approvals. Four
   urgency tiers, not the task rail's original three: 0 = `PAUSED_NEEDS_APPROVAL` (real clock,
   `APPROVAL_PAUSE_TIMEOUT_HOURS` = 48h, soonest-to-expire first), 1 = standalone approvals — a
   chat-originated `request_approval` with no task, or a CI/CD deployment gate — (no clock anywhere
   in the code, but a live blocking decision outranks an already-dead task since speed still helps
   here; oldest-first), 2 = `PAUSED_FAILED_STEP`/`PAUSED_PLAN_INVALID` (already dead, no resume path —
   finding 76 — most-recently-died first), 3 = `DRAFT_PLAN` (no decay, oldest-first).
   Real correctness bug found and fixed around, not silently reproduced: a task's own
   `PAUSED_NEEDS_APPROVAL` and a `policy_engine`-sourced `MergedApproval` can be the exact same
   `ApprovalRequest` row (`task_executor.py` and the agent's own ad-hoc `request_approval` chat tool
   both create one via the same `PolicyEngine.create_request()`), and resolving it through the
   generic `/approvals` endpoint runs the action but never touches the `Task` row — permanently
   stuck in `PAUSED_NEEDS_APPROVAL` even though the approval resolved, live on `/approvals` today,
   predating this slice (**logged as findings item 98**, not fixed at the state-machine level — that's
   its own slice, same reasoning as finding 76 staying open). `GET /tasks/active` now exposes each
   task's `current_step.approval_request_id` (a field already loaded, not a new query) so this page
   can dedupe: a task-linked approval renders exactly once, as a task row, resolved exclusively
   through `resumeTask()`/`rejectTaskStep()`, never the generic endpoint. Also added `project_id`/
   `project_name` (via an outerjoin already sitting next to the existing `AgentInstance` one) and
   reused the already-computed `_pause_reason()`/`_plan_invalid_reason()` helpers so blocked rows show
   the real specific failure, not just generic action text. The preview's literal `Grant access`
   button wasn't built — `_pause_reason()`'s scope-denial text is prose, not a structured
   `{agent_id, source_id}` a link could route from with confidence; shipped `Open task` instead and
   logged the structured-payload fix as its own follow-up (**findings item 99**). Empty state is this
   app's own standard `.empty-state` pattern (icon, heading, calm copy), not the preview's minimal
   list-cap line — deliberate, the preview's line was designed as an end-of-list cap, not a true zero
   state. **Verified**: seeded a task paused for approval with a real linked `ApprovalRequest`
   directly (mirroring the backend test suite's own `_set_status`-style seeding, since driving a full
   LLM-planned task through real execution wasn't necessary to test this) — confirmed it renders
   exactly once (not once as a task and once as an approval) and the Sidebar badge agrees with the
   page's own count; approved it from Needs You and confirmed via a direct API check that the task's
   status actually left `PAUSED_NEEDS_APPROVAL` (it resumed, ran for real, and correctly failed on
   the seed's synthetic pipeline id after exhausting retries — landing in `PAUSED_FAILED_STEP`,
   re-surfacing correctly as a "blocked" row with the real failure text) rather than the approval
   resolving while the task stayed silently stuck.
10. ✅ **SHIPPED 2026-09-15.** Scheduled — replaces the StubPage with the real, tenant-wide
    `ScheduledAgentTask` list. Scope corrected from the original description: pipeline `schedule_cron`
    deliberately **not** aggregated in — an unrelated mechanism with no `deactivation_reason` concept
    at all, already has a correct home in each project's Workbench Pipelines tab (schedule column,
    Pause/Activate, built in 6b); bolting it into this table would mean an "Agent" column empty for
    every pipeline row and a deactivation feature that only ever applies to half the list. The
    list-endpoint gap was real, confirmed by reading the code: `GET /{agent_id}/schedules` existed
    but only per-agent, no tenant-wide view. New `GET /api/v1/agents/schedules`, same bulk-fetch
    shape `GET /tasks/active` already established — one query for schedule+agent+project via
    outerjoins, one bulk query for every `Task` matching `originating_schedule_id`, reduced to
    "most recent per schedule" in Python, not a per-schedule round trip. `deactivation_reason` shown
    verbatim (already real, written prose from `validate_schedule_can_run`) — the preview's own
    "re-point it at a live source" copy was checked against the real code and found inaccurate:
    `tool_args` are immutable once a schedule exists, no edit endpoint exists, every real validation
    message says "delete this schedule and create a new one," not "edit" — shown as-is instead of
    reproducing the preview's wrong phrasing. "On" is a static badge, not a toggle — confirmed no
    manual pause endpoint exists, only automatic deactivation, so a switch would imply a control that
    isn't there. No create button: `ScheduledAgentTask`'s own docstring already called that UI "its
    own later slice" when the backend was built; confirmed why by reading `TASK_SHAPE_ALLOWED_TOOLS` —
    `tool_args`' real shape differs per tool across ~14 schedulable tools with no single schema to
    render a generic form from, real scope logged as findings item 100 rather than shipped as a
    guessed form. Empty state explains what a schedule is and states plainly it's created via the API
    today, with the real endpoint shown, rather than reading as an unfinished screen.
    **Verified**: seeded a real schedule via the actual creation endpoint, deleted its source via the
    real delete endpoint, then ran the actual `validate_schedule_can_run` to deactivate it (not a
    guessed message) — confirmed the real reason renders verbatim in the UI; clicked Reactivate with
    the cause still genuinely unfixed and confirmed it fails at the click with the same live
    validation error (not silently, not at the next firing), and the row's "off" state is unchanged
    afterward. Both themes.
11. **3-tab `ContextPanel`.** Formalize the existing 3 stacked sections into real tabs. Pure
    presentation change over already-fetched data. **Size: S.**
12. **Placement decisions cleanup.** Resolve and implement wherever you land on: `/ai-employees`
    fate, global agents list fate, Governance's Contracts/Audit split vs. the `audit` stub, Billing's
    home, Automations/Analytics stubs. Each is small once decided; listed here because each depends
    on a decision from §1, not on any other slice above. **Size: S each.**
13. **Docs.** Rewrite `SELF_TEST_GUIDE.md`'s nav-dependent instructions and recapture screenshots —
    see §7 for exactly what's stale. **Size: M** (mechanical, but long).

See §8 below for the full read-through and how the two previews were reconciled (2026-09-14).

---

## 7. What this invalidates in `SELF_TEST_GUIDE.md` and the screenshots

**Structure:** the guide is a click-by-click walkthrough (15 top-level sections) organized mostly by
current nav destination, with several sections that explicitly document *which sidebar grouping*
things live in — e.g. it calls out that Sources/Pipelines/Quality/Incidents/Transforms/Governance
currently live under "AXIOM's own nested sidebar domain," distinct from the regular Workspace
sidebar, and that Approvals deliberately does not. That distinction is exactly the thing this rebuild
replaces, so every sentence describing it goes stale.

**Sections that go stale (reference specific sidebar labels/groupings that won't exist):**
§2–3 (Sources/Pipelines/Quality/AXIOM chat/Tasks, written as sidebar click-paths), §4.4 (Team/Viewer
permission walkthrough references sidebar location), §6 (Dashboard → Home rename), §7 (Incidents),
§8 (Transforms), §9 (Settings — tab *content* survives, but its current framing as an ADMIN-grouped
sidebar item does not), §10 (Approvals → folds into Needs you), §11 (Governance — also needs
rewriting for wherever Lineage/Contracts/Audit Log land per §1), §12 (App Shell Sweep — sidebar
collapse icon, workspace-switcher position, command palette — all describe the current `Sidebar`
component directly), §15 (Wunomo Projects — Projects/Agents/Channels walkthrough needs updating for
the new project-container tab shell, though its *content* — hire, scope, offboard, budget exhaustion
— is exactly what §5 confirms survives untouched).

**Notably NOT covered by a dedicated section today:** CI/CD has no top-level heading in the guide at
all despite being a real, built, tabbed page — worth adding when the guide gets rewritten, not just
patching what's stale.

**Screenshots (`docs/self_test_assets/`, 10 files):** all ten depict the Tasks/AXIOM-chat flow
(start-a-task through approval-gate through terminal state) or the Dashboard — none depict
Sources/Pipelines/Quality/Incidents/Transforms/Governance/CI/CD/Team/Billing/Settings. Good news:
staleness risk is concentrated, not spread across all 10. Bad news: the concentrated set is exactly
the flow (chat, task creation, approval) that's moving into a project's Chat/Tasks tabs and a new
Needs-you screen — meaning most or all 10 will need recapturing once the container shell and Needs
You screen exist, not just cosmetic recropping.

**Sections that survive untouched:** §1 (Pre-flight — env/docker/login, not nav-dependent), §5 (LLM
budget bookkeeping), §13 (deliberately-excluded-topics list), §14 (Known Issues — though it should be
re-verified against the audit's findings above, e.g. this document's own note on the Incidents
duplicate-row bug).

---

## 8. Preview read-through (2026-09-13) — contradictions and new findings

Both previews landed in `docs/design/`: `wunomo-redesign-v2.html` (a single-flow interactive demo,
labeled "clickable, not a working build") and `wunomo-all-screens.html` (a picker across every
screen in the redesign). Read both in full. One contradiction is serious enough to resolve before
building the project shell; the rest are smaller and mostly resolve open questions from §1 rather
than raising new blockers. None of this changes slice 1 or 2 (buttons, tokens) — both previews use
neutral, real, unlined buttons throughout and a dark-neutral palette matching what those two slices
already target.

### Resolved 2026-09-14 — recorded so this doesn't get re-litigated

**`wunomo-all-screens.html` is authoritative for structure**: the 4-tab project shell (Chat /
Workbench / Tasks / Agents) and the 7-item Workbench sub-nav are the target. `wunomo-redesign-v2.html`
was the first pass, written before the operational surfaces' home was worked out — superseded on this
point, not a live alternative.

**`wunomo-redesign-v2.html` is authoritative for exactly one thing, which stays**: the Chat tab has
its own 3-tab side panel (Agents / Data / Activity). This is a glance surface, not a competing
structure to Workbench — **Data** lists a handful of sources and links out into Workbench for the
real screen; **Activity** shows live steps and links out into Task detail for the real screen. Both
the glance panel and the full Workbench/Task-detail screens exist, at different depths, permanently.

**Smaller answers, also recorded:**
- Projects keeps its existing `/projects` list screen — the rail-only presentation in both previews
  was a mockup shortcut, not a decision. §1's `projects` row stands as originally written (RESTYLE).
- Hire modal carries all 6 employee types from `lib/employees.ts`, 5 of them locked — the preview's
  4-card grid was for visual symmetry, not a roster trim. Nothing changes in §5's "must survive" row.
- Settings keeps all 6 tabs — the preview's missing Profile tab was an omission, not a cut.
- `agents/hire` as a modal: the REBUILD correction (page → modal) stands as noted in §8 above.
- Source Detail drill-down: confirmed genuinely new and intended — stays in §3.

### Background — why these two needed reconciling in the first place

`wunomo-all-screens.html`'s project header renders a real 4-item subnav — **Chat, Workbench, Tasks,
Agents** — and its Workbench has exactly the 7-item sub-nav this audit assumed (Sources, Pipelines,
Quality, Incidents, Transforms, Lineage, CI/CD), plus dedicated **Task detail** and **Agent detail**
screens matching what's already built today. This matches the original written spec and everything
in §1–§7 above almost exactly.

`wunomo-redesign-v2.html` — the interactive one, i.e. the one actually demonstrating how it feels to
use — shows something structurally different: **no subnav, no Workbench, no separate Tasks
destination at all.** The project screen is chat as the main pane with a lightweight **3-tab side
panel: Agents, Data, Activity**. "Data" replaces Workbench and Sources/Pipelines/Quality/Incidents/
Transforms/Governance/CI-CD are explicitly named in its own footnote as "no longer destinations —
they're views of a project's data, reached from the Data panel," rendered there as plain source cards
with profiling status, not as separate CRUD screens. "Tasks" doesn't exist as a tab or a screen —
task plans, steps, and approval gates appear inline as cards in the chat thread, and the Activity tab
is a live step-by-step event timeline, not the existing Task list/detail pages (cost card, rerun,
plan-edit).

These can't both be right. Slices 4–6 (project container shell, Workbench sub-nav) are sized and
scoped against the *all-screens* structure — if the *redesign-v2* structure is actually the intended
one, §1's reuse map changes materially: the existing Tasks list/detail pages stop being a "MOVE,
reused as-is" and become a "REBUILD" (their content redistributes into inline chat cards + an
Activity timeline), and Workbench's whole premise (7 sub-nav destinations, each a real page) goes
away in favor of one unified Data panel. **Need to know which one is the real target — or whether
`redesign-v2` is an earlier/simplified sketch superseded by `all-screens` — before slice 4 starts.**
Slices 1–2 don't depend on this either way.

### Smaller findings — status after 2026-09-14's resolution

- ~~"Projects" isn't a 4th clickable rail destination in either preview~~ — **resolved: keep the
  existing `/projects` list screen**, per the answers above. The rail-only presentation was a mockup
  shortcut.
- **Billing's home is resolved:** both previews merge Team and Billing into one screen/nav item,
  "Team & billing" — closes §1's open "Billing has no home" question definitively.
- **`agents/hire` is a modal in both previews, not a page** — **REBUILD correction accepted** (§1
  updated). Roster question resolved above: all 6 employee types, 5 locked; the preview's 4-card grid
  was symmetry, not a trim.
- ~~Settings preview shows 5 tabs, missing Profile~~ — **resolved: all 6 tabs stay**, Profile's
  absence was a mockup omission.
- **New screen, not previously catalogued: Source Detail — confirmed genuinely new and intended.**
  `wunomo-all-screens.html` shows a drill-down from Workbench → Sources into a per-source page with
  its own 5-tab sub-nav (Schema, Quality, Pipelines, Incidents, Lineage). Nothing like this exists in
  the current app (`sources` today is a flat list with row actions, no detail route). Added to §3.
- **Scheduled screen reveals a real behavior, not just layout — still open:** a schedule shown auto-disabled with
  an inline explanation ("its source was deleted on 9 Sept — re-point it to turn it back on"). Worth
  folding into slice 10's scope explicitly — "what happens to a schedule when its source disappears"
  wasn't covered by the backend confirmation pass.
- **"Needs you"'s scope-denial card reads "This task can't be resumed — grant the source, then start
  a new one."** Plausibly consistent with what was confirmed of the backend (`ADVANCEABLE_STATUSES`
  in `tasks/[id]/page.tsx` lists no scope-related paused state, only quota-exceeded and
  source-locked) — a scope denial may simply not be a resumable pause the way those two are. Not
  contradicted, but also not explicitly verified in the backend confirmation pass — worth a quick
  check before Needs You ships rather than assuming the copy is accurate.
- **Everything else lines up well:** Agent detail's Can-reach/Standing-instructions/This-month/
  Schedules/Offboard sections match every backend mechanism confirmed in §5 one-for-one. Task
  detail's Steps/Cost/Outcome layout matches the existing Cost card and step timeline almost exactly.
  Needs You merges risk-tiered approvals with blocked/attention tasks into one feed, exactly as §1
  recommended. The Workbench 7-item sub-nav (in `all-screens`) matches §2's join-table analysis
  item-for-item.

---

## Backend: what this rebuild genuinely needs from the backend team

Per your framing, this is almost entirely a frontend rebuild. Two real items, both small:

1. **`GET /api/v1/channels/` has no `project_id` query filter** — it always returns every channel in
   the tenant the user belongs to. The Chat tab can filter client-side (each `ChannelItem` already
   carries `project_id`), so this isn't a blocker, but a real filter param would be the cleaner fix
   if channel volume ever gets large enough for client-side filtering to matter.
2. **Confirm `ScheduledAgentTask` has a list endpoint.** The model, the beat polling, and the firing
   logic are all real and already shipped (Phase 4 slice 14) — but no GET-list route was confirmed to
   exist, and no frontend anywhere reads it today. If it's missing, it's the one genuinely new
   backend surface this rebuild needs, and it's small (a scoped list query, same shape as the
   existing agents/tasks list endpoints).

Everything else — the Workbench data-scoping question in §2 — is a product decision about whether to
build new scoping, not a gap that blocks shipping the rebuild as pure navigation/layout work.
