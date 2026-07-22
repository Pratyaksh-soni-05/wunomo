# Wunomo AI — Frontend Build Plan

**Status: Phases 0, 2-10, and 12-18 complete and fully live-verified** (plus Phase
11's lineage half, pulled forward into Phase 12 — see that row). **Phase 18 (AI
Employees + Landing page) is done** — AI Employees (3 deliberate deviations from
the literal master design: no waitlist button, no marketplace button, no
per-tile pricing until real Stripe pricing exists) and the landing page (replaces
the Phase 2 component-showcase scaffold that had silently occupied root `/`;
platform-first copy signed off in full before code; social proof omitted
entirely; roster copy shares a single source of truth with `/ai-employees` via a
new `lib/employees.ts` extraction so the two pages can't drift) — see "Phase 18
note" below for the full amendment list. Real deployment is separately gated on
the domain purchase, tracked in Outstanding items — this phase's "done" means
built and verified locally only, per explicit instruction. **Phase 17
(Team, Billing, Settings UI) is done** — all three screens built, per the "Phase
17 decisions (locked)" spec below (proposed and approved in a docs-only session,
2026-07-18, before any code was written; no new backend/migration work needed,
everything it wired to already existed and was live-verified). Build order was
Settings → Team → Billing. Settings' live verification settled two amendments
(the backend's `notify_on` deep-merge genuinely persists an explicit `false`; the
API Keys tab's raw secret is provably absent from browser storage and never
resurfaces after a reload). Team's live verification closed a real gap the
original locked spec left open (invite creation was speced, invite *acceptance*
wasn't — a new public `/invite/accept` page closed the loop) and confirmed a live
finding now tracked as **Known-broken** (not just a Gotcha, per explicit
instruction): a removed member's JWT keeps working for up to the JWT's full
60-minute TTL, `is_active` isn't re-checked per request — flagged as a Phase 19
candidate. Billing's live verification found and confirmed a second real backend
gap, also tracked in Known-broken: `change_plan()` allows any plan downgrade
unconditionally, even one that immediately exceeds the new plan's limits, with no
payment gate either — the UI reflects this honestly (a non-blocking warning
naming the specific over-limit resource) rather than pretending to block it.
Phase 16 (Settings
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

**Addendum, found during the Team build**: this spec never actually described an
invite-*acceptance* UI — only creation/list/revoke on `/team`. Closed in the same
session rather than deferred: a new public `frontend/src/app/invite/accept/page.tsx`
(no auth guard, outside the `(app)` group) calls `GET /team/invites/verify` and
`POST /team/invites/accept`. Treat this as part of the real, built spec going
forward.

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

## Phase 18 note: AI Employees + landing page amendments

`renderAIEmployees()` in the master design (`wunomo-ai MASTER DESIGN.html:1317-1373`)
includes a "Join Waitlist" button per locked tile, a "Browse Marketplace" header
button, and a per-tile price (`$59/mo` etc.). Built with three deliberate
deviations, decided in-session rather than shipped as literally designed:

- **"Join Waitlist" dropped entirely** (no `mailto:` fallback either) — it wired
  to nothing real in the design and there's no backend for it this phase (zero
  backend prerequisite, per the table above). The "Coming Soon" overlay badge
  stands alone as a non-interactive label.
- **"Browse Marketplace" dropped** — implies a marketplace that doesn't exist.
  The "1 Active" header badge stays; that one's honestly true (AXIOM is real).
- **Per-tile pricing omitted.** Those numbers are Phase 0 mockup placeholders,
  not committed product pricing — showing a firm price for an unpurchasable
  product creates a commitment that hasn't actually been made. **AI-employee
  pricing display is deferred until real pricing is set alongside the Stripe
  integration work** (see `BillingService`'s stubbed payment methods,
  `CLAUDE.md`).

**Landing page** — no mockup existed anywhere in the repo for this (confirmed by
reading `design-proposal.html` in full — it's the Phase 0 palette/typography
sign-off doc, not a landing page). Built from copy proposed and signed off in
full before any code was written; positioning was platform-first ("hire AI
employees," not AXIOM-first), per the user's explicit bullets. Social-proof
section omitted entirely, per instruction, rather than filled with placeholder
logos/testimonials/counts — features flow straight into the final CTA. No
screenshots this version — description-only feature blocks; real screenshots
are deferred to deploy time against a production-shaped tenant (a QA tenant's
exceeded-usage bars are not hero material). The AXIOM roster tile's CTA is
auth-aware (`"Get Started with AXIOM"` → `/signup` logged out, `"Open AXIOM →"`
→ `/chat` logged in), read client-side via a `useEffect`-only hook deliberately
designed to add no *new* hydration-mismatch warnings beyond the one this page
already inherits from the root layout's theme pre-paint script (see
`CLAUDE.md`'s Gotchas — found during the AI Employees build, confirmed, not
re-discovered, on the landing page too). Replaces the Phase 2 component-showcase
scaffold that had silently occupied root `/` since Phase 2. Real production
deployment is separately gated on the domain purchase (see Outstanding items) —
this phase's own definition of done was built-and-verified-locally only.

**Phase 19 polish addendum**: the landing page was substantially rebuilt in a
later session — real logo (nav/footer mark + hero wordmark), a real
screenshot carousel from a freshly-seeded demo tenant (no fabricated
numbers), real About and Contact sections, section-anchor nav with a
light/dark toggle, and a hero load-in animation that fully respects
`prefers-reduced-motion`. See `CLAUDE.md`'s "Landing page rebuild" Status
Table row for the complete build and live-verification detail — this note
is a pointer, not a duplicate.

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
| 17 | **Team, Billing, Settings UI** — **done, fully live-verified** | Wired to Phase 15/16 — see "Phase 17 decisions (locked)" above for the full approved spec (screen-by-screen breakdown, `lib/api.ts` additions, theme reconciliation, role-gating, invite-verification scope) | — | **Settings: closed.** All 5 tabs round-tripped live (owner + a re-logged-in downgraded viewer), including the `notify_on` explicit-false persistence and the raw API-key secret's absence from browser storage. **Team: closed.** Full invite lifecycle live-verified including real Resend delivery, a real accept round trip through a clean unauthenticated browser context (via a new `/invite/accept` page this session added — not in the original spec), 2-owner guard coverage in both directions, and a JWT-replay-after-removal finding (access persists until expiry) now tracked in `CLAUDE.md`'s Known-broken table with severity and the real token TTL. **Billing: closed.** Real plan card + upgrade/downgrade picker + 4 usage bars, all live-verified against genuinely seeded usage (not an all-zero tenant); found and confirmed a second real backend gap (unconditional downgrades, no payment gate) also tracked in Known-broken, with the UI honestly warning rather than pretending to block it. See `CLAUDE.md`'s Settings/Team/Billing screen Status Table rows for full detail. | Phase 15, 16 |
| 18 | **AI Employees + Landing page** — **done, fully live-verified** | Locked tiles (as designed, with amendments — see note below), public landing page (replaces the Phase 2 scaffold at root `/`) | None | Visual QA — both screens: explicit rendered-text audits, both themes, desktop+mobile widths on the landing page, clean logged-out context, every link resolves, hydration-warning check (found app-wide during this phase, tracked in `CLAUDE.md` Gotchas, not fixed here) | Phase 2 (can move earlier for marketing urgency) |
| 19 | **Polish** | Responsive/accessibility/visual QA/performance | — | Full cross-screen pass | All prior |

---

## Phase 19 note: Known-broken must be triaged, not just inherited

`CLAUDE.md`'s Known-broken table has grown across every phase — some rows are
already resolved, some are real gaps nobody has decided whether to fix before
real users arrive. As part of Phase 19, every still-open Known-broken row must
be explicitly partitioned into one of two buckets: **fix in Phase 19** (with the
actual fix), or **accepted-for-launch** (with a written rationale for why it's
safe to ship as-is — not silence, not an assumption). Launch readiness is a
decision to make deliberately, not a default that falls out of an unreviewed
backlog. Two rows already flagged as real candidates for the "fix" bucket from
this project's own recent work: the removed/demoted-member JWT-persistence gap
(Phase 17, Team) and `change_plan()`'s unconditional-downgrade/no-payment-gate
gap (Phase 17, Billing) — both tracked in `CLAUDE.md`'s Known-broken table with
severity and fix directions already written up; Phase 19 should resolve or
consciously accept each of them, not let them ride through undecided.

---

## Phase 19 partition status (as of 2026-07-23 — keep this current every session)

**NEXT SESSION STARTS HERE.** Recommended next item: the **dark-theme
screenshot verification pass** (see below) — the token redesign already
landed and is the freshest unfinished thread. If Gemini's daily quota is
tight when you start (check first, cheap probe — see `CLAUDE.md`'s
quota Gotchas), that's not a blocker for this item, since the screenshot
pass needs zero LLM calls. The **migration-drift session** (below) is the
other reasonable starting point and is arguably higher-risk/higher-value
if you'd rather tackle that first — both are unblocked and don't depend
on each other.

One line per item: **DONE** (live-verified, closed), **REMAINING**
(still open, no decision made on priority), **UNDECIDED** (a real gap
with a written rationale needed, not yet triaged into fix-vs-accept per
the note above), **ACCEPTED-FOR-LAUNCH** (consciously decided safe to
ship as-is), or **DOMAIN-GATED** (blocked on the user's side, tracked in
Outstanding items).

**P0 (launch-blocking) — all 5 DONE.** Unified permission spec + AXIOM
tool-call bypass; file-upload UI for CSV/Excel; `is_active`/role
integrity (both `resolve_identity()` and the per-request re-check);
invite email link fix; scheduled pipelines cluster. See `CLAUDE.md`'s
Status Table rows, each live-verified against the real running server.

**Dark theme redesign — STARTED, REMAINING.** Token change landed
(`tokens.css`, warm near-black neutral surfaces, measured 4.5:1+
contrast) but the commit's own required next step — a screenshot
verification pass across every screen, both themes — has not happened.
Two real, unrelated bugs were found and fixed while starting that pass
(both DONE): Dashboard's Chart.js trend colors silently never resolving
CSS custom properties in either theme; a pre-existing
`react/no-unescaped-entities` production-build failure on the Team
screen. **This is the most likely next-session starting point** — see
the note at the top of this section.

**Migration-drift dedicated session — REMAINING, own highest-risk slot,
not started.** `CLAUDE.md`'s Known-broken table carries two real,
related gaps that have never been addressed: the `incidentstatus`
Postgres enum migration doesn't match the Python-side enum (lowercase
3-value vs. uppercase 4-value); `pipeline_commits`/`pipeline_deployments`
have no Alembic migration creating them at all. Both trace back to the
same root cause documented in `CLAUDE.md`'s Gotchas: this dev DB's schema
was never actually created by Alembic — `alembic_version` doesn't exist,
`Base.metadata.create_all()` on backend startup is the real source of
truth here, and running `alembic upgrade head` against this DB fails
immediately (`DuplicateObject`). This is deliberately called out as its
own dedicated session, not a quick fix folded into something else —
reconciling the migration chain against the real live schema (likely via
`alembic stamp` at the right revision, per the Gotcha's own worked
example for the one migration that's already needed this) touches
every table in the app and deserves undivided attention, not a
tail-end-of-session pass.

**P1 (10 items) — all REMAINING, none started.** Centralized 402/403
handling in `lib/api.ts`; shared role-aware control component (replacing
the copy-pasted `canManage` pattern); shared delete-confirmation dialog;
promote Audit Log to a top-level `/audit` page + remove the dead
"Analytics" nav item; Catalog's Sync Metadata real per-source
pass/fail reporting; rename Quality's "Run Checks" to reflect its real
scope; Transforms' "Auto" language selector (implement or remove);
approval outcomes returning to the chat thread on reopen; remove the
notifications bell (**re-confirmed still hardcoded placeholder data**
during this session's shell audit — see `CLAUDE.md`'s Part 4 answers);
remove the decorative "Production" environment dropdown (**re-confirmed
still a no-op toast** during the same audit); wire "AXIOM Online" to the
real `GET /health/db` (**re-confirmed still fully decorative**); fix the
role-display `capitalize` bug on underscored role names. See
`FRONTEND_BUILD_PLAN.md`'s own P1 list above for full detail per item —
unchanged this session, just independently re-confirmed for 3 of the 12.

**P2 (small items) — 1 DONE this session, rest REMAINING.** "+ New Chat"
giving no feedback on an already-empty thread is **DONE** — turned out to
be a real race condition, not just missing feedback (see `CLAUDE.md`'s
"New Chat button race condition" row). Still open: "Attach a source…"'s
missing empty-state message on a zero-source tenant; "+ Save current
draft"'s missing disabled-state tooltip; Dashboard secondary-query
empty-state flash; no redirect for authed users hitting `/login`/`/signup`;
saved-prompts device-local labeling; the three different "Pending
Approvals" counts meaning different things; the orphan `PATCH
/cicd/incidents/{id}/resolve` endpoint (recommend deleting); missing
SQL-tab Explain button; Command Palette's placeholder text overpromising
"actions, pages, sources" when it only searches page names (**re-confirmed
navigation-only, not a stub**, during this session's shell audit); the
Sidebar's self-disclosing "Production" workspace selector.

**Known-broken rows still UNDECIDED (real gaps, not yet triaged
fix-vs-accept, per the note above)**: WebSocket chat auth (still the most
severe issue in the codebase — unauthenticated, though narrowed to
Viewer-tier tool access by the permission spec); removed/demoted members
keep access for up to the JWT TTL (60 min) after removal — real fix
directions already written up, not yet chosen between; `change_plan()`
allows unconditional downgrades with no usage check and no payment gate;
CI/CD webhook tenant spoofable if `GITHUB_WEBHOOK_SECRET` is unset;
`BusinessRules.create_rule()` can't create any of its own 8 supported
rule types; `QualityTestRunner` is a no-op stub (not wired into the real
check path, but would silently lie if anything ever called it);
`approval_executor.py`/`update_contract`'s no-op approval action are both
dead code, not gaps per se, but still undecided whether to delete or
wire up.

**ACCEPTED-FOR-LAUNCH (rationale already on record, not silently
carried forward)**: onboarding enforcement staying per-tenant/
first-responder-wins (explicit product decision, Phase 19 plan); invited
members skipping onboarding (correct behavior, not a gap); `ENABLE_
AUTONOMOUS_MODE`/`ENABLE_DESTRUCTIVE_ACTIONS`/`SYNC_DATABASE_URL` dead
config (harmless, no call sites); the freshness-checker duplicate-incident
issue and the CSV connector's cosmetic `rows_processed: 0` display bug
(both flagged, both low-severity, neither blocks anything real); the
Settings AI Model tab's hardcoded allowlist (explicit adjustment in the
original Phase 17 spec).

**DOMAIN-GATED (blocked on the user's side — see Outstanding items,
`CLAUDE.md`)**: real production deployment; Privacy Policy/Terms of
Service pages; Resend domain verification (blocks real invite/email-code
delivery to anyone but the account owner).

---

## Phase 19 plan (locked, 2026-07-22)

Produced from a full code-derived audit of the product (`dataops-agent/USER_MANUAL.md`,
built screen-by-screen against the actual frontend + backend code, not memory
of intent) plus the user's own live walkthrough of the seeded "Phase19
Walkthrough Co" tenant. Proposed, revised twice, and approved before any code
— see the manual's own findings for full detail per screen; this section is
the execution plan derived from them.

### Headline finding

The 5-role model (`services/rbac.py`'s `Role` enum) was real only for
approvals, team, settings, and billing — everywhere else (sources, pipelines,
quality rules, incidents, contracts, transform generation) any authenticated
role, including Viewer, could mutate freely. Root cause: each endpoint
hand-picked its own `require_role(...)` tuple ad hoc, with most endpoints
picking none at all. AXIOM's tool-calling path had **zero** role enforcement
of any kind — only `operation_mode` + a hardcoded risk tier gated it,
independent of the REST layer entirely, so a Viewer chatting with AXIOM could
have it execute actions the same Viewer would be 403'd on through the UI.

### Architecture (approved)

One capability map, two consumers — not a second rulebook in the agent:

- `services/rbac.py` gains `PERMISSIONS: dict[str, frozenset[Role]]`, keyed
  by `"<resource>.<action>"` (e.g. `"pipelines.trigger"`), and
  `has_permission(role, capability) -> bool`.
- `require_permission(capability)` (`api/v1/auth.py`, alongside the existing
  `require_role`/`enforce_quota` factories) replaces the ad hoc per-endpoint
  role tuples. **Dependency order matters**: `require_permission(...)` is
  declared before `enforce_quota(...)` on every endpoint carrying both, since
  FastAPI resolves dependencies in declared order and stops at the first
  failure — a blocked-by-role request never reaches the quota check, so a
  Viewer never sees "out of AI credits" when the real answer is "not
  allowed."
- `get_current_user()` gains exactly **one** additional DB query (`SELECT
  is_active, role FROM users WHERE id = :sub`), merged into the returned
  dict, `401` raised immediately if `is_active` is `False`. This applies to
  every authenticated request app-wide (not just permission-gated ones) and
  closes the JWT-persistence-after-removal gap. It stays a single query per
  request via FastAPI's default per-request dependency caching —
  `require_permission`/`enforce_quota`/every route handler all depend on the
  same `get_current_user` call, invoked once and reused; `has_permission()`
  itself is a pure in-memory dict lookup, no I/O.
- Every one of the 38 real AXIOM tools (`agent/tools/*.py`) gets a
  `TOOL_CAPABILITIES: dict[tool_name, capability]` entry. `agent_node`'s
  existing tool-call loop gets one new check — `has_permission(caller_role,
  TOOL_CAPABILITIES[tool.name])` — evaluated **before and independently of**
  the `operation_mode`/risk-tier approval gate. Role-blocked stays
  role-blocked regardless of Advisory/Assisted/Autonomous.
- **Fail-closed**: an unmapped tool is denied for every role. Enforced by a
  startup assertion (`assert set(ALL_TOOLS) <= set(TOOL_CAPABILITIES)`,
  fails boot) plus a test enumerating every registered tool.
- Read-only AXIOM tools (`list_data_sources`, `get_lineage`,
  `get_quality_report`, `list_open_incidents`, `get_system_health`,
  `get_audit_trail`, `get_pipeline_run_history`, `get_kpi_summary`,
  `get_cicd_status`, `preview_source_data`, `list_business_rules`,
  `detect_schema_drift`) map to a `view` capability granted to every role, so
  Viewer chat stays useful rather than refusing everything.

### Capability table (locked)

| Capability | Owner | Admin | Data Eng | Data Analyst | Viewer |
|---|---|---|---|---|---|
| View everything (read-only screens + `view`-mapped AXIOM tools) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Sources: create / edit | ✅ | ✅ | ✅ | ❌ | ❌ |
| Sources: sync / profile (incl. Catalog's Sync Metadata) | ✅ | ✅ | ✅ | ✅ | ❌ |
| Sources: delete | ✅ | ✅ | ✅ | ❌ | ❌ |
| Pipelines: create / edit / schedule | ✅ | ✅ | ✅ | ❌ | ❌ |
| Pipelines: trigger / pause / activate | ✅ | ✅ | ✅ | ✅ | ❌ |
| Pipelines: delete | ✅ | ✅ | ✅ | ❌ | ❌ |
| Quality rules: create / edit / run | ✅ | ✅ | ✅ | ✅ | ❌ |
| Quality rules: delete | ✅ | ✅ | ✅ | ❌ | ❌ |
| Transforms: generate / dry-run / preview / explain | ✅ | ✅ | ✅ | ✅ | ✅ |
| Transforms: execute (real run/sql, run/pandas) | ✅ | ✅ | ✅ | ✅ | ❌ |
| Incidents: log | ✅ | ✅ | ✅ | ✅ | ✅ |
| Incidents: resolve | ✅ | ✅ | ✅ | ✅ | ❌ |
| Contracts: validate | ✅ | ✅ | ✅ | ✅ | ❌ |
| Contracts: create | ✅ | ✅ | ✅ | ✅ | ❌ |
| Chat with AXIOM (send a message) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Approvals, CI/CD incident resolve | ✅ | ✅ | ❌ | ❌ | ❌ |
| Team invite / role-change / remove | ✅ | ✅ | ❌ | ❌ | ❌ |
| Settings / API keys / plan change | ✅ | ✅ | ❌ | ❌ | ❌ |

Transforms:execute confirmed safe for Data Analyst before locking this table
— both `SqlRunner` (keyword-blocklist + first-token SELECT/WITH/EXPLAIN
check) and `PythonRunner` (AST-sandboxed, no DB connection object ever
exposed to the exec namespace, no write-back code path exists at all) are
structurally read-only; neither can perform arbitrary DDL/DML. Caveat kept on
record: `SqlRunner`'s check is a keyword blocklist, not a formal SQL parser,
and runs under the same stored credentials as ordinary sync, not a separate
read-only DB role.

Explicit, accepted tradeoff: Viewer keeps `view` + chat, so a Viewer can
still spend real tenant AI credits via transform-generation/chat even though
they can't execute anything. Recorded here, not left implicit.

### Verification (required before this is considered done)

1. Role×capability matrix test — 5 roles × every capability row above,
   scripted against real endpoints, asserting allow/deny. No LLM.
2. **Cross-consumer regression guard** (the actual proof both consumers
   share one map, not two hardcoded copies that happen to agree today):
   `test_viewer_blocked_from_pipeline_trigger_both_consumers` — asserts a
   Viewer's `POST /pipelines/{id}/trigger` returns `403`, **and** a direct
   call to the `run_pipeline` tool-dispatch function (synthetic Viewer role)
   is also denied, both checked against the same `PERMISSIONS["pipelines.trigger"]`
   entry.
3. Agent-side gate tested at the tool-dispatch function level with a
   synthetic role passed directly — not through real AXIOM conversations
   (avoids burning Gemini's daily cap on routine gate checks).
4. Fail-closed enumeration test (above).

### P0 (launch-blocking, this phase)

1. **Done, fully live-verified (2026-07-22).** Unified permission spec +
   AXIOM tool-call bypass (above) — see `CLAUDE.md`'s new "Unified
   permission spec" Status Table row for the complete implementation,
   241-test regression detail, and the real-server live-verification
   (including the headline proof: a Viewer promoted to Data Engineer via a
   direct DB write, with no new JWT issued, had their existing token's
   *next request* immediately reflect the new capability — and the same
   still-valid token was immediately rejected the moment the user was
   deactivated). Item 3(b) below (the `get_current_user()` per-request
   `is_active`/role re-check) shipped as part of this same work, not
   separately.
2. **Done, fully live-verified (2026-07-22).** File-upload UI for CSV/Excel
   in the Sources "Add Source" modal — `frontend/src/app/(app)/sources/page.tsx`
   now shows a real `<input type="file">` (accept scoped to `.csv` or
   `.xlsx,.xls` per selected type) instead of the raw JSON-textarea path
   for `csv`/`excel` only; every other source type is unchanged. New
   `uploadAndRegisterSource()` (`lib/api.ts`) posts real multipart
   `FormData` to `/uploads/register` (a dedicated fetch call, not routed
   through the shared `request()` helper, since that hardcodes
   `Content-Type: application/json` which would strip the multipart
   boundary). Selecting a file auto-fills the Name field from the
   filename (editable, optional — the backend already defaults to
   `file.filename` if omitted). **Found and fixed a real gap while
   wiring this up**: `POST /uploads/register` creates a real
   `DataSource` — the same action `POST /sources/` gates behind
   `sources.create` — but was never migrated in the original Phase 19
   permission-spec pass (`uploads.py` wasn't in that file list). Added
   `Depends(require_permission("sources.create"))` +
   `Depends(enforce_quota("data_sources"))` in the same order/pattern as
   `sources.py`'s `create_source`. New regression test
   (`test_upload_register_requires_sources_create_permission`,
   `test_uploads.py`) plus live-verification against the real running
   server: a real CSV upload as Owner succeeded (`200`, real
   `source_id`, real 2-row ingest with real column names); the same
   user demoted to Viewer via direct DB write (no new token) got a real
   `403` on the identical upload. Live-verified in a real Playwright
   browser too: CSV/Excel show the file input (not the JSON textarea);
   switching to `postgres` reverts to the JSON config path with the
   file input hidden; a real upload produces a real success toast and
   the new source appears in the table. `npx tsc --noEmit` clean. Full
   backend suite: 242 passed.
3. **Done.** `is_active`/role integrity: (a) `resolve_identity()`
   (email-code/Google login) gains the same `is_active` filter
   `resolve_password_login()` already has — **done, fully live-verified
   (2026-07-22)**, see `CLAUDE.md`'s "`resolve_identity()` missing
   `is_active` filter" Status Table row; (b) `get_current_user()`'s
   per-request re-check, now re-reading both `is_active` and `role`, not
   just `is_active`, since a demoted user must lose their old capabilities
   immediately under the new permission model, not just an active/inactive
   user losing all access — **done, shipped with item 1 above, see
   `CLAUDE.md`**.
4. **Done, fully live-verified (2026-07-22).** Fixed `_invite_link()`'s
   `/accept-invite` → `/invite/accept` — re-confirmed via a fresh grep that
   it's still the only backend-generated frontend link in the codebase, no
   pattern to hunt elsewhere. New unit test asserting the function's exact
   output (every existing integration test mocks the function that calls
   it, so nothing had ever exercised this string before). Live-verified
   with a real Resend-delivered invite email whose real body now contains
   the corrected link, and that exact link loaded in a real browser
   correctly resolved to the real tenant/role instead of a 404. See
   `CLAUDE.md`'s "Invite email link pointed at a 404" Status Table row.
5. **Done, fully live-verified (2026-07-22).** Scheduled pipelines: the
   originally-scoped arg-mismatch bug turned out to be the smaller half of
   a bigger finding — the entire dynamic per-pipeline scheduling mechanism
   (`Scheduler.register()`/`sync_all()`) was never actually called from
   anywhere in the running app, and even a correctly-wired call couldn't
   have worked, since it mutates a `beat_schedule` dict that isn't shared
   between the `backend` and `celery_beat` processes. Replaced with a real,
   live static-polling beat task (`check_scheduled_pipelines()`, every 60s,
   same pattern as the already-working `check_all_freshness()`) that polls
   active scheduled pipelines against the DB directly and fires due ones via
   `croniter.match()`. Added save-time cron validation (`croniter.is_valid()`,
   all 3 write paths) and real next-run/last-run visibility (new "Next /
   Last Run" column, Pipelines screen). **Verified live exactly per this
   item's own gate**: a real `* * * * *` pipeline produced 3 real,
   correctly-timed runs one minute apart, no duplicates, confirmed via the
   real run-history endpoint and a real Playwright DOM check of the UI. See
   `CLAUDE.md`'s "Scheduled pipelines cluster" Status Table row and its new
   Gotchas (the cross-process `beat_schedule` mutation issue, and a
   confirmed-pre-existing/benign asyncio warning found during verification).

### P1

6. Centralized 402/403 handling in `lib/api.ts`'s shared mutation error
   path — 403 → real permission message, 402 → quota message linking
   `/billing`.
7. Shared role-aware control component reading the same `PERMISSIONS` map
   (mirrored client-side), replacing the copy-pasted `canManage` pattern —
   covers Sources, Pipelines, Quality, Incidents, Governance, CI/CD,
   Approvals, and Catalog's Sync Metadata (a fan-out of `sources.profile`).
8. Shared delete-confirmation dialog (sources, pipelines, quality rules, API
   key revoke, member removal).
9. Promote Governance's real Audit Log tab to a top-level `/audit` page;
   remove the "Analytics" nav item entirely (no plan behind it, Dashboard
   already covers the ground).
10. Catalog's "Sync Metadata": real per-source pass/fail reporting instead
    of always claiming "complete."
11. Rename Quality's "Run Checks" to reflect it re-runs every rule on the
    whole pipeline, not just the clicked row.
12. Transforms' "Auto" language selector: implement real detection or
    remove the option (currently identical to picking "SQL").
13. Approval outcomes never returning to the chat thread — cheap-version fix
    approved: resolve each blocked tool call's *current* approval status at
    session-history read time (a join against `ApprovalRequest` inside
    `GET /chat/sessions/{id}/history`, no push infrastructure) so a
    reopened conversation shows approved/rejected instead of a frozen
    "Needs approval."
14. Remove the notifications bell entirely this phase — confirmed hardcoded
    placeholder data with an unconditionally-rendered unread dot (a real
    "nothing faked" violation in the global topbar). A real notification
    system is its own feature; not half-wiring it here.
15. Remove the "Production" environment dropdown — confirmed decorative
    (toast-only, no real effect), implies staging/prod environments that
    don't exist.
16. Wire "AXIOM Online" to the real `GET /health/db` (checks actual Postgres
    connectivity, unlike the trivial `GET /health`), polled every 30–60s,
    dot + label reflect the real result (including a real "AXIOM Offline").
17. Fix role display: both Sidebar footer and Topbar account dropdown apply
    `text-transform: capitalize` directly to the raw role string, producing
    "Data_engineer" for any underscored role (CSS `capitalize` doesn't treat
    `_` as a word boundary) — confirmed live with a real `data_engineer`
    JWT. Extract Team screen's existing `roleLabel()` lookup into a shared
    helper, use it everywhere a role is displayed.

### P2 (fix if room, else explicit accept)

Dashboard secondary-query empty-state flash; no redirect for authed users
hitting `/login`/`/signup`; label saved prompts as device-local; label the
three different "Pending Approvals" counts (Dashboard/CI-CD/Approvals count
different things); orphan `PATCH /cicd/incidents/{id}/resolve` (no frontend
caller anywhere — recommend deleting the dead endpoint); missing SQL-tab
Explain button; Command Palette's placeholder text overpromising "actions,
pages, sources" when it only searches page names (real navigation, cosmetic
copy mismatch only); Sidebar's self-disclosing "Production" workspace
selector (lower severity — already admits "coming in Phase 15" via its own
toast).

**Chat findings** — "+ New Chat" **[RESOLVED: Phase 19 polish session]**:
this was originally diagnosed as missing-feedback only, but a deeper live
investigation found a real race condition, not just a UX gap — see
`CLAUDE.md`'s "New Chat button race condition" Status Table row for the
full fix and live-verification detail. Remaining, still-real
missing-feedback items (own sub-items, small, can ride with P1's
shared-component work): "Attach a source…" works correctly with real
sources but gives no empty-state message on a zero-source tenant; "+ Save
current draft"'s full save→recall→remove cycle works correctly, the
disabled state just has no tooltip explaining why.

**Dropped from the list**: "invited members skip onboarding" — the profile
is per-tenant and the inviting tenant has already completed it; skipping is
correct, not a gap. Documented as intended behavior in
`dataops-agent/USER_MANUAL.md`, not tracked as a fix item.

### Product decisions (decided)

- **Duplicate-email signup**: change it. `register()` will look up the
  email before creating a tenant; if one or more accounts already exist,
  present an explicit choice (log into an existing workspace, or
  deliberately create a new one) requiring confirmation, instead of silently
  creating a second orphan tenant and informing after the fact.
- **Onboarding enforcement**: leave unenforced. Documented as intended,
  per-tenant, first-responder-wins behavior.

### Dark theme legibility (own task, own commits — sequenced AFTER the permission work lands and is fully verified, never in parallel with it)

Measured WCAG contrast (script, not visual judgment) found the current
bg/surface relationship (`--bg` black page, `--surface` `#0F2440` elevated
cards) is already sound — 13.99:1 primary text, 8.67:1 secondary text
against `--surface`, both excellent. **No swap of that relationship is
planned.** The one real, isolated, measured failure is `--text-muted`:

| Token | Before | After | Contrast before (surface / surface-hover) | Contrast after |
|---|---|---|---|---|
| `--text-muted` (dark mode) | `#7A8CA3` | `#9FB4CB` | 4.54:1 / **3.33:1 (fails AA)** | 7.33:1 / 5.38:1 (passes with margin) |

One token, two locations in `tokens.css` (`:root[data-theme="dark"]` and the
mirrored `@media (prefers-color-scheme: dark)` block). Verification: measured
contrast ratios (not visual judgment) for the new value plus fresh
dark-mode screenshots of all 24 screens — this explicitly invalidates every
dark-mode screenshot taken during Phases 1–18.

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
- **New, user-actionable, grouped with the domain-purchase cluster: Privacy
  Policy and Terms of Service pages.** The landing page (Phase 18) links to real
  `/login`/`/signup`, but neither auth flow requires accepting a Privacy Policy
  or Terms of Service, and no such pages exist anywhere in this app. Required
  before any real production signup traffic — not before this session's local
  build-and-verify work, and not something to write speculative legal copy for
  without the user's involvement. Explicitly in scope for Phase 19's
  launch-readiness partition (see the "Phase 19 note" above).

---

## Where a fresh session should start

1. `CLAUDE.md` (repo root) — backend state, workflow rules, Gotchas
2. This file (`FRONTEND_BUILD_PLAN.md`, repo root) — what's being built and in what order
3. `dataops-agent/DESIGN_TOKENS.md` — locked palette/typography values
4. `dataops-agent/frontend/wunomo-ai MASTER DESIGN.html` — the design source of truth
   for layout/components/screens (palette/fonts in it are superseded by the above)
