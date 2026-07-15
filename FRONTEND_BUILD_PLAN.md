# Wunomo AI — Frontend Build Plan

**Status: Phase 0 complete and approved. Phase 2 (frontend scaffold + design system)
complete** — Next.js 15 App Router scaffolded under `dataops-agent/frontend/`, locked
tokens ported to `src/styles/tokens.css` (light + dark, 3 dark-mode contrast bugs found
and fixed via actual screenshot verification, not just code review — see that file's
comments), real font files self-hosted under `public/fonts/` (no CDN calls), and the
10-component core library built (`src/components/ui/`). Visually verified in both
themes via Playwright screenshots against a live dev server and a clean production
build. This is the authoritative, signed-off plan
for building the Wunomo AI frontend against the real `dataops-agent` backend.
Referenced from `CLAUDE.md` — read that file first for the backend's current state,
then this file for what's being built on top of it and in what order.

Source material: `dataops-agent/frontend/wunomo-ai MASTER DESIGN.html` (the master
design prototype — all 18 post-login screens, component library, design tokens),
plus `dataops-agent/frontend/color scheme.png` and `wunomo_architecture.html` (the
latter is an aspirational long-term vision doc, not current-state — don't treat it as
a spec). Derived design tokens are in `dataops-agent/DESIGN_TOKENS.md`.

---

## Phase 0 decisions (locked)

**Typography:** General Sans (UI/body, Fontshare) + Fraunces (display/headings,
Google Fonts) + JetBrains Mono (code/SQL/hashes/timestamps, unchanged from the
prototype). Self-hosted from `frontend/public/fonts/`, no runtime CDN calls.

**Palette:** Midnight `#122C4F` / Pearl Perfect `#FBF9E4` / Noir `#000000` / Ocean
`#5B88B2`, with derived light/dark token scales — see `dataops-agent/DESIGN_TOKENS.md`
for exact hex values. Sidebar stays Midnight in both themes (constant "spine").
Semantic status colors (success/warning/danger/info) keep their original hues in
both themes; only bg/border tints change per theme.

**Tech stack:** Next.js 15 (App Router) + React 19, `(public)`/`(app)` route groups,
Zustand for state, plain `fetch` + `lib/api.ts` JWT client (React Query introduced at
the Dashboard phase), Chart.js + `react-chartjs-2`, ported `design-system.css`
(not a Tailwind rewrite), JWT in localStorage for v1 (httpOnly cookie hardening
documented as deferred), repo structure under `dataops-agent/frontend/`.

**Four pushback items, all approved:**
1. Google OAuth account linking requires Google's `email_verified: true` on the ID
   token — non-negotiable, prevents a spoofing edge case on auto-link-by-email.
2. `get_agent()`'s module-level `_cache` in `agent/dataops_agent.py` must be re-keyed
   to include tenant + model choice once per-tenant AI model selection ships (Phase
   16) — otherwise a tenant's model preference can leak into another tenant's cached
   agent object. **Already added to CLAUDE.md's Gotchas as of this commit**, not
   deferred to Phase 16, so no intermediate session touches `get_agent()` unaware.
3. `require_role()` shared dependency gets built and applied to at least CI/CD
   approve/reject as part of Phase 15. Full audit of other ungated sensitive
   mutations below, for prioritization when Phase 15 arrives.
4. Shared quota-check dependency from day one (Phase 15), to avoid the same
   "inconsistently applied" fate as role-checks currently have.

**Approvals screen:** merges two real but separate sources (`/approvals` general
PolicyEngine queue + `/cicd/commits?gate_decision=pending_approval`) via a small
**backend aggregation endpoint**, not a frontend-side merge — keeps tenant-scoped
query logic centralized and avoids badge-count drift between the sidebar and the
Approvals page.

**Coming Soon at launch (confirmed, nothing else):**
- Automations (real trigger→action rule engine is a dedicated post-launch project)
- The 5 locked AI Employees (LEDGER, DEPLOY, INSIGHT, SENTINEL, PULSE)
- Compliance tab (within Governance)

Everything else on every screen ships real, wired to a real backend endpoint.

---

## Role-check audit (feeds Phase 15 prioritization)

Grepped every `@router.post/put/patch/delete` across `api/v1/*.py` against every
`role` check in the same files. **Only `approvals.py`'s approve/reject checks role**
(`admin`/`owner`). Every other mutation endpoint below is gated by
`Depends(get_current_user)` only — any authenticated tenant member, regardless of
role, can perform them. Listed by suggested priority for Phase 15 to triage:

**High priority (destructive or high blast-radius):**
- `DELETE /pipelines/{id}`, `DELETE /sources/{id}`, `DELETE /quality/{rule_id}`
- `POST /cicd/commits/{id}/approve`, `/reject` (already flagged in CLAUDE.md's
  known-broken list — approves/rejects production deployments)
- `POST /transformations/run/sql`, `/run/pandas` (executes against real connected
  sources/sandboxed code, even though `sql_runner.py`/`python_runner.py` sandbox
  the execution itself)
- `PATCH /cicd/incidents/{id}/resolve`

**Medium priority (state-changing, reversible):**
- `POST /pipelines/{id}/trigger`, `/pause`, `/activate`, `/backfill`,
  `PUT /pipelines/{id}/schedule`, `PUT /pipelines/{id}`
- `PUT /sources/{id}`, `POST /sources/{id}/sync`, `/profile`, `/drift`
- `POST /incidents/`, `PUT /incidents/{id}`, `POST /incidents/{id}/resolve`
- `POST /governance/lineage/node`, `/lineage/edge`, `/contracts`,
  `/contracts/{id}/validate`
- `POST /quality/`, `POST /quality/{id}/run`
- `POST /cicd/deployments/{id}/record-run` (looks meant for system/webhook use,
  not user-facing — worth checking who's actually meant to call this)

**Lower priority (additive, low blast radius):**
- `POST /uploads/`, `/uploads/register`
- `POST /analytics/kpis`

Phase 15 decides which of these actually need role gates (vs. "any tenant member
can do this" being the intended behavior) — this list is for triage, not a mandate
that all of them change.

---

## The 19 phases

Frontend scaffold/design-system/shell/screens-wiring-to-already-verified-endpoints
are **never blocked** by Track 2 (billing/metering/team) — those proceed in parallel
while backend work lands. Every backend item follows CLAUDE.md rules without
exception: tenant isolation on every new table, explicit approval before any
schema change, regression tests alongside every feature, live verification before
commit, separate commits per verified unit, Status Table + Gotchas updated in the
same commit as the change.

| # | Phase | Frontend scope | Backend prerequisite / scope | Verification gate | Depends on |
|---|---|---|---|---|---|
| 1 | **Usage metering foundation** (Track 2) | None | Instrument the LLM call site in `llm_service.py` to log tokens in/out, provider, model, latency per request to a new `LlmUsageEvent` table (schema proposed separately for approval); add a `provider` field to the `/chat/` response | Real tool-calling and non-tool chat messages logged accurately; `provider` field present; full regression of tenant_id injection, message bounding, and timeout fallback (all fixed earlier this project) still passes | None — runs parallel to Phase 2 |
| 2 | **Frontend scaffold + design system** | Next.js init, locked palette/fonts ported to `tokens.css`, self-hosted font files + `@font-face`, core component library (Button, Card, Badge, Input, Table, Modal, Toast, Tabs, Progress, Skeleton) | None | Visual comparison against the prototype, both themes | None — runs parallel to Phase 1 |
| 3 | **Unified auth design** (proposal only) | None | Propose JWT claims shape, tenant-resolution rules across OAuth / invite-join / new-signup, the `email_verified` linking rule — sign-off, no code | N/A (design approval) | None |
| 4 | **Onboarding profile storage** | None | New columns/table for role, company, size, use case, data stack — schema proposed for approval first | Register a user, POST onboarding answers, confirm persisted; confirm register/login unaffected | Phase 3 |
| 5 | **Google OAuth** | None | Real OAuth flow, callback endpoint, `email_verified`-gated account linking, built against `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` env vars | Two-tiered: logic/unit verification lands with the code; full live Google round-trip explicitly marked **pending** until real credentials are provided — same treatment as the Gemini quota situation, not conflated with "broken" | Phase 3 |
| 6 | **Auth + Onboarding UI** | Signup/login wired to real endpoints; onboarding wired to Phase 4 (real persistence from day one); Google button wired to Phase 5 | — | Real signup, login, onboarding persistence, all live-verified | Phase 2, 4; OAuth functional once Phase 5 + real credentials land |
| 7 | **App shell** | Sidebar/topbar/routing/command palette/toasts/notifications/AXIOM FAB, light/dark theme switching (client-side, upgraded to server-persisted in Phase 16) | None | Visual + interaction comparison to prototype | Phase 2 |
| 8 | **Chat sessions + tool trace** | None | `GET /chat/sessions` (tenant-scoped session list); real tool-call trace included in chat response | Multi-session real chat; session list correctly tenant-scoped; tool trace reflects tools actually executed | None |
| 9 | **Dashboard** | Wired to real KPIs (pipelines/quality/incidents/approvals/sources) + AXIOM Activity via Phase 8 | — | Live dashboard against real tenant data | Phase 7; Phase 8 for AXIOM Activity |
| 10 | **AXIOM chat (3-panel)** | Wired to real chat/history; graceful loading/fallback UX; real provider-switch messaging via Phase 1's `provider` field | — | Real multi-turn conversation; loading states and provider display accurate | Phase 7, 1, 8 |
| 11 | **KPI instrumentation + lineage auto-population** | None | Write a `KpiValue` point on every quality-check run; auto-create `LineageNode`/`LineageEdge` on pipeline/source creation | Real quality check → KPI row appears in `/analytics/kpis`; real pipeline+source → `/governance/graph` non-empty | None |
| 12 | **Core DataOps screens** | Sources, Pipelines, Quality (real trend), Incidents, CI/CD, Approvals (merged), Governance (real lineage/contracts/audit) | Small: Approvals-merge aggregation endpoint | Full live walkthrough against real tenant data, mirroring the Phase 4 backend verification already done this project | Phase 7; Phase 11 for Quality/Governance fidelity |
| 13 | **Transform history + catalog aggregation** | None | Transform-run persistence model; thin aggregation endpoint over `schema_snapshot` for catalog | Real SQL/pandas transform → listed/replayable; catalog reflects real profiled sources | None |
| 14 | **Transforms + Data Catalog** | Wired to Phase 13 | — | Live verification of NL/SQL/Python tabs + History; live catalog view | Phase 13 |
| 15 | **Plan/quota + Team** (Track 2, largest phase) | None | Plan/quota schema + shared quota-check dependency; invite/roles schema + `require_role()` dependency (retrofit onto CI/CD approve/reject at minimum — see audit above for other candidates); `BillingService` interface with Stripe stubbed behind it | Real invite email (existing SMTP) → accept → joins existing tenant with correct role; a restricted role is actually blocked on CI/CD approve/reject; quota soft-warn/hard-block triggers against Phase 1's real usage data | Phase 1 (real usage numbers), Phase 3 (auth architecture) |
| 16 | **Settings persistence** | None | Workspace config, notification prefs, per-tenant AI model override (**with the `_cache` re-keying fix — see Gotchas**), theme server-persistence, API-keys model + endpoints | Change a tenant's model preference → next chat request actually uses it **and** a different tenant is unaffected (explicit cross-tenant test); theme/notification/workspace round-trip; API key create/list/revoke works | Phase 1, 15 |
| 17 | **Team, Billing, Settings UI** | Wired to Phase 15/16 | — | Live verification of invites, roles, plan/quota display, all settings tabs | Phase 15, 16 |
| 18 | **AI Employees + Landing page** | Locked tiles (as designed), public landing page | None | Visual QA | Phase 2 (can move earlier for marketing urgency) |
| 19 | **Polish** | Responsive/accessibility/visual QA/performance | — | Full cross-screen pass | All prior |

---

## Outstanding items (user's side)

- **Google OAuth client id/secret** — being created in Google Cloud Console;
  will be provided via `.env` (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`)
  when ready. Phase 5 can be built and unit-tested without these; full live
  verification is blocked until they arrive.
- **Gemini billing** — still unresolved on Google Cloud's side (the API key shows
  `limit: 0` on the free tier even after rotation — an account/billing-tier issue,
  not a code issue). Groq fallback works correctly and is the effective primary
  provider until this is sorted. Affects Phase 1's `provider` field distribution and
  Phase 10's live testing of "healthy-Gemini" paths, not anything structural.

---

## Where a fresh session should start

1. `CLAUDE.md` (repo root) — backend state, workflow rules, Gotchas
2. This file (`FRONTEND_BUILD_PLAN.md`, repo root) — what's being built and in what order
3. `dataops-agent/DESIGN_TOKENS.md` — locked palette/typography values
4. `dataops-agent/frontend/wunomo-ai MASTER DESIGN.html` — the design source of truth
   for layout/components/screens (palette/fonts in it are superseded by the above)
