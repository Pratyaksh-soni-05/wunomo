# Wunomo AI / AXIOM — User Manual & Flow Reference

**This is an audit artifact, not marketing material.** Every statement below is
derived from reading the actual frontend page/component code, `lib/api.ts`, and
the backend endpoint each screen calls — not from memory of what was intended or
planned. Where behavior could not be confirmed by reading code alone, it is
marked **UNVERIFIED — needs live check** rather than guessed. The product's real
flaws (stubs, Coming Soon items, open Known-broken gaps) are documented inline,
cross-referenced to `CLAUDE.md`'s Known-broken table where applicable.

Source files read to produce this document are named per section so any claim
can be re-checked against the code directly.

Status: **in progress, built screen-group by screen-group** and committed after
each group is written. See the bottom of this file for which groups are done.

---

## Document conventions

- **Route path and file** — the Next.js route and the exact file implementing it.
- **Purpose** — one to two sentences, what the screen is for.
- **How to reach it** — every real navigation path into the screen (nav item,
  link, redirect, or "not linked anywhere — direct URL / external link only").
- **Role visibility** — what Owner / Admin / Data Engineer / Data Analyst /
  Viewer each see. Screens with no role distinction say so explicitly.
- **Interactive elements** — every button/toggle/input/tab/table action/modal,
  each stating: label, what it does, the exact API call (method + path), what
  happens on success, what happens on failure, and any confirmation/guard logic.
- **Empty states** — what renders with no data, and why.
- **Known issues** — anything affecting this screen from `CLAUDE.md`'s
  Known-broken table, or a new finding surfaced while writing this document
  (marked **NEW FINDING**, not yet added to `CLAUDE.md` — logged here, not fixed,
  per this document's own no-fix-while-writing rule).

---

## Screens — Group 1: Landing & Authentication

*Files read for this group: `frontend/src/app/page.tsx`, `frontend/src/app/login/page.tsx`,
`frontend/src/app/signup/page.tsx`, `frontend/src/app/onboarding/page.tsx`,
`frontend/src/app/api/auth/callback/google/page.tsx`, `frontend/src/app/invite/accept/page.tsx`,
`frontend/src/components/auth/AuthShell.tsx`, `frontend/src/components/auth/WorkspacePicker.tsx`,
`frontend/src/app/layout.tsx`, `frontend/src/lib/api.ts`, `backend/api/v1/auth.py`,
`backend/api/v1/onboarding.py`, `backend/api/v1/team.py`, `backend/services/team_service.py`.*

### 1. Landing page — `/`

**File:** `frontend/src/app/page.tsx`

**Purpose:** Public marketing page — introduces "Wunomo AI" as an AI-workforce
platform, shows the 6-tile employee roster (AXIOM real, 5 locked), and drives
signups.

**How to reach it:** The root URL. Not part of the authenticated `(app)` shell —
no auth guard. Reachable by anyone, logged in or not.

**Role visibility:** No role distinction. The only branching is authenticated
vs. not (`useIsAuthed()`, a `useEffect`-only client-side check of whether a
token exists in `localStorage` — deliberately does not check whether the token
is still valid/unexpired, only whether one is present. It also does not check
role at all — an Owner, Admin, Data Engineer, Data Analyst, or Viewer see an
identical logged-in state on this page).

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Nav "Log in" (shown only when logged out) | Link | Navigates to `/login` | — | — |
| Nav "Get Started" (shown only when logged out) | Link | Navigates to `/signup` | — | — |
| Nav "Go to Dashboard" (shown only when logged in) | Link | Navigates to `/dashboard` | — | — |
| Hero "Get Started" button | Link | Navigates to `/signup` | — | — |
| Hero "Log in" button | Link | Navigates to `/login` | — | — |
| AXIOM roster tile CTA, logged in | Link, label "Open AXIOM →" | Navigates to `/chat` | — | — |
| AXIOM roster tile CTA, logged out | Link, label "Get Started with AXIOM" | Navigates to `/signup` | — | — |
| 5 locked roster tiles (LEDGER/DEPLOY/INSIGHT/SENTINEL/PULSE) | Non-interactive — "Coming Soon" badge only, no button | — | — | — |
| Final-CTA "Get Started" | Link | Navigates to `/signup` | — | — |
| Footer "Log in" / "Get Started" links | Link | Navigate to `/login` / `/signup` | — | — |

No element on this page makes a backend API call — the only "data fetch" is
the local `getToken()` read from `localStorage`.

**Empty states:** None — the page is entirely static content (roster data comes
from a local module, `lib/employees.ts`, not an API).

**Known issues:**
- **App-wide, not specific to this page:** a React hydration-mismatch console
  warning fires on any page (including this one) when the stored theme is
  `"dark"` and the page does a full reload — caused by the root layout's
  synchronous pre-paint theme script writing `data-theme` before React
  hydrates, with no matching server-rendered attribute. Cosmetic only (page
  still renders correctly). See `CLAUDE.md` Gotchas, not fixed as of this
  writing.
- `useIsAuthed()` only checks *token presence*, not validity — a user with an
  expired-but-still-`localStorage`-present token sees the logged-in nav/CTA
  state on this page even though the token itself would be rejected on any
  real API call. Landing page itself makes no API calls, so nothing breaks
  visibly here; the first authenticated page they click into (e.g. `/chat` via
  "Open AXIOM") would trigger the centralized 401-handling redirect back to
  `/login?expired=1`. **NEW FINDING**, not previously documented — low
  severity (self-correcting on first real API call), not fixed here.

---

### 2. Login — `/login`

**File:** `frontend/src/app/login/page.tsx`, using `AuthShell` + `WorkspacePicker`.

**Purpose:** Authenticate an existing user via one of three methods: password,
one-time email code, or Google OAuth.

**How to reach it:**
- Nav/footer "Log in" links from the landing page.
- Signup page's "Already have a workspace? Log in" footer link.
- Automatic redirect from any `(app)`-group route when no token is present
  (`(app)/layout.tsx`'s client-side guard).
- Automatic redirect (with a `?expired=1` query param) from `lib/api.ts`'s
  centralized 401 handler, whenever an authenticated request gets a real 401
  back (expired/invalid token). On mount, this page checks for that param,
  shows a "Session expired — please log in again." toast, and strips the
  param from the URL.
- Direct navigation. **Not** guarded against an already-logged-in user — a
  user with a valid token can still open `/login` directly and will see the
  login form rendered normally (no auto-redirect to `/dashboard`).

**Role visibility:** N/A — pre-authentication, no role exists yet.

**Interactive elements:**

*Password mode (default):*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Email / Password inputs + "Log in" button | Submit | `POST /api/v1/auth/login` (form-encoded `username`/`password`) | Exactly one tenant matches this email+password → JWT issued, session saved (`localStorage`), then `GET /api/v1/onboarding/` is checked and the user is routed to `/dashboard` (if `completed: true`) or `/onboarding` (if not). More than one tenant matches → no token issued yet; `WorkspacePicker` modal opens with the list of matching workspaces. | Wrong password or unknown email → generic "Invalid credentials" toast in both cases (no enumeration — backend returns the same `400` either way). |
| "Email me a code instead" | Client-side only | Switches to code-request mode | — | — |

*Code-request mode:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Email input + "Send code" | Submit | `POST /api/v1/auth/email-code/request` `{email}` | `{status:"sent"}` → success toast, switches to code-verify mode, starts a 60-second resend cooldown. Backend always returns "sent" regardless of whether the email has an account (enumeration-safety by design). | `{status:"rate_limited"}` → warning toast, stays on this screen. |
| "Back to password" | Client-side only | Switches back to password mode | — | — |

*Code-verify mode:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| 6-digit code input + "Verify & log in" | Submit | `POST /api/v1/auth/email-code/verify` `{email, code}` | Single tenant match → JWT issued, same completion routing as password login. Multiple matches → `WorkspacePicker` opens; because the code is single-use and already consumed by this call, finalizing the pick calls a *different* endpoint (`POST /api/v1/auth/resolve-workspace` with a short-lived `resolution_token`), not a second code submission. Zero matches (`no_account`) → warning toast "No workspace found for this email. Sign up instead." — login's code-verify never auto-creates a tenant (unlike signup's, see below). | Wrong/expired/already-used code → generic "Invalid or expired code." toast (backend collapses all three into the same `400`). |
| "Back to password" | Client-side only | Switches back to password mode | — | — |
| "Resend code" (disabled during the 60s cooldown, shows a live countdown) | Submit | Re-calls `POST /api/v1/auth/email-code/request` | Same as the initial send | Same as the initial send |

*Common to all modes:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "Continue with Google" | Click | `GET /api/v1/auth/google/login-url`, then a full-page redirect (`window.location.href`) to the returned real Google OAuth consent URL | Browser leaves the app and lands on Google's real consent screen | — |
| "Sign up" footer link | Link | Navigates to `/signup` | — | — |
| `WorkspacePicker` modal option click | Click | Depending on which flow opened it: either a second `POST /api/v1/auth/login` (with the chosen `tenant_id`, password path) or `POST /api/v1/auth/resolve-workspace` (code/Google path) | JWT issued, completes login/routing as above | — |

**Empty states:** N/A — this is a form, not a data list.

**Known issues:**
- Password login enforces `User.is_active` (a removed/deactivated team member's
  password login correctly fails immediately — Phase 15 fix). **Email-code and
  Google login do NOT check `is_active` at all** — a removed/deactivated member
  can still complete a fresh login via either of those two methods even after
  being removed from the team. Documented in `CLAUDE.md`'s Gotchas
  ("`User.is_active` is only enforced on the password login path...") — not yet
  fixed.
- More broadly, any successful login (any method) issues a JWT that stays
  valid for its full TTL (`JWT_EXPIRE_MINUTES=60`) regardless of later role
  changes or removal — see `CLAUDE.md` Known-broken, "Removed/demoted team
  members keep full access for up to the JWT TTL."

---

### 3. Signup — `/signup`

**File:** `frontend/src/app/signup/page.tsx`, using `AuthShell` + `WorkspacePicker`.

**Purpose:** Create a brand-new workspace (tenant) and its first user (role
`owner`), via password, email-code, or Google.

**How to reach it:** Nav/hero/tile/final-CTA links from the landing page,
login page's "Sign up" footer link, direct navigation. Not an auto-redirect
target from anywhere (unauthenticated users hitting a protected route are sent
to `/login`, not here). Not guarded against an already-logged-in visitor —
same as `/login`, a valid session doesn't redirect the user away from this page.

**Role visibility:** N/A.

**Interactive elements:**

*Form mode (default):*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Full name / Email / Workspace name / Password inputs + "Create account" | Submit | `POST /api/v1/auth/register` `{email, password, full_name, tenant_name}` | **Unconditionally creates a new tenant + owner user** — there is no check that blocks or asks-before-creating on a duplicate email. The response also includes `existing_workspaces` (a non-blocking, informational lookup of any *other* tenants already registered under this email). If that list is non-empty, the new workspace has *already been created* by this point, and the UI pauses on a nudge screen (below) instead of auto-routing forward. If empty, proceeds straight through to the same "check onboarding, route to `/dashboard` or `/onboarding`" logic as login. | Duplicate constraint or validation error → toast with the backend's detail message, or generic "Registration failed." |
| "Verify by code instead of a password" | Client-side, guarded | Requires Email + Workspace name to already be filled (else a warning toast "Fill in your email and workspace name first." and no mode switch); otherwise switches to code-request mode | — | — |

*Nudge screen (shown only when `register()`'s response included existing workspaces):*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Banner text | — | Informational only: "Heads up — this email already has N workspace(s) (names…). Your new workspace was still created." | — | — |
| "Continue to your new workspace" | Click | No new API call — completes routing using the token/tenant/user IDs already returned by the earlier `register()` call | Routes to `/dashboard` or `/onboarding` per the already-fetched onboarding status | — |
| "Log in to an existing workspace instead" | Link | Navigates to `/login` (the just-created new tenant is **not** deleted or undone by choosing this — it simply isn't logged into right now) | — | — |

*Code-request / code-verify modes:* same UI shape as Login's, with two real
differences:
- The verify call is `POST /api/v1/auth/email-code/verify` `{email, code, new_tenant_name: <workspace name>}` — passing `new_tenant_name` means a `no_account` backend result (`status: "none"`) auto-creates a fresh tenant instead of the login flow's "no workspace found" message. The only way this page's own "Something went wrong creating your workspace. Try again." danger-toast path fires is if the backend somehow still returns `no_account` despite a name being sent — effectively an edge case, not the normal path.
- Everything else (resend cooldown, "Back", `WorkspacePicker`-via-`resolution_token` for multi-tenant matches) is identical to Login's.

*Common:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "Continue with Google" | Click | If a Workspace name was typed, it's stashed in `sessionStorage` (`axiom_pending_tenant_name`) first, then `GET /api/v1/auth/google/login-url` + redirect to Google, same as Login | The Google callback page reads and clears that stashed name to create a fresh tenant if needed | — |
| "Log in" footer link | Link | Navigates to `/login` | — | — |

**Empty states:** N/A.

**Known issues:**
- The duplicate-email behavior described above ("creates first, informs after,
  never asks before") is the **actual, intended, shipped fix** for the
  historical "`register()` never checks for an existing email" bug — see
  `CLAUDE.md` Known-broken, now marked `[RESOLVED: Phase 3/6]`. It is
  documented here as current behavior, not as an open defect: a real duplicate
  signup **does** produce a second, independent, real tenant every time — the
  nudge is advisory, not a block.

---

### 4. Google OAuth callback — `/api/auth/callback/google`

**File:** `frontend/src/app/api/auth/callback/google/page.tsx`

**Purpose:** Receives Google's redirect (`code` + `state` query params) after
the user approves consent on Google's real screen, and completes the
login/signup started from either `/login` or `/signup`. Despite the `/api/...`
path, this is a plain client-rendered Next.js page (not a Route Handler) — it
runs in the browser like any other route.

**How to reach it:** Never navigated to directly. It is the registered OAuth
`redirect_uri` Google sends the browser back to after "Continue with Google"
on `/login` or `/signup`.

**Role visibility:** N/A.

**Interactive elements:** No buttons on the success path — the exchange runs
automatically on mount (guarded by a `ran` ref so it only fires once, since
the authorization `code` and `state` are both single-use and a double-fire —
e.g. under React re-render — would consume them incorrectly on the second
attempt).

| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (automatic, on mount) | — | `POST /api/v1/auth/google/callback` `{code, state, new_tenant_name?}` (the `new_tenant_name` is read from `sessionStorage` if the Signup page set it, then immediately cleared) | Single tenant match → JWT issued, routes to `/dashboard`/`/onboarding` same as other methods. Multiple matches → `WorkspacePicker` opens, finalized via `POST /api/v1/auth/resolve-workspace` (Google's code+state are already consumed by this point, same reasoning as email-code). No existing account and no `new_tenant_name` was set (i.e. came from Login's Google button, not Signup's) → inline error: "No workspace found for this Google account. Sign up first, then link Google from there." | Missing `code`/`state` in the URL → inline error "Missing authorization code from Google." Invalid/expired `state`, a failed token exchange, or ID-token verification failure → inline generic error "Google sign-in failed. Please try again." A `403 blocked_unverified` response (email already has a password account and Google's own `email_verified` claim is `false`) → the real backend detail message is shown verbatim, telling the user to log in with their password instead. |
| "Back to login" link (shown alongside any error state) | Link | Navigates to `/login` | — | — |
| `WorkspacePicker` modal | Click | `POST /api/v1/auth/resolve-workspace` | Completes login, routes onward | — |

**Empty states:** While waiting for the exchange to complete, shows a
"Finishing Google sign-in…" message with two skeleton placeholder bars.

**Known issues:** None open. A real clock-skew bug ("Token used too early",
caused by a Docker/WSL2 container clock a second or two behind Google's) was
found and fixed in an earlier session (`clock_skew_in_seconds=10` added to the
token verification call) — historical only, see `CLAUDE.md` Gotchas.

---

### 5. Onboarding — `/onboarding`

**File:** `frontend/src/app/onboarding/page.tsx`

**Purpose:** A 4-step profile questionnaire (role, industry, company size, use
cases + optional data stack) collected once per **tenant** (not per user).

**How to reach it:** Automatic redirect immediately after a successful
password/email-code/Google login or signup, whenever
`GET /api/v1/onboarding/` reports `completed: false`. **Not** part of the
`(app)` shell (no sidebar/topbar) and not linked from anywhere inside it. If a
user whose tenant has already completed onboarding navigates here directly,
the page's own mount check redirects them straight to `/dashboard`. If no
token is present at all, redirects to `/login`.

**Role visibility:** No role distinction is enforced in the code — any
authenticated user in a tenant that hasn't completed onboarding can fill this
in (the underlying `OnboardingProfile` row is one-per-tenant, not one-per-user,
so whoever gets here first effectively answers on behalf of the tenant).

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Step 1 — role chips (6 single-select options) | Click | Client-side only, no API call | Enables "Next" | — |
| Step 2 — industry free-text input | Type | Client-side only | Enables "Next" once non-empty | — |
| Step 3 — company size chips (5 single-select options) | Click | Client-side only | Enables "Next" | — |
| Step 4 — use-case chips (6 options, multi-select, at least 1 required) | Click | Client-side only | Enables "Finish" once ≥1 selected | — |
| Step 4 — data stack chips (10 options, multi-select, explicitly optional) | Click | Client-side only | — | — |
| "Back" (disabled on step 1) | Click | Client-side only | Steps back one | — |
| "Next" (steps 1–3) | Click | Client-side only | Advances one step | Disabled until the current step's required field is filled |
| "Finish" (step 4) | Click | `POST /api/v1/onboarding/` `{role, industry, company_size, use_cases, data_stack}` — upserts the tenant's one profile row | Routes to `/dashboard` | Danger toast "Couldn't save your answers. Try again." — stays on step 4, nothing is cleared |

**Empty states:** N/A — a linear wizard.

**Known issues:**
- **NEW FINDING**, not previously documented: a teammate who joins via
  `/invite/accept` is routed **straight to `/dashboard`**, never through
  `/onboarding` at all — `invite/accept/page.tsx`'s success handler calls
  `saveSession()` then `router.push("/dashboard")` directly, unlike every other
  entry path (password/email-code/Google login and signup), which all call
  `GET /api/v1/onboarding/` first and route to `/onboarding` if incomplete.
  In practice this is usually harmless (the inviting tenant has almost always
  already completed onboarding), but it means an invited member is never
  shown the onboarding questionnaire even in a tenant that hasn't completed
  it — not fixed here, logged only.
- Onboarding completion is **not enforced** anywhere as a hard gate — nothing
  in `(app)/layout.tsx`'s guard checks onboarding status, only token presence.
  A user can navigate directly to `/dashboard` or any other app URL and use
  the product fully without ever completing onboarding; the redirect is purely
  a default first-landing behavior, not an access control.

---

### 6. Invite accept — `/invite/accept?token=...`

**File:** `frontend/src/app/invite/accept/page.tsx`

**Purpose:** Public page for a newly-invited teammate to set a password and
join the inviting tenant, with the role locked at invite-creation time.

**How to reach it:** Only via a raw invite link containing `?token=`. In
practice, two real sources of that link exist today: (1) the real emailed
invite (see Known issues below — the emailed link currently points at the
wrong path), or (2) the `invite_link_token` returned directly in the
`POST /api/v1/team/invites` response and surfaced in the Team screen's invite
modal as a manual-share fallback (since Resend is sandboxed — see Outstanding
items). Not linked from anywhere else in the app; outside both the `(app)`
group and the `AuthShell` login/signup pages.

**Role visibility:** N/A — public, pre-auth.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (automatic, on mount) | — | `GET /api/v1/team/invites/verify?token=...` | Populates `{email, role, tenant_name}`, shown above the form | Any failure (unknown token, expired, already-accepted, or revoked — the backend's `get_invite_by_token()` collapses all of these into the same "not found" response, so the frontend genuinely cannot and does not distinguish them) → "This invite is invalid, expired, or has already been used." + "Back to login" link |
| Email field | — | Pre-filled from the invite, **disabled** — not editable (the invite is email-locked) | — | — |
| Full name field | Type | Optional | — | — |
| Password field | Type | Required | — | — |
| "Accept invite & join" (disabled while submitting or while password is empty) | Submit | `POST /api/v1/team/invites/accept` `{token, password, full_name}` — `tenant_id` and `role` come from the invite record itself, never from this request body | Creates a real `User` row in the *inviting* tenant with the role locked at invite time; session saved; routes straight to `/dashboard` (see the Onboarding section above — this path skips onboarding entirely) | Danger toast with the backend's detail message (e.g., "This email is already a member of this workspace") or a generic "Failed to accept invite" — the invite record itself is left `pending` on this specific failure (email-already-member), so a retry with different circumstances, or an admin revoking it, both still work correctly |

**Empty states:** The loading state (while `verify` is in flight) shows two
skeleton placeholder bars instead of the form.

**Known issues:**
- **NEW FINDING, real and current, not in `CLAUDE.md` today:** the backend's
  own invite-email builder generates the link at the wrong path.
  `services/team_service.py`'s `_invite_link()` builds
  `{base}/accept-invite?token={token}` (singular, hyphenated), but the real
  frontend route is `/invite/accept?token=...` (this page, under a nested
  `invite/` folder). Any real invite email delivered by Resend today contains
  a link that would 404 in the frontend — the invite still works correctly if
  the recipient is handed the raw `invite_link_token` some other way (e.g. the
  Team screen's create-invite response, which is how this project's own live
  verification worked around it), but the emailed link itself is broken. Not
  fixed here, per this document's own rule — logged for the Phase 19 triage.

---

## Screens — Group 2: Dashboard, Sources, Catalog, Pipelines

*Files read for this group: `frontend/src/app/(app)/layout.tsx`,
`frontend/src/app/(app)/dashboard/page.tsx`,
`frontend/src/components/dashboard/{KpiCard,HealthBanner,TrendCharts,RecentRunsCard,ApprovalsCard,AxiomActivityCard}.tsx`,
`frontend/src/app/(app)/sources/page.tsx`, `frontend/src/app/(app)/catalog/page.tsx`,
`frontend/src/app/(app)/pipelines/page.tsx`, `frontend/src/lib/api.ts`,
`backend/api/v1/{pipelines,sources,quality,approvals,transformations}.py` (grepped for
`require_role`/`enforce_quota` across all of `api/v1/*.py` to get exact role-gating
per endpoint, not assumed from `CLAUDE.md` prose).*

**Shared app-shell context (applies to every screen from here on):** every
route under the `(app)` route group is wrapped by `frontend/src/app/(app)/layout.tsx`,
which (1) redirects to `/login` if no token is present in `localStorage` — this
is the **only** access check at the shell level, it does not check onboarding
completion or role; (2) on mount, fetches `GET /api/v1/auth/me` and reconciles
the server-stored theme over whatever `localStorage`'s pre-paint script already
applied; (3) renders `Sidebar` + `Topbar` + `AxiomFab` + `CommandPalette`
(`Ctrl+K`) around the page content. Individual screens are responsible for
their own role-based UI gating — the shell itself does not enforce or hide
anything by role.

### 7. Dashboard — `/dashboard`

**File:** `frontend/src/app/(app)/dashboard/page.tsx` +
`frontend/src/components/dashboard/*.tsx`

**Purpose:** Tenant-wide overview — 7 KPI cards, an open-incident banner, two
trend charts, recent pipeline runs, pending approvals, and recent AXIOM chat
activity.

**How to reach it:** Sidebar's first nav item ("Dashboard", no section label).
Default post-login landing point once onboarding is complete. Not otherwise
linked from most other screens except a few explicit "View all" buttons on
other cards that point back here.

**Role visibility:** **No role-based hiding anywhere on this screen.** Every
KPI, chart, and card renders identically for Owner/Admin/Data Engineer/Data
Analyst/Viewer. This includes the Approve/Reject buttons on the Pending
Approvals card (see below) — the backend actually restricts approve/reject to
Owner/Admin, but the frontend button is shown to every role regardless; a
Data Engineer/Data Analyst/Viewer who clicks it gets a real backend `403`,
surfaced only as the generic "Couldn't approve — try again." toast (the
mutation's `onError` handler doesn't inspect the status code to say
anything more specific). **NEW FINDING** — this is the same "role-gated
backend action, ungated frontend control" pattern found again on Sources and
Pipelines below; unlike Team/Settings/Billing (Phase 17), which hide
controls per role to match the backend guard, these earlier (Phase 9/12)
screens never got that treatment.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "Refresh" button | Click | Re-fires all 6 queries on the page (`GET /analytics`, `GET /analytics/quality?window_days=7`, `GET /analytics/recent-runs?limit=5`, `GET /approvals`, `GET /incidents/`, `GET /chat/sessions`) | "Dashboard refreshed." toast | Individual queries fail silently into their own empty/zero states (React Query default — no page-level error banner) |
| "Ask AXIOM" button | Click | Navigates to `/chat` | — | — |
| Health banner "Investigate" button (shown only when at least one open incident exists) | Click | Navigates to `/incidents` | — | — |
| Pending Approvals card — "Approve" button per item | Click | `POST /api/v1/approvals/{id}/approve` `{notes: ""}` | "Approved." toast, approvals list + KPI count both refetch (same query key) | Generic "Couldn't approve — try again." toast (see role note above — a 403 looks identical to a network error here) |
| Pending Approvals card — "Reject" button per item | Click | `POST /api/v1/approvals/{id}/reject` `{notes: ""}` | "Rejected." toast, list + KPI refetch | Generic "Couldn't reject — try again." toast |
| AXIOM Activity card — "Open" button, or clicking a listed session row | Click | Navigates to `/chat` (no session ID is passed — clicking a specific past conversation's row does **not** reopen that specific session, it just opens the Chat screen generically; re-selecting that conversation happens inside `/chat`'s own session list) | — | — |
| Recent Pipeline Runs card — "View all" button | Click | Navigates to `/pipelines` | — | — |
| KPI cards, charts | — | Read-only, no click handlers | — | — |

**Empty states:**
- Loading (`overview` or `quality` queries still in flight): one large skeleton
  block + a 4-card skeleton grid, replacing the entire content area.
- **NEW FINDING**, minor: the loading gate above only covers 2 of the 6 queries
  the page fires. The other four (`recentRuns`, `approvals`, `incidents`,
  `sessions`) have no independent loading state of their own — if they resolve
  slower than `overview`/`quality` (e.g. under a slow network), their cards
  briefly render as if genuinely empty ("No pipeline runs yet.", "Nothing
  pending approval.", "No conversations with AXIOM yet.") even on a tenant
  with real data, until that specific query resolves a moment later.
  Self-corrects, not persistent — but a real, observable flash of an
  inaccurate empty state.
- No incidents open → health banner simply doesn't render (not an empty-state
  message, just absent).
- No quality trend data yet (`trends.length === 0`) → both trend charts are
  omitted entirely (not shown as empty charts).
- Recent Pipeline Runs / Pending Approvals / AXIOM Activity cards each show
  their own "No … yet." message when their respective list is genuinely empty.

**Known issues:** See the role-visibility note above (approve/reject shown to
all roles; backend correctly blocks Data Engineer/Data Analyst/Viewer, but the
403 isn't distinguished in the UI). The Pending Approvals card and KPI reflect
only the **PolicyEngine** general-approval queue (`GET /approvals`) — CI/CD
deployment gates (`PipelineCommit.gate_decision`) are a separate queue, only
visible on the dedicated `/approvals` screen's merged view (Group 4).

---

### 8. Data Sources — `/sources`

**File:** `frontend/src/app/(app)/sources/page.tsx`

**Purpose:** Register, sync, profile, and delete the tenant's data sources
(CSV/Excel files, Postgres, MySQL, REST API, Google Sheets).

**How to reach it:** Sidebar → Data → "Data Sources".

**Role visibility:** **No role-based hiding.** Every role sees identical
Sync/Profile/Delete buttons and the "+ Add Source" button. Backend reality:
`POST /sources/` (create) is gated only by `enforce_quota("data_sources")` —
any authenticated role can create a source, subject to the tenant's plan
limit, not role. `POST /sources/{id}/sync` and `POST /sources/{id}/profile`
are **fully ungated** (any role). `DELETE /sources/{id}` **is** role-gated
(Owner/Admin/Data Engineer only) — a Data Analyst or Viewer sees and can click
the Delete button, and will get a real backend `403`, again surfaced only as
the generic "Failed to delete source." toast (no status-code branching in the
`onError` handler).

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ Add Source" button (also shown inside the empty state) | Click | Opens the "Add Data Source" modal | — | — |
| Modal — Name input | Type | Required; "Create" stays disabled until non-empty | — | — |
| Modal — Type `<Select>` (CSV file / Excel file / Postgres / MySQL / REST API / Google Sheets) | Select | Client-side only — swaps the connection-config textarea's placeholder to a type-specific example JSON blob | — | — |
| Modal — "Connection config (JSON)" textarea | Type | Free-form JSON, pre-filled with the selected type's placeholder | — | — |
| Modal — "Create" button | Click | Parses the textarea as JSON client-side first (invalid JSON → toast "Connection config must be valid JSON", never reaches the network); on valid JSON, `POST /api/v1/sources/` `{name, source_type, connection_config}` | Success toast naming the source, modal closes, name field resets, list refetches | Backend error message via toast, or generic "Failed to create source." |
| Table row — "Sync" button | Click | `POST /api/v1/sources/{id}/sync?mode=incremental` | "Sync started." toast, list refetches | "Sync failed." toast |
| Table row — "Profile" button | Click | `POST /api/v1/sources/{id}/profile` | "Source profiled." toast, list refetches | "Profiling failed." toast |
| Table row — "Delete" button | Click | `DELETE /api/v1/sources/{id}` — **no confirmation dialog before this fires**, the click is immediate and irreversible | "Source deleted." toast, list refetches | "Failed to delete source." toast (see role note above) |

**Empty states:** No sources yet → "No data sources yet" message + a
"+ Add Source" button (identical action to the header button).

**Known issues:**
- **Resolved, historical:** the CSV/Excel "Add Source" modal placeholders used
  to suggest a `{"path": "..."}` connection config, but the real connector
  (`FileConnector`) only reads `file_path` — a source created by typing the
  placeholder verbatim would silently fail to profile (`No such file or
  directory: ''`). Fixed in this project's own Phase 19 pre-walkthrough pass;
  the placeholders shown today already read `{"file_path": "sales.csv"}` /
  `{"file_path": "report.xlsx"}`, confirmed by the code read for this
  document. **The safer, real registration path for a file upload is
  `POST /api/v1/uploads/register` (multipart file upload, auto-generates a
  correct `file_path`) — this Sources screen's "Add Source" modal does not use
  that endpoint at all.** There is no file-upload control anywhere on this
  screen; a CSV/Excel source created here requires the operator to already
  know a real server-side file path to type into the JSON textarea by hand.
  **NEW FINDING**: this screen has no UI path to actually upload a file — the
  only way to get a real, working CSV/Excel source registered today is either
  hand-typing a path to a file already present on the server's filesystem
  (not realistic for an end user), or calling `POST /uploads/register`
  directly (no frontend page calls this endpoint at all — **UNVERIFIED**
  whether any other screen in this app exposes a file-picker wired to it; not
  found in Sources, Catalog, or Pipelines).
- Role-gated Delete with no frontend hiding — see Role visibility above.
- No delete confirmation dialog — a misclick deletes a source immediately
  (cascades to any pipelines/runs depending on it per the backend's own
  cascade behavior — not re-verified for this document, see Pipelines below
  for the related, already-fixed `DELETE /pipelines/{id}` history).

---

### 9. Data Catalog — `/catalog`

**File:** `frontend/src/app/(app)/catalog/page.tsx`

**Purpose:** Read-only, searchable view of every profiled (and not-yet-profiled)
table across all data sources, aggregated from each source's stored schema
snapshot.

**How to reach it:** Sidebar → Data → "Data Catalog".

**Role visibility:** No role-based hiding — `GET /api/v1/catalog/` and
`POST /sources/{id}/profile` (used by Sync Metadata) are both fully ungated;
every role sees and can use identical controls.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Search input | Type | Client-side only filter over already-fetched entries (matches table name, source name, tags, or column names, case-insensitive) | — | — |
| "Sync Metadata" button (disabled while syncing, or if there are zero catalog entries) | Click | Calls `POST /api/v1/sources/{id}/profile` **sequentially, once per unique source** appearing in the catalog (not in parallel) — button label shows live "Profiling N of M…" progress. One source failing to profile does not stop the loop (each call is individually try/caught and ignored). | "Metadata sync complete." toast after the full loop finishes; catalog list refetches | (No distinct failure state — per-source failures are silently swallowed, so a sync where every single source failed to profile would still end with the same "Metadata sync complete." success toast) |

**Empty states:**
- No sources at all → "No sources to catalog yet" + guidance to add and
  profile a source (no button here — the nearest add-source action is on the
  Sources screen, not linked directly from this empty state).
- Sources exist but a search term matches nothing → "No matches" + "Try a
  different search term."
- A source that has never been profiled still appears as its own row (not
  hidden), with a "Not profiled" badge in place of a table name and `—` for
  column/row counts — this is deliberate per the backend's aggregation design
  (`profiled: false` entries are included, not filtered out).

**Known issues:**
- **NEW FINDING**: "Sync Metadata"'s per-source failures are completely
  silent — the toast always says "complete" regardless of whether any/all of
  the underlying profile calls actually succeeded. A user has no way to tell,
  from this screen alone, whether a sync partially failed; they'd only notice
  via a source's "Last Profiled" timestamp not advancing.

---

### 10. Pipelines — `/pipelines`

**File:** `frontend/src/app/(app)/pipelines/page.tsx`

**Purpose:** Create, trigger, pause/activate, inspect run history for, and
delete pipelines (a pipeline = a scheduled or manually-triggered sync-then-
quality-check sequence against one data source).

**How to reach it:** Sidebar → Data → "Pipelines". Also reachable via
Dashboard's Recent Pipeline Runs "View all" button, and (per the pipeline-name
being a clickable link that opens the run-history modal) from within this
page itself.

**Role visibility:** **No role-based hiding**, same pattern as Sources.
Backend reality, confirmed by grep across `api/v1/*.py`:
- `POST /pipelines/` (create) — ungated, any authenticated role.
- `POST /pipelines/{id}/trigger` — gated only by `enforce_quota("pipeline_runs")`
  (blocks on quota, not role).
- `POST /pipelines/{id}/pause` and `/activate` — fully ungated, any role.
- `DELETE /pipelines/{id}` — role-gated (Owner/Admin/Data Engineer only,
  same three roles as Sources' delete). A Data Analyst or Viewer sees and can
  click Delete, gets a real `403`, sees the same generic "Failed to delete
  pipeline." toast either way.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ New Pipeline" button (also in the empty state) | Click | Opens the "New Pipeline" modal | — | — |
| Modal — Name input | Type | Required; "Create" disabled until non-empty | — | — |
| Modal — Source `<Select>` | Select | Optional — "No source (manual)" is a valid choice, leaving the pipeline with `source_id: null` | — | — |
| Modal — Description input | Type | Optional | — | — |
| Modal — Schedule (cron) input | Type | Optional free-text, e.g. `0 */6 * * *`; **no client-side cron validation** — any string is submitted as-is | — | — |
| Modal — "Create" button | Click | `POST /api/v1/pipelines/` `{name, source_id?, description?, schedule_cron?}` | Success toast naming the pipeline, modal closes and resets, list refetches | Generic "Failed to create pipeline." toast (no backend detail message surfaced) |
| Table row — pipeline name (clickable link) | Click | Opens the "Runs — {name}" modal | `GET /api/v1/pipelines/{id}/runs?limit=20` fires (query is `enabled` only while this modal is open) | — |
| Table row — "Trigger" button | Click | `POST /api/v1/pipelines/{id}/trigger` | "Run triggered." toast, list refetches (note: the table's own `status`/columns don't show run-in-progress state directly — that's only visible via the Runs modal or Dashboard) | "Failed to trigger run." toast (this is also the visible symptom of a quota-exceeded `402` — not distinguished from any other failure) |
| Table row — "Pause" button (shown when status ≠ `paused`) | Click | `POST /api/v1/pipelines/{id}/pause` | "Pipeline paused." toast, list refetches | "Failed to pause pipeline." toast |
| Table row — "Activate" button (shown when status = `paused`) | Click | `POST /api/v1/pipelines/{id}/activate` | "Pipeline activated." toast, list refetches | "Failed to activate pipeline." toast |
| Table row — "Delete" button | Click | `DELETE /api/v1/pipelines/{id}` — **no confirmation dialog**, immediate | "Pipeline deleted." toast, list refetches | "Failed to delete pipeline." toast (see role note above) |
| Runs modal — read-only table (status/rows/duration/when) | — | Populated by the query triggered when the modal opens | — | — |

**Empty states:**
- No pipelines yet → "No pipelines yet" + "+ New Pipeline" button.
- Runs modal, pipeline has never run → "No runs yet."

**Known issues:**
- Role-gated Delete with no frontend hiding — see Role visibility above.
- No delete confirmation dialog on a destructive, backend-cascading action
  (deleting a pipeline with run history deletes its `PipelineRun`/
  `QualityRule` rows and clears incident references — see `CLAUDE.md`'s
  `DELETE /pipelines/{id}` history). The underlying delete-cascade behavior
  itself is correct and already fixed/tested per `CLAUDE.md` (it no longer
  500s) — only the missing frontend confirmation step before firing the
  delete is a new finding here.
- No client-side cron syntax validation on the Schedule field — a malformed
  cron string is accepted by this form and sent to the backend as-is;
  **UNVERIFIED** what the backend does with an invalid cron string (whether
  it silently never fires, or errors at save time) — not traced further for
  this document since it's outside the frontend's own behavior.

---

## Screens — Group 3: Transforms, Quality, Incidents, Governance

*Files read for this group: `frontend/src/app/(app)/transforms/page.tsx`,
`frontend/src/app/(app)/quality/page.tsx`, `frontend/src/app/(app)/incidents/page.tsx`,
`frontend/src/app/(app)/governance/page.tsx`, `frontend/src/lib/api.ts`,
`backend/api/v1/{transformations,quality,incidents,governance}.py` (grepped for
`role`/`require_role` in all four to confirm exact gating).*

### 11. Transforms — `/transforms`

**File:** `frontend/src/app/(app)/transforms/page.tsx`

**Purpose:** Generate, edit, run, and replay SQL/Python data transformations
against a selected source — via natural language, a raw SQL editor, or a raw
Python (pandas) editor — plus a history of every real execution.

**How to reach it:** Sidebar → Data → "Transforms". Also reachable indirectly:
the Chat screen's agent can trigger real transform executions itself (see
Chat, Group 5), which then appear in this screen's History tab regardless of
whether the user ever opens Transforms directly.

**Role visibility:** Mixed, and **not reflected in the UI at all.** A single
data-source `<Select>` at the top applies to all four tabs. Backend reality,
confirmed by grep:
- Generate (Natural Language tab), Dry Run (SQL tab), Preview (Python tab),
  and Explain (Python tab) are all **fully ungated** — any authenticated role,
  including Viewer, can use them.
- **Execute** (both the SQL tab's "Execute" and the Python tab's "Execute")
  is role-gated to Owner/Admin/Data Engineer/Data Analyst — **Viewer is the
  only role excluded.** The button itself is shown and enabled identically
  for a Viewer; clicking it produces a real backend `403`. Unlike most other
  screens in this app, this one's error handling **does** surface the real
  backend detail message inline (via a shared `errMsg()` helper that reads
  `ApiError.detail` when it's a string) rather than a generic toast — a
  Viewer would actually see "Requires role: owner or admin or data_engineer
  or data_analyst" printed under the editor, not a vague failure.
- History tab (`GET /transformations/runs`) is ungated — any role can view it.

**Interactive elements:**

*Shared:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Data source `<Select>` (above the tabs) | Select | Client-side only — feeds `source_id` into whichever tab's action is used next | — | — |
| Tabs: Natural Language / SQL Editor / Python Editor / History | Click | Client-side only, switches the visible panel | — | — |

*Natural Language tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Goal text input | Type | Free text, e.g. "Filter rows where widget_count is greater than 15" | — | — |
| Language `<Select>` (Auto / SQL / Pandas) | Select | **NEW FINDING**: "Auto" and "SQL" are functionally identical — the selected value only decides, client-side, whether `generatePandasTransform` (`pandas` selected) or `generateSqlTransform` (`auto` or `sql` selected) is called; the chosen value itself is never actually sent to the backend as a parameter (neither generate call has a `language` field). There is no real auto-detection — picking "Auto" always produces SQL, exactly like explicitly picking "SQL." | — | — |
| "Generate" button (disabled until the goal field is non-empty) | Click | `POST /transformations/generate/sql` or `/generate/pandas` `{request, source_id?}` depending on the language selector above | Generated code renders in a read-only code block; a badge shows "Grounded in real schema" (green) or "No schema available" (yellow) reflecting the backend's real `schema_used` flag, plus a warning-count badge if the backend returned any | Inline red error text with the backend's detail message |
| "Send to SQL/Python Editor" button (shown only once a result exists) | Click | Client-side only — copies the generated code into the matching editor's state and switches tabs | — | — |

*SQL Editor tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| SQL code textarea | Type | Free-form, pre-filled with `SELECT 1;` | — | — |
| "Dry Run" button | Click | Requires a source selected first (else a "Select a data source first." toast, no call made) → `POST /transformations/run/sql/dry-run` `{source_id, sql}` — ungated, any role | Renders the returned query plan as a table | Inline red error text |
| "Execute" button | Click | Same source-required guard → `POST /transformations/run/sql` `{source_id, sql}` — **role-gated, see above** | Renders real result rows (capped at 100 shown client-side even if more are returned) with row count/duration/truncated flag; the transform-runs History query is invalidated so it appears there too | Inline red error text (a Viewer's 403 shows here, verbatim) |

*Python Editor tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Python code textarea | Type | Free-form, pre-filled with `result_df = df.head(10)` | — | — |
| "Preview (100 rows)" button | Click | Source-required guard → `POST /transformations/preview/pandas` `{source_id, code}` — ungated | Renders preview result rows | Inline red error text |
| "Execute" button | Click | Source-required guard → `POST /transformations/run/pandas` `{source_id, code}` — **role-gated, same as SQL Execute** | Renders real result rows, invalidates History | Inline red error text |
| "✨ Explain" button | Click | `POST /transformations/explain` `{code, language: "pandas"}` — ungated. **Note**: this button only exists on the Python tab; there is no equivalent "Explain" control anywhere on the SQL tab. | Renders a plain-English explanation card below the editor | Danger toast with the backend detail message |

*History tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (on tab open) | — | `GET /transformations/runs?limit=50` — ungated, any role | Lists every real execution (both this screen's own Execute calls and any AXIOM chat-triggered transform runs — an "Origin" column distinguishes "AXIOM" vs "Manual"), truncated code preview, type badge, success/failed status badge, row count, timestamp | — |
| "Replay" button per row | Click | Client-side only — no API call. Loads that run's exact source + code back into the matching editor tab and switches to it, with a "Loaded into editor — review and run." toast. **Does not re-execute anything by itself** — the user must click Execute again after reviewing. | — | — |

**Empty states:** History tab with zero runs → "No transforms run yet" +
explanatory text that both manual and AXIOM-triggered runs will appear here.
Result areas (before any Generate/Dry Run/Execute/Preview) show a placeholder
comment or nothing at all, not an "empty state" per se.

**Known issues:**
- Execute is role-gated (excludes Viewer) with no frontend hiding — though,
  as noted above, this is the one screen where the resulting error message is
  actually informative rather than generic.
- The "Auto" language option's lack of real auto-detection (NEW FINDING,
  above).
- Dry Run / Preview / Explain / Generate are all safe to leave fully ungated
  (read-only or sandboxed, matching `CLAUDE.md`'s stated reasoning for why
  `run/sql/dry-run` was deliberately left out of the role retrofit).

---

### 12. Quality — `/quality`

**File:** `frontend/src/app/(app)/quality/page.tsx`

**Purpose:** Create and manage quality rules attached to pipelines (not_null,
unique, accepted_values, range, freshness, regex, row_count, custom_sql), and
manually trigger a check run.

**How to reach it:** Sidebar → Quality & Ops → "Quality".

**Role visibility:** **No role-based hiding.** Backend reality: `POST /quality/`
(create rule) and `POST /quality/{pipeline_id}/run` (run checks) are both
fully ungated — any role. `DELETE /quality/{rule_id}` is role-gated
(Owner/Admin/Data Engineer) with no frontend hiding, same generic-toast
pattern as Sources/Pipelines delete.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ New Rule" button (disabled if there are zero pipelines to attach a rule to) | Click | Opens the "New Quality Rule" modal | — | — |
| Modal — Name input | Type | Required | — | — |
| Modal — Pipeline `<Select>` | Select | Required | — | — |
| Modal — Rule type `<Select>` (not_null / unique / accepted_values / range / freshness / regex / row_count / custom_sql) | Select | These are exactly the 8 base rule types `QualityRuleEngine` actually supports — **this dropdown does not expose any of the separate "business rule" types** (`reconciliation`, `kpi_sanity`, etc.), so the known, documented `BusinessRules.create_rule()` bug (can't create any of its own 8 business-rule types — see `CLAUDE.md` Known-broken) is **not reachable from this screen at all**. | — | — |
| Modal — Column (optional) input | Type | Optional | — | — |
| Modal — Severity `<Select>` (low/medium/high/critical) | Select | Defaults to "high" | — | — |
| Modal — "Create" button (disabled until Name + Pipeline are set) | Click | `POST /api/v1/quality/` `{pipeline_id, name, rule_type, column_name?, severity}` | Success toast, modal closes, list refetches | "Failed to create rule — check a pipeline is selected." toast |
| Table row — "Run Checks" button | Click | `POST /api/v1/quality/{pipeline_id}/run` — **runs every rule attached to that rule's pipeline, not just the one row clicked.** The button is scoped per-row visually, but the action is pipeline-wide. | Toast with the real score and pass/fail counts, e.g. "Checks ran — score 100, 3 passed / 0 failed."; list refetches (pass/fail counts on every rule for that pipeline update) | "Failed to run checks." toast |
| Table row — "Delete" button | Click | `DELETE /api/v1/quality/{rule_id}` — no confirmation dialog | "Rule deleted." toast, list refetches | "Failed to delete rule." toast (see role note above) |

**Empty states:** Zero pipelines exist → "Create a pipeline first, then attach
quality rules to it." (no "+ New Rule" button shown at all in this case).
Pipelines exist but zero rules → "Attach rules to a pipeline to catch bad data
before it spreads." + a working "+ New Rule" button.

**Known issues:**
- **NEW FINDING**: "Run Checks" is pipeline-scoped, not rule-scoped, despite
  appearing as a per-rule row action — clicking it on any one rule re-runs
  every rule attached to that pipeline.
- Role-gated Delete with no frontend hiding, no confirmation dialog.

---

### 13. Incidents — `/incidents`

**File:** `frontend/src/app/(app)/incidents/page.tsx`

**Purpose:** View open incidents (raised automatically by AXIOM/the freshness
checker, or logged manually here) and mark them resolved.

**How to reach it:** Sidebar → Quality & Ops → "Incidents". Also reachable via
the Dashboard's health banner "Investigate" button when at least one open
incident exists.

**Role visibility:** **No role gating anywhere on this screen or its two
backend endpoints** — `POST /incidents/` (create/log) and
`POST /incidents/{id}/resolve` have no `require_role` at all, confirmed by
grep (zero matches in `incidents.py`). Every role can log and resolve
incidents identically.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ Log Incident" button (also in empty state) | Click | Opens the "Log Incident" modal | — | — |
| Modal — Title input | Type | Required | — | — |
| Modal — Description input | Type | Optional | — | — |
| Modal — Severity `<Select>` (low/medium/high/critical) | Select | Defaults to "medium" | — | — |
| Modal — Pipeline `<Select>` | Select | Optional — "None" is valid | — | — |
| Modal — "Log Incident" button (disabled until Title is set) | Click | `POST /api/v1/incidents/` `{title, description?, severity, pipeline_id?}` | Success toast, modal closes, list refetches | "Failed to create incident." toast |
| Table row — "Resolve" button (shown only when status ≠ `resolved`) | Click | Opens the "Resolve Incident" modal (does not resolve immediately) | — | — |
| Resolve modal — Resolution notes input (required) | Type | — | — | — |
| Resolve modal — "Mark Resolved" button (disabled until notes are non-empty) | Click | `POST /api/v1/incidents/{id}/resolve` `{resolution_notes}` | "Incident resolved." toast, modal closes, list refetches | "Failed to resolve incident." toast |

**Empty states:** No open incidents → "No incidents — Nothing's on fire.
Incidents raised by AXIOM or logged manually will show up here." + "+ Log
Incident" button.

**Known issues:** This screen's list query (`GET /incidents/`) returns *open*
incidents — **UNVERIFIED** from the frontend code alone whether a resolved
incident stays visible in this same list immediately after resolving (it
still appears in the table with status `resolved` and a "—" in place of the
Resolve button per the code, but whether the backend's underlying query
continues to include already-resolved incidents indefinitely, or only briefly
until the next fetch, was not traced into `incidents.py`'s query logic for
this document).

---

### 14. Governance — `/governance`

**File:** `frontend/src/app/(app)/governance/page.tsx`

**Purpose:** Three tabs — Lineage (a graph of sources → pipelines → outputs),
Contracts (schema/quality expectations defined against a source, with
on-demand validation), and Audit Log (a read-only feed of governance and
approval actions).

**How to reach it:** Sidebar → Quality & Ops → "Governance".

**Role visibility:** **No role gating anywhere** — `governance.py` has zero
`role`/`require_role` references (confirmed by grep). Every role can view
lineage, create/validate contracts, and read the audit log identically.

**Interactive elements:**

*Lineage tab (default):*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (on tab load) | — | `GET /governance/graph` — this endpoint self-heals/backfills lineage for the tenant on every read (per `CLAUDE.md`'s Phase 12 lineage work), so the graph shown is always current even for older tenants that predate auto-population | Two read-only tables: Nodes (name + type badge: source/pipeline/output) and Edges (upstream → relationship → downstream, resolved to real node names where possible) | — |

*Contracts tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ New Contract" button (only shown while this tab is active; disabled if there are zero sources) | Click | Opens the "New Data Contract" modal | — | — |
| Modal — Name input | Type | Required | — | — |
| Modal — Producer source `<Select>` | Select | Required | — | — |
| Modal — Consumer description input | Type | Optional | — | — |
| Modal — "Create" button | Click | `POST /governance/contracts` `{name, producer_source_id, consumer_description?}` | Success toast, modal closes, contracts list **and** audit trail both refetch (contract creation is itself an audited action) | "Failed to create contract." toast |
| Table row — "Validate" button | Click | `POST /governance/contracts/{id}/validate` | "Contract validated." toast, contracts list **and** audit trail both refetch, table's Status badge updates (valid/violated/pending) and Last Validated timestamp updates | "Validation failed." toast |

*Audit Log tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (on tab load) | — | `GET /governance/audit?limit=50` | Read-only table: actor, action (raw action string, e.g. `contract.created`), resource type + short ID, timestamp | — |

**Empty states:** Lineage with no nodes → "No lineage yet — Lineage nodes are
created automatically as you add sources and pipelines." Contracts with none
yet → "Add a source first, then define a contract against it." (no sources)
or "Define expectations for a source's schema and quality, then validate them
anytime." (sources exist, zero contracts). Audit log with no entries → "No
audit events yet."

**Known issues:** None found specific to this screen — Contracts' Audit Log
staleness bug (create/validate not invalidating the audit query) is already
fixed per `CLAUDE.md`'s Phase 12 Status Table, confirmed still fixed by this
screen's current code (both mutations explicitly invalidate `["audit-trail"]`
alongside `["contracts"]`).

---

## Progress tracker

- [x] **Group 1: Landing & Authentication** — Landing, Login, Signup, Google
      callback, Onboarding, Invite accept. 2 new findings logged (both above,
      not yet fixed): the broken `/accept-invite` vs `/invite/accept` emailed
      link path, and invited members skipping onboarding.
- [x] **Group 2: Dashboard, Sources, Catalog, Pipelines.** New findings logged
      (not fixed): role-gated backend actions (approve/reject, source/pipeline
      delete) have no frontend role-based hiding on these four screens, unlike
      Team/Settings/Billing; Dashboard's 4 secondary queries have no
      independent loading state and can flash an inaccurate empty state;
      Sources has no actual file-upload UI despite offering CSV/Excel as
      source types; Catalog's Sync Metadata silently swallows per-source
      failures; Pipelines has no delete confirmation dialog.
- [x] **Group 3: Transforms, Quality, Incidents, Governance.** New findings
      logged (not fixed): Transforms' "Auto" language selector doesn't
      actually auto-detect — it's identical to picking "SQL"; Quality's
      "Run Checks" button is per-rule visually but pipeline-wide in effect;
      Execute (Transforms) and Delete (Quality) remain role-gated with no
      frontend hiding, consistent with Group 2's pattern. Incidents and
      Governance are both fully ungated by role, matching their backend code.
      One UNVERIFIED item: whether resolved incidents remain in the
      Incidents list indefinitely or only briefly.
- [ ] Group 4: Automations, CI/CD, Approvals, Analytics, Audit
- [ ] Group 5: AI Employees, Chat
- [ ] Group 6: Team, Billing, Settings (5 tabs)
- [ ] End-to-end user flows
- [ ] Glossary
- [ ] Role-permission matrix
- [ ] Export to PDF
