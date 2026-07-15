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
