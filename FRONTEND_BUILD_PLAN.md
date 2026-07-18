# Wunomo AI — Frontend Build Plan

**Status: Phases 0, 2-10, and 12-16 complete and fully live-verified** (plus Phase
11's lineage half, pulled forward into Phase 12 — see that row). **Phase 17 (Team,
Billing, Settings UI) is in progress** — Settings is done and fully live-verified,
Team and Billing remain, per the "Phase 17 decisions (locked)" spec below (proposed
and approved in a docs-only session, 2026-07-18, before any code was written; no new
backend/migration work needed, everything it wires to already exists and is
live-verified). Build order: Settings → Team → Billing — Settings' live
verification also settled two build-session amendments: the backend's
`notify_on` deep-merge genuinely persists an explicit `false` (confirmed via raw
`curl` before the UI even existed), and the API Keys tab's raw secret is provably
absent from browser storage and never resurfaces after a reload. Phase 16 (Settings
persistence) closed out this session — the `get_agent()` cache re-keying fix +
per-tenant AI model override (Phase 0's approved pushback #2, live-verified with two
real different LLM providers and zero cross-tenant leakage), workspace config,
notification prefs (which surfaced and fixed a real bug: `NotificationService` had
referenced entirely nonexistent Settings fields since it was written), theme
server-persistence, and platform API keys (CRUD only, deliberately not wired to
request authentication yet — see `CLAUDE.md`'s Not-yet-built). All three of the
phase's verification gates (model-preference cross-tenant test; theme/notification/
workspace round-trip; API key create/list/revoke) are closed — see `CLAUDE.md`'s
Phase 16 Status Table rows for full detail. Phase 15 (Plan/quota + Team) closed the
session before — `require_role()` and `enforce_quota()` shared dependencies, real
team invites (Resend-delivered, live-verified), team member management, a 3-tier
plan/quota system calibrated against this project's own real usage data, and a
`BillingService` interface with Stripe honestly stubbed behind it; also closed the
long-standing CI/CD double-booked-approval bug along the way.
See the phase table below for the authoritative, per-phase status and verification
detail for each — this banner is a quick pointer, not a substitute for it. This is
the authoritative, signed-off plan for building the Wunomo AI frontend against the
real `dataops-agent` backend. Referenced from `CLAUDE.md` — read that file first
for the backend's current state, then this file for what's being built on top of it
and in what order.

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

## Phase 3 decisions (locked)

Auth design proposal, approved. Grounded in a full read of `api/v1/auth.py`, which
surfaced two pre-existing bugs now tracked in CLAUDE.md's Known-broken table (see
below) — the design closes both rather than just describing them.

**Core principle:** identity is scoped to `(email, tenant)`, not to email alone. The
same email existing in multiple tenants is not a conflict — it's independent workspace
memberships (Slack's model). "Linking" only ever means attaching a second login method
to one specific existing `(email, tenant)` account; it never merges or blocks across
tenants.

**JWT claims:** `sub` (user.id), `tenant_id`, `email`, `role` — all unchanged. Adds
`auth_method` (`"password" | "google"`, extended to a third value below) and `iat`.
Deliberately not adding `personality_mode`/`operation_mode` (already correctly read
fresh per-request elsewhere — embedding them would create staleness) or an
`email_verified` claim (checked server-side at linking time, not worth persisting into
every token).

**`User` model changes required** (migration proposed separately before it lands):
`hashed_password` becomes nullable (Google-only accounts have none); new `google_id:
str | None`, indexed but **not** globally unique (the same Google identity can
legitimately link to more than one tenant-account); new `email_verified: bool = False`,
set `True` only when Google's own `email_verified` claim was `true` at linking time.

**Three signup/login paths:**
1. **Fresh email/password signup** — unchanged (new tenant, role `owner`), plus a
   **non-blocking informational nudge** if the email already exists in another tenant
   ("you already have a workspace under this email — log in instead, or continue").
2. **Google OAuth** — splits on context, not on the token: *"create new workspace"* via
   Google always makes a fresh tenant (never conflicts, same reasoning as #1). *"Continue
   with Google" against a specific existing tenant* (invite flow, or a workspace-scoped
   login) looks up `(tenant_id, email)`; auto-links to an existing password account
   **iff** Google's `email_verified` claim is `true`; if `false`, blocks the auto-link
   and redirects to password login — never silently links on an unverified email, never
   silently creates a duplicate (the unique constraint wouldn't allow one in the same
   tenant anyway).
3. **Invite-based join** — tenant_id and role come from the invite token, never user
   input. Invites are email-locked (same spoofing-prevention spirit as the OAuth rule).
   Redeeming against an email already a member of that same tenant → rejected as
   "already a member"; against other tenants → irrelevant, proceeds as an independent
   membership. (Invite table/endpoints themselves are Phase 15's build; this is the
   resolution logic Phase 15 implements against.)

**Login disambiguation (built now, not deferred — fixes the pre-existing arbitrary-match
bug):** to avoid leaking "this email exists somewhere" to an unauthenticated caller,
resolution happens only *after* a credential match, never before. Client submits
email+password in one call; server checks the password against every `User` row with
that email across tenants. Exactly one match → issue the JWT immediately (identical to
today's UX). Multiple matches → return a workspace list with **no token yet**; client
resubmits with a chosen `tenant_id`; server re-verifies scoped to that tenant and issues
the token. Zero matches → the same generic "invalid credentials" as today, no
distinction leaked between wrong-password and no-such-email.

**Third method — email + one-time code (passwordless), added after the above was
approved.** Uses the Resend service already planned for Phase 15, free-tier only, no
phone/SMS OTP. `auth_method` gets a third value, `"email_code"`. No new `User` columns
beyond what Google already requires — a successful verification also sets
`email_verified = true` on the linked row (reusing that column, not duplicating it).

*Tenant resolution* mirrors the Google split, plus one addition Google didn't need:
"create new workspace" always makes a fresh tenant (never conflicts); "continue" against
a specific existing tenant resolves `(tenant_id, email)` and auto-links (see below); a
**general, non-tenant-scoped login** — a code only proves *which email*, not *which
tenant* — resolves every tenant-account for that email after verification: one match
logs straight in, multiple show a workspace picker, zero can safely say "no workspace
found for this email, create one?" **because by that point ownership is already
proven** — the enumeration risk that shapes the password-login design doesn't apply
post-verification.

*Auto-link on first `email_code` login against an existing password/Google account:*
**approved, reasoned independently, not by default-matching the Google rule.**
Email-code is a direct, first-party, real-time proof (we generate the secret, choose
the channel, verify the round-trip immediately) — at least as strong as, arguably
stronger than, trusting Google's indirect historical claim, and structurally the same
trust mechanism the industry already uses for "forgot password" flows, which authorize
strictly more sensitive actions (full account takeover) than adding a second login
method. Anyone who could abuse auto-link via a received code could equally abuse a
future password-reset email, so this doesn't lower the system's trust bar, just
applies the one it already implies elsewhere.

*Rate limiting / abuse prevention* (defaults below — sensible starting points, tunable
later without a redesign). Two storage layers matching what's already in this stack:
Redis (already used for Celery/cache, DB 0) for ephemeral counters, Postgres for the
durable code record.

`EmailLoginCode` table: `email` (indexed), `code_hash` (SHA-256, deliberately not
bcrypt — protection comes from TTL + attempt caps, not hash slowness, and slow hashing
only hurts legitimate retry latency), `intended_tenant_id` (nullable — null means
new-workspace/general context), `expires_at`, `attempts_used`, `consumed_at`
(single-use, set on success, blocks replay), `request_ip` (audit — see Gotchas for the
X-Forwarded-For caveat on this field).

| Control | Default | Stops |
|---|---|---|
| Code TTL | 10 min | Stale-code brute-forcing |
| Max verify attempts per code | 5 | Guessing within a code's lifetime (6-digit space, 5 attempts ≈ 0.0005% success) |
| Resend cooldown | 60s per email | Inbox-bombing, rapid-fire request+guess cycles |
| Requests per email | 5/hour | Sustained abuse against one target, Resend free-tier quota protection |
| Requests per IP | 20/hour | One attacker spraying many different emails |
| Lockout | 30 min, after 3 consecutive fully-exhausted codes for the same email | Closes the loophole where an attacker just requests fresh codes for fresh attempt budgets |

Enumeration safety is symmetric with the password design: all rate-limit/lockout
bookkeeping is keyed by the *raw submitted email string*, independent of whether it
resolves to a real account, so a non-existent email rate-limits/locks out exactly like
a real one under the same request pattern. The request endpoint only ever returns
"code sent" (always, real account or not) or "rate limited" (depends only on request
pattern) — neither leaks account existence. Verification failures are uniform too:
expired, wrong, and locked-out all return the same generic "invalid or expired code."

**Summary — all three methods:**

| | Password | Google OAuth | Email code |
|---|---|---|---|
| `auth_method` | `"password"` | `"google"` | `"email_code"` |
| Proves | knowledge of a per-`(tenant,email)` secret | Google's historical claim | real-time inbox control |
| New-workspace signup | always fresh tenant | always fresh tenant | always fresh tenant |
| Existing-tenant login | check hash, disambiguate if >1 tenant matches | auto-link iff `email_verified` from Google | auto-link (reasoned above) |
| Sets `User.email_verified` | no | yes, from Google's claim | yes, on successful verify |

**Latent bugs this design closes** (found while reading `api/v1/auth.py` to ground the
design, now tracked in CLAUDE.md's Known-broken table — locked as bugs to fix when this
lands, not yet fixed): `login()` has no tenant scoping on its email lookup and silently
authenticates into an arbitrary tenant-account if the same email exists in more than
one tenant (the schema explicitly allows this); `register()` never checks for an
existing email before creating a new tenant, so duplicate signups under the same email
silently produce orphan tenants with no warning. Both fix directions are specified
above (login disambiguation; the non-blocking signup nudge) and are approved to build
now, not deferred.

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

## Phase 17 decisions (locked)

Proposed and approved in a docs-only session (2026-07-18) before any code was
written — build sessions should treat this as the spec, not re-derive it. No new
backend/migration work is needed anywhere in this phase; every endpoint below
already exists and is live-verified (Phase 15/16). Build order: **Settings → Team →
Billing** (ascending complexity), each screen live-verified via Playwright against
the real backend before moving to the next, both themes screenshotted, same
methodology as every prior phase.

**`lib/api.ts` additions** (typed client, same pattern as every prior phase):
- Team: `TeamMember`, `TeamInvite` types; `getTeamMembers`, `getTeamInvites`,
  `createTeamInvite`, `revokeTeamInvite`, `changeMemberRole`, `removeTeamMember`
- Billing: `QuotaStatus`, `PlanLimits` types; `getUsage` (4-resource bars),
  `getPlans`, `getCurrentPlan`, `changePlan`
- Settings: `TenantSettings` type; `getSettings`, `updateSettings`
- Auth `/me`: `getMe`, `updateMe` (theme)
- API keys: `ApiKeyItem`, `ApiKeyCreated` types; `createApiKey`, `listApiKeys`,
  `revokeApiKey`

**Team screen (`/team`)**: member table (email, role, status, joined) + pending-
invites table (email, role, status, expires, revoke). Invite modal (email + role
`<Select>` from `ALL_ROLES`). Role change via inline `<Select>` per row →
`PATCH /members/{id}/role`. All mutation controls (invite/revoke/role-change/
remove) hidden — not just disabled — for non-Owner/Admin, using
`decodeUserFromToken()`'s `role` claim, matching the backend's real `require_role`
gate so a Viewer never sees a control they'd 403 on. Self-row and last-owner
protections surfaced as disabled+tooltip rather than hidden, since those are
legitimate-but-blocked states, not a permissions issue.

**Billing screen (`/billing`)**: current plan card (name + limits from `GET
/plan`) with an upgrade `<Select>` + confirm (Owner/Admin only) → `POST
/change-plan`, labeled as taking effect immediately (dev-mode stand-in, matches
the `BillingService` docstring — no fake "processing payment" UI). Four real usage
bars from `GET /billing/usage` using the existing `<Progress>` component, colored
by the real `status` field (`ok`/`warning`/`exceeded`) rather than a client-side
recomputation. Checkout/invoices section explicitly labeled "Coming soon" with no
fabricated invoice rows — matches the backend's honest-501 pattern
(`POST /checkout`).

**Settings screen (`/settings`)**, tabs (reusing `<Tabs>`, same pattern as
Governance/Transforms):
1. **Workspace** — name/timezone/description form → `PATCH /settings/`
2. **Notifications** — Slack webhook + alert email + the 4 `notify_on` toggles,
   deep-merge-safe (only send changed keys)
3. **AI Model** — `<Select>` restricted to the 2-entry allowlist + "use plan
   default" option. **Adjustment from the original proposal**: hardcode the
   2-item list client-side (not fetched from the backend, since there's no list
   endpoint for it) with a code comment pointing at
   `services/llm_service.py`'s `SUPPORTED_MODEL_OVERRIDES` as the source of
   truth — so a future reader knows exactly where to check/update if the
   allowlist ever changes, rather than the two lists silently drifting apart
4. **Theme** — Light/Dark/System, calls `PATCH /auth/me`
5. **API Keys** — create (name input) → show raw key once in a `<Modal>` with a
   copy button and a clear "you won't see this again" warning; list (masked,
   last-used, created); revoke. Copy explicitly states keys are for
   reference/audit today, **not yet accepted as request credentials** — no
   wording implying they can authenticate anything (per the explicit instruction
   carried over from Phase 16's approval).

Tabs 1-3 and 5's mutations are Owner/Admin-gated (hidden for other roles,
read-only view shown instead); Theme is self-service for anyone since it's
per-user.

**Theme reconciliation**: keep the existing localStorage pre-paint script
(`app/layout.tsx`) as the synchronous fast-path — avoids flash-of-wrong-theme,
can't be replaced by an async fetch before paint. Layer the server on top: on the
`(app)` shell mount, fetch `GET /auth/me` and if the server's `theme` differs from
localStorage, apply it (update `document.dataset.theme` + localStorage) — server
wins once loaded, since it's the durable preference. Both `ThemeToggle`'s toggle
and the Settings tab write through to `PATCH /auth/me` in addition to
localStorage/DOM, so either entry point stays in sync. "System" resolves via
`matchMedia('(prefers-color-scheme: dark)')` at apply time; the toggle button
itself always writes an explicit `light`/`dark` (never `system`), since a binary
click has no "system" gesture.

**Resend/invite verification — adjustment from the original proposal**: the
Resend account backing this project is still sandbox-limited (domain verification
pending on the user's side, tracked in Outstanding items below). This phase's live
proof of the invite flow is scoped to sending to **the account owner's own
verified address only** — creation, real email delivery, `verify`/`accept` round
trip, and role/roster updates. That counts as this phase's live verification gate
for invites; sending to an arbitrary third-party address is out of reach until the
domain is verified and gets flagged as untestable-pending-domain-verification, not
silently skipped or claimed as fully verified.

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
| 5 | **Non-password auth: Google OAuth + email-code** — **done, fully live-verified** | None | Real Google OAuth flow, callback endpoint, `email_verified`-gated account linking, built against real `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` env vars; **plus** the email-code method (Resend integration, `EmailLoginCode` table + rate limiting, auto-link on verify) — bundled into one phase since both share the `User` schema migration (nullable `hashed_password`, `google_id`, `email_verified`), the JWT `auth_method` handling, and the auto-link machinery designed together in Phase 3 | Both methods fully live-verified end-to-end. Email-code: a real, fully-automated Resend delivery round-trip (code sent, retrieved via Resend's own API, verified, JWT issued). Google: the user clicked through the real consent screen; the resulting code was exchanged and verified for real against Google's production endpoints, correctly auto-linking onto an account originally created via email-code (not password) rather than creating a redundant tenant — confirms auto-link works from either originating method | Phase 3 |
| 6 | **Auth + Onboarding UI** — **done, fully live-verified** | Signup/login wired to real endpoints; onboarding wired to Phase 4 (real persistence from day one); Google button **and email-code flow** wired to Phase 5 | — | Real signup, login, onboarding persistence, all live-verified | Phase 2, 4; OAuth functional once Phase 5 + real credentials land (email-code live-verifiable independently of Google credentials) |
| 7 | **App shell** — **done, fully live-verified** | Sidebar/topbar/routing/command palette/toasts/notifications/AXIOM FAB, light/dark theme switching (client-side, upgraded to server-persisted in Phase 16) | None | Visual + interaction comparison to prototype | Phase 2 |
| 8 | **Chat sessions + tool trace** — **done, fully live-verified** | None | `GET /chat/sessions` (private-per-user AND tenant-scoped session list); real tool-call trace included in chat response | Multi-session real chat; session list correctly scoped; tool trace reflects tools actually executed — verified via 5 regression tests plus a real end-to-end round trip once Groq's quota freed up (real tool call, real result, real trace persisted and returned) | None |
| 9 | **Dashboard** — **done, fully live-verified** | Wired to real KPIs (pipelines/quality/incidents/approvals/sources) + AXIOM Activity via Phase 8 | Small new `GET /analytics/recent-runs` endpoint | Live dashboard against real tenant data | Phase 7; Phase 8 for AXIOM Activity |
| 10 | **AXIOM chat (3-panel)** — **done, fully live-verified** | Wired to real chat/history; graceful loading/fallback UX; real provider-switch messaging via Phase 1's `provider` field | — | Real multi-turn conversation; loading states and provider display accurate — all checks done, including the previously-deferred multi-turn/tool-trace/mode-switch/approval-gate live proof (run once Gemini's daily quota reset; also settled approval-persistence with live proof and fixed a real risk_level bug found in the same pass — see `CLAUDE.md`) | Phase 7, 1, 8 — LangChain v1.x upgrade (done, see `CLAUDE.md`) and the 22-site `agent/tools/*.py` punch list (done) are no longer blockers |
| 11 | **KPI instrumentation** — lineage half **done, pulled forward into Phase 12** | None | ~~auto-create `LineageNode`/`LineageEdge` on pipeline/source creation~~ **done** (`LineageTracker.sync_tenant_lineage()`, hooked into source/pipeline creation plus a self-healing sync on every `/governance/graph` read so pre-existing tenants backfill too — see CLAUDE.md Status Table). **Remaining scope**: write a `KpiValue` point on every quality-check run — not needed by any Phase 12 screen, still pending | Real quality check → KPI row appears in `/analytics/kpis` | None |
| 12 | **Core DataOps screens** — **done, fully live-verified** | Sources, Pipelines, Quality (real trend), Incidents, CI/CD, Approvals (merged), Governance (real lineage/contracts/audit) — all 7 built, replacing their Phase 7 stubs | `GET /api/v1/approvals/merged` (done); lineage auto-population pulled forward from Phase 11 (done) | Full live Playwright walkthrough per screen against real tenant data (create/update/delete/action flows, both themes screenshotted). Also did the cross-cutting 401-handling fix as pre-work (see CLAUDE.md) | Phase 7; lineage auto-population (done, see Phase 11) |
| 13 | **Transform history + catalog aggregation** — **done, fully live-verified** | None | `TransformRun` persistence model (executions only, both REST and chat-tool paths); `GET /api/v1/catalog/` thin aggregation over `schema_snapshot`. Also fixed 2 real bugs found along the way (see `CLAUDE.md`): `TransformGenerator._resolve_schema()` ran schema-blind for every source (wrong shape assumption), and `invoke_llm()` crashed on Gemini 3.5's list-shaped content (same class of bug as the agent-graph fix, different call path) | Real SQL/pandas transform → listed/replayable — confirmed via a real CSV execution (success + a real syntax-error case), both correctly persisted; catalog reflects real profiled sources — confirmed against a real profiled CSV source | None |
| 14 | **Transforms + Data Catalog** — **done, fully live-verified** | Wired to Phase 13 | `GET /api/v1/transformations/runs` (addendum — Phase 13 had persistence but no read endpoint) | Live verification of NL/SQL/Python tabs + History; live catalog view — all done, see `CLAUDE.md`'s Phase 14 Status Table row | Phase 13 |
| 15 | **Plan/quota + Team** (Track 2, largest phase) — **done, fully live-verified** | None | `require_role()` + `enforce_quota()` shared dependencies (retrofitted onto CI/CD approve/reject plus the rest of the approved high-priority list); `TeamInvite` schema + invite create/list/revoke/accept + team member list/role-change/soft-removal; 3-tier `PLANS` config + quota enforcement on the 4 clearest cost/volume drivers; `BillingService` interface with Stripe stubbed behind honest `501`s. Also fixed the long-standing CI/CD double-booked-approval bug along the way (see CLAUDE.md Known-broken, now resolved) | All 3 gates closed and live-verified against the real running server (not just pytest) — see CLAUDE.md's Phase 15 Status Table rows for full detail: (1) a real invite email delivered via Resend (`last_event: "delivered"`), accepted, joined the *existing* tenant with the locked role, real subsequent login succeeded; (2) a real downgraded-to-viewer JWT got a real 403 on CI/CD approve, the same commit's owner token still succeeded; (3) quota status/enforcement verified against *real pre-existing* `llm_usage_events` history on an actual tenant from earlier in this project (not synthetic seeds) — correctly reported `exceeded` and hard-blocked `/chat/` with a real 402, and a separately-seeded tenant correctly showed the soft-warn band at 85% without being blocked | Phase 1 (real usage numbers), Phase 3 (auth architecture) |
| 16 | **Settings persistence** — **done, fully live-verified** | None | Workspace config, notification prefs, per-tenant AI model override (with the `_cache` re-keying fix), theme server-persistence, API-keys model + endpoints (CRUD only, not wired to request auth yet) | All 3 gates closed and live-verified against the real running server: two real tenants with different model overrides got two real, different LLM providers (`groq`/`llama-3.3-70b-versatile` vs `gemini`/`gemini-3.5-flash`) with zero cross-contamination; workspace rename/timezone/description and theme both round-tripped through a fresh `GET` after a `PATCH` (not a same-request echo); notification prefs verified by spying on the real `urlopen` call (trusting HTTP status alone was a false signal — Slack redirects bad webhook paths to a 200 page); API key create/list/revoke all confirmed live, raw secret shown exactly once and never in the list response. See `CLAUDE.md`'s Phase 16 Status Table rows for full detail. | Phase 1, 15 |
| 17 | **Team, Billing, Settings UI** — **Settings done and live-verified; Team, Billing not yet built** | Wired to Phase 15/16 — see "Phase 17 decisions (locked)" above for the full approved spec (screen-by-screen breakdown, `lib/api.ts` additions, theme reconciliation, role-gating, invite-verification scope) | — | **Settings: closed.** All 5 tabs round-tripped live (owner + a re-logged-in downgraded viewer), including the `notify_on` explicit-false persistence and the raw API-key secret's absence from browser storage — see `CLAUDE.md`'s Settings screen Status Table row. **Team, Billing: pending** — invites (scoped to the account owner's own address, per the Resend sandbox limit), roles, plan/quota display | Phase 15, 16 |
| 18 | **AI Employees + Landing page** | Locked tiles (as designed), public landing page | None | Visual QA | Phase 2 (can move earlier for marketing urgency) |
| 19 | **Polish** | Responsive/accessibility/visual QA/performance | — | Full cross-screen pass | All prior |

---

## Outstanding items (user's side)

- ~~**Google OAuth client id/secret**~~ — resolved. Real credentials configured and
  fully live-verified through both Phase 5 (backend) and Phase 6 (UI click-through),
  including a real fix for a clock-skew bug found during the Phase 6 UI test — see
  `CLAUDE.md` Gotchas.
- ~~**Gemini billing**~~ — resolved. Root cause was never billing: `gemini-2.0-flash`
  had been deprecated by Google (free tier removed), so every key showed `limit: 0`
  regardless of account state. Fixed by switching to `gemini-3-flash-preview`, then to
  `gemini-3.5-flash` — see `CLAUDE.md` Gotchas. Gemini 3 tool-calling itself is fully
  working now (LangChain v1.x upgrade, done).
- **Not user-actionable, but worth knowing**: `gemini-3.5-flash` carries the same flat
  20 requests/day free-tier cap as the preview model did — not a preview-vs-GA
  distinction, confirmed by direct counter-evidence (see `CLAUDE.md` Gotchas). Groq's
  shared org-level daily token quota has also been independently exhausted more than
  once. Phase 10's live-send verification is now complete (run in a follow-up
  session once Gemini's quota reset) — any future session doing live-LLM
  verification should still check quota state first before spending, per the
  established pattern.
- **New, user-actionable: Resend domain verification** — the Resend account backing
  Phase 15's team invites and Phase 5's email-code auth is still in sandbox mode.
  `onboarding@resend.dev` can only deliver to the account owner's own verified
  address (confirmed live — a send to any other real address gets a real `403` from
  Resend's API). Real invites to actual teammates, and real email-code sign-in for
  anyone other than the account owner, will silently fail to deliver (the app itself
  reports success either way, by design — see `CLAUDE.md`'s enumeration-safety
  Gotcha) until a domain is verified at resend.com/domains and `EMAIL_FROM` switches
  off the shared sandbox address. Not blocking any further backend work — Phase
  15's own verification gate was satisfiable by sending to the owner's own address —
  but it will block real end-user-facing use of either feature until done.

---

## Where a fresh session should start

1. `CLAUDE.md` (repo root) — backend state, workflow rules, Gotchas
2. This file (`FRONTEND_BUILD_PLAN.md`, repo root) — what's being built and in what order
3. `dataops-agent/DESIGN_TOKENS.md` — locked palette/typography values
4. `dataops-agent/frontend/wunomo-ai MASTER DESIGN.html` — the design source of truth
   for layout/components/screens (palette/fonts in it are superseded by the above)
