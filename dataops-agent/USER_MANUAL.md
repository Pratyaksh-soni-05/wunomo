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

## Screens — Group 4: Automations, CI/CD, Approvals, Analytics, Audit

*Files read for this group: `frontend/src/app/(app)/automations/page.tsx`,
`frontend/src/app/(app)/cicd/page.tsx`, `frontend/src/app/(app)/approvals/page.tsx`,
`frontend/src/app/(app)/analytics/page.tsx`, `frontend/src/app/(app)/audit/page.tsx`,
`frontend/src/components/shell/StubPage.tsx`, `frontend/src/lib/api.ts`,
`backend/api/v1/{cicd,approvals}.py` (grepped for every mutating route and its
role gate).*

### 15. Automations — `/automations`

**File:** `frontend/src/app/(app)/automations/page.tsx` — renders the shared
`StubPage` component only.

**Purpose:** None yet. Per both `CLAUDE.md` and `FRONTEND_BUILD_PLAN.md`, a
real trigger→action rule engine for this screen is explicitly deferred as "a
dedicated post-launch project," confirmed as one of the plan's three
confirmed-Coming-Soon items at launch (alongside the 5 locked AI Employees and
Governance's Compliance sub-tab, which doesn't exist as a separate tab at all
in the current Governance screen — see Group 3).

**How to reach it:** Sidebar → Quality & Ops → "Automations".

**Role visibility:** N/A — static stub, identical for every role.

**Interactive elements:** None.

**Empty states:** The entire screen *is* the empty state — a centered icon,
the title "Automations," and the generic stub message: "This screen is a
routable stub for now — real content lands in a later phase." (This
particular stub is not passed a `phase` prop, unlike some others, so it gets
the generic message rather than a "wired to real data in Phase N" one.)

**Known issues:** None beyond being unbuilt — this is documented,
intentional, launch-scoped Coming Soon, not a defect.

---

### 16. CI / CD — `/cicd`

**File:** `frontend/src/app/(app)/cicd/page.tsx`

**Purpose:** GitHub-webhook-driven pipeline CI status — commit risk scoring
and deploy-gate decisions, plus a log of real deployments and their
post-deploy monitoring.

**How to reach it:** Sidebar → Quality & Ops → "CI / CD".

**Role visibility:** **No role-based hiding**, same recurring pattern as
Groups 2–3. Backend reality (confirmed by grep of `cicd.py`):
`POST /cicd/commits/{id}/approve` and `/reject` are both role-gated
(Owner/Admin only) — the Commits tab shows Approve/Reject buttons to every
role identically; a Data Engineer/Data Analyst/Viewer sees them, can click
them, and gets a real `403` surfaced as the generic "Failed to approve/reject
deployment." toast.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (on load) | — | `GET /cicd/status/summary`, `GET /cicd/commits?limit=20`, `GET /cicd/deployments?limit=20` — all three ungated, any role | Populates the 4 summary cards (Pipeline Health, Active Deployments, Rollbacks, Pending Approvals) and both tabs | — |
| Tabs: Commits / Deployments | Click | Client-side only | — | — |
| Commits tab — "Approve" button (shown only when `gate_decision === "pending_approval"`) | Click | `POST /cicd/commits/{id}/approve` — **role-gated, see above** | "Deployment approved and queued." toast, summary + both tabs' data all refetch | "Failed to approve deployment." toast |
| Commits tab — "Reject" button (same visibility condition) | Click | `POST /cicd/commits/{id}/reject` — **role-gated** | "Deployment rejected." toast, everything refetches | "Failed to reject deployment." toast |
| Deployments tab | — | Read-only table (status, monitoring active/closed, post-deploy run count, failure count, deployed-at) | — | — |

**Empty states:** No commits yet → "No commits yet — Commits arrive via the
GitHub webhook when a pipeline definition file changes." No deployments yet →
"No deployments yet — Deployments appear here once a commit is approved and
deployed."

**Known issues:**
- Role-gated Approve/Reject with no frontend hiding — consistent with the
  pattern documented in Group 2.
- **NEW FINDING**: the backend exposes `PATCH /cicd/incidents/{incident_id}/resolve`
  (also role-gated, Owner/Admin), for a **separate** incident system
  (`models.cicd.CICDIncident`, distinct from the general `Incident` model the
  `/incidents` screen manages — see `CLAUDE.md`'s note that "two different
  'incident' systems exist in this codebase"). **No screen anywhere in this
  app calls this endpoint** — grepped the entire `lib/api.ts` for any
  `cicd/incidents` reference; there is none. Whatever this endpoint is for
  is currently only reachable by a direct API call, not through any UI.
- The 4-card summary's "Pending Approvals" count reflects only CI/CD gate
  decisions (via `GET /cicd/status/summary`) — it is a **different number**
  from the Dashboard's "Pending Approvals" KPI (which reflects only the
  PolicyEngine queue) and from the dedicated Approvals screen's count (which
  merges both). Seeing three different "pending approvals" numbers across
  Dashboard, this screen, and Approvals is expected/correct given what each
  actually counts, but is easy to misread as an inconsistency.

---

### 17. Approvals — `/approvals`

**File:** `frontend/src/app/(app)/approvals/page.tsx`

**Purpose:** The single merged view of every pending approval in the tenant —
both general agent/policy-engine actions and CI/CD deployment gates — in one
list, per the locked Phase 0 design decision to build this as a real backend
aggregation endpoint rather than a frontend-side merge.

**How to reach it:** Sidebar → Quality & Ops → "Approvals".

**Role visibility:** **No role-based hiding**, same pattern again. Both
underlying actions this screen can trigger are role-gated: `POST
/approvals/{id}/approve`/`/reject` (inline check in `approvals.py`, not the
shared `require_role` dependency, but functionally identical — Owner/Admin
only) for `source: "policy_engine"` items, and `POST
/cicd/commits/{id}/approve`/`/reject` (Owner/Admin) for
`source: "cicd_deployment"` items. Every role sees identical Approve/Reject
buttons on every row regardless of which source it is.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| (on load) | — | `GET /approvals/merged` | Lists every pending item from both queues, newest first, each tagged with a "Source" badge ("Agent Action" or "CI/CD Deployment") and a real risk-level badge | — |
| Table row — "Approve" button | Click | Routed by the item's own `source` field: `POST /cicd/commits/{id}/approve` if `cicd_deployment`, else `POST /approvals/{id}/approve` — **the frontend never invents its own mutation path, it always defers to whichever real endpoint owns that item, per the locked design** | "Approved." toast, list refetches | "Failed to approve." toast (generic, same for either underlying source or a role 403) |
| Table row — "Reject" button | Click | Same routing logic, reject variant | "Rejected." toast, list refetches | "Failed to reject." toast |

**Empty states:** Nothing pending → "Nothing pending approval — Agent actions
and CI/CD deployments that need a human sign-off will show up here."

**Known issues:**
- Role-gated actions with no frontend hiding — same recurring pattern.
- This list deliberately excludes one specific category of stuck/orphaned
  item by design (`policy_engine` requests with `action_name ==
  "cicd_pipeline_deployment"`, a historical double-booking bug — see
  `CLAUDE.md`'s now-`[RESOLVED]` "CI/CD high-risk commits double-book their
  approval" row) — confirmed still present and correctly commented in the
  current backend code, not a live bug today.

---

### 18. Analytics — `/analytics`

**File:** `frontend/src/app/(app)/analytics/page.tsx` — renders the shared
`StubPage` component only, with `phase={undefined}` (same generic stub
message as Automations).

**Purpose:** None yet, as its own dedicated screen. **This is a real gap
worth being precise about**: a `GET /api/v1/analytics` endpoint (plus
`/analytics/quality` and `/analytics/recent-runs`) genuinely exists and is
real, live-verified, tenant-scoped data — but it is only ever consumed by the
**Dashboard** screen (Group 2), not by this dedicated Analytics screen. A
user clicking the sidebar's "Analytics" item expecting a deeper/different
analytics view than the Dashboard's KPI cards gets an empty stub instead.

**How to reach it:** Sidebar → Analytics → "Analytics".

**Role visibility:** N/A — static stub.

**Interactive elements:** None.

**Empty states:** Entire screen is the stub message.

**Known issues:** Unbuilt. Not called out as a launch-blocking gap in either
`CLAUDE.md` or `FRONTEND_BUILD_PLAN.md`'s Coming-Soon list (which names only
Automations, the 5 locked AI Employees, and Governance's Compliance tab) —
**NEW FINDING**: this screen appears to be an unremarked gap, not a
consciously-scoped Coming Soon item like the other three stubs in this group.

---

### 19. Audit Logs — `/audit`

**File:** `frontend/src/app/(app)/audit/page.tsx` — renders the shared
`StubPage` component only.

**Purpose:** None yet, as its own dedicated screen. **Same shape of gap as
Analytics**: a real, working audit trail already exists and is fully wired up
— but only inside **Governance's "Audit Log" tab** (Group 3), which reads the
exact same `GET /governance/audit` endpoint. The sidebar's separate,
top-level "Audit Logs" item (under the Admin section) is unrelated to that
tab and is just an empty stub.

**How to reach it:** Sidebar → Admin → "Audit Logs".

**Role visibility:** N/A — static stub.

**Interactive elements:** None.

**Empty states:** Entire screen is the stub message.

**Known issues:** **NEW FINDING**: this creates a real, confusing duplication
in the sidebar — two differently-labeled nav items ("Governance" and "Audit
Logs") where only one of them (Governance's third tab) actually shows the
real audit trail, and the other is a dead end. A user who specifically wants
"the audit log" has no way to know, without trial and error, that the working
version is one tab inside a differently-named screen.

---

## Screens — Group 5: AI Employees, Chat

*Files read for this group: `frontend/src/app/(app)/ai-employees/page.tsx`,
`frontend/src/lib/employees.ts`, `frontend/src/components/shared/EmployeeCard.tsx`,
`frontend/src/app/(app)/chat/page.tsx`,
`frontend/src/components/chat/{SessionList,MessageThread,ContextPanel,ToolCallBlock,useSavedPrompts}.tsx`,
`frontend/src/lib/api.ts`, `backend/api/v1/chat.py`, `backend/agent/personality.py`
(plus a grep of `backend/agent/` for any `role` check, and of the frontend for any
WebSocket usage).*

### 20. AI Employees — `/ai-employees`

**File:** `frontend/src/app/(app)/ai-employees/page.tsx` +
`frontend/src/lib/employees.ts` + `frontend/src/components/shared/EmployeeCard.tsx`

**Purpose:** A 6-tile roster page — AXIOM (real, active) plus 5 honestly
locked "Coming Soon" employees (LEDGER, DEPLOY, INSIGHT, SENTINEL, PULSE).

**How to reach it:** Sidebar → Workspace → "AI Employees".

**Role visibility:** N/A — purely static content, no API calls of any kind
(the roster data is a hardcoded local module, `lib/employees.ts`, shared
verbatim with the landing page's roster section so the two can't drift).

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| AXIOM tile's "Open AXIOM →" button | Click | Navigates to `/chat` | — | — |
| 5 locked tiles | — | Non-interactive — each shows a translucent "Coming Soon" overlay badge over the card, no button, no click target | — | — |

**Empty states:** N/A — always renders all 6 tiles.

**Known issues:** None — this screen matches its own documented, intentional
scope exactly (`CLAUDE.md` Phase 18: no waitlist button, no marketplace
button, no per-tile pricing, all deliberate).

---

### 21. AXIOM Chat — `/chat`

**File:** `frontend/src/app/(app)/chat/page.tsx` +
`frontend/src/components/chat/{SessionList,MessageThread,ContextPanel,ToolCallBlock,useSavedPrompts}.tsx`

**Purpose:** The real 3-panel conversational interface to AXIOM, the one
active AI employee — send messages, see real tool calls it executes against
the tenant's real data, and manage saved prompts/session history.

**How to reach it:** Sidebar → Workspace → "AXIOM" (badge: "Live"). Also: the
AXIOM FAB (floating button, visible on every other authenticated screen, hides
itself here), Dashboard's "Ask AXIOM" button and AXIOM Activity card, AI
Employees' "Open AXIOM →" tile CTA, the landing page's AXIOM tile CTA when
logged in.

**Role visibility:** `POST /api/v1/chat/` has **no role gate at all** — it is
only gated by `enforce_quota("ai_credits")` (blocks on the tenant's plan
credit limit, not on who's asking). `GET /chat/sessions` and
`GET /chat/sessions/{id}/history` are likewise ungated. **Every role,
including Viewer, can converse with AXIOM freely (subject to quota).**

**NEW FINDING, significant**: the tools AXIOM calls on a user's behalf are
gated **only by `operation_mode` and a hardcoded per-tool risk tier
(`personality.py`'s `RISK_ACTIONS`)** — never by the calling user's `role`.
Grepping the entire `backend/agent/` tree for any `role` check found none
(the single unrelated hit is a chat-message-role field, not a user role).
This matters because tool execution calls the same underlying service-layer
functions the REST endpoints call, **in-process, not through this app's own
role-gated REST API** — so a Viewer chatting with AXIOM under
`operation_mode: autonomous` could have AXIOM successfully execute an action
(e.g. triggering a pipeline run, requesting an approval, generating a report)
that the exact same Viewer would get a real `403` for if they tried it
directly through this app's own screens. This compounds with an already-
documented bug: `RISK_ACTIONS`'s `"high"` tier lists four tool names
(`delete_records`, `drop_table`, `modify_schema`, `revoke_access`) that
**aren't real registered tools at all** (see `CLAUDE.md`'s "Phantom high-risk
tools" row) — so in practice almost every real tool resolves to `medium` or
`low` risk, and `autonomous` mode (which only routes literal `high`-risk
calls through approval) ends up approving nearly everything automatically,
regardless of who's asking.

**Interactive elements:**

*Left panel — Session List:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ New Chat" button | Click | Client-side only — clears the local message thread, draft, attached context, and active session ID. Does **not** call the backend; the previous conversation isn't deleted, just deselected. | — | — |
| A session row in "Recent" | Click | `GET /chat/sessions/{id}/history` | Loads that session's full real message history (including its real tool-call trace) into the thread | "Failed to load conversation history." toast |
| A "Saved Prompts" entry | Click | Client-side only — replaces (not appends to) the current draft text with the saved prompt's text | — | — |
| Saved prompt's "✕" remove button | Click | Client-side only, removes it from `localStorage` | — | — |
| "+ Save current draft" (disabled when the draft is empty) | Click | Client-side only, appends the current draft text to `localStorage` | — | — |

Saved prompts are stored in `localStorage` under a per-tenant key
(`axiom_saved_prompts_{tenantId}`) — **personal to the browser they were
saved in, not synced across devices, and not shared with teammates**, even
though they visually sit right next to session history.

*Middle panel — Message Thread:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Personality mode `<Select>` (Engineer/Founder/Analyst/Auditor) | Select | Client-side only, sent as `personality_mode` on the *next* message — changes the system prompt's tone/verbosity going forward; does not retroactively affect already-rendered messages | — | — |
| Operation mode `<Select>` (Advisory/Assisted/Autonomous/Audit) | Select | Client-side only, sent as `operation_mode` on the *next* message — see the approval-gating explanation above and in "Glossary"/"End-to-end flows" below | — | — |
| Message textarea | Type | Enter sends (unless Shift+Enter, which inserts a newline); disabled while a send is in flight | — | — |
| "Send" button (disabled while empty or sending) | Click | `POST /api/v1/chat/` `{message, session_id?, personality_mode, operation_mode, context?}` | Real assistant response appended to the thread, along with its real tool-call trace (each rendered as a collapsible `ToolCallBlock`); the header's status line updates to "Ready · last reply via {provider}" (the real LLM provider that served this specific reply — `gemini` or `groq` — surfaced transparently to the user); if this was a brand-new conversation, the newly-assigned `session_id` is captured so the next message continues the same thread; the session list on the left refetches so the (possibly new) session appears there | Two distinct inline+toast messages depending on failure type: a real backend error → "AXIOM couldn't complete that request — it may have tried an action it couldn't format correctly. Try rephrasing, or try again."; a network-level failure (can't reach the backend at all) → "Couldn't reach AXIOM. Check your connection and try again." **The user's own just-sent message is never rolled back or removed on failure** — it stays visible in the thread either way. |
| 5 "Quick Prompt" buttons (fixed suggestions: "List my data sources", "Show failed pipeline runs", "Run quality checks on a pipeline", "List open incidents", "Generate a status report") | Click | Client-side only — inserts the prompt text into the draft. **Does not send automatically** — the user still has to press Enter or click Send. | — | — |
| Attached-context chip's "✕" (shown only when a source is attached) | Click | Client-side only, clears `attachedContext` | — | — |
| Assistant message text | — | Rendered via a small hand-rolled formatter: HTML-escapes the raw text first (`&`, `<`, `>`), *then* converts `**bold**` to `<strong>` and newlines to `<br>` before injecting via `dangerouslySetInnerHTML` — the escape-first ordering means AXIOM's own response text cannot inject arbitrary HTML/script tags into the page even though `dangerouslySetInnerHTML` is used. | — | — | — |
| A `ToolCallBlock` header (tool name + "Completed"/"Needs approval" badge) | Click | Client-side only — expands/collapses to show the real raw `Arguments` (JSON) and `Result` (pretty-printed JSON, or the raw string if it isn't valid JSON) for that specific tool call | — | — |
| A blocked tool call's approval notice (shown only when the tool call's `status` is `blocked_pending_approval`) | — | Displays the real risk level and reason (when the backend supplied them) inline, plus a "Approvals screen" link | Click navigates to `/approvals` | — |

*Right panel — Context Panel:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "Attach a source…" `<Select>` (shown only when nothing is currently attached) | Select | Client-side only — stores `{source_id, source_name}`, sent as `context` on the *next* message. The backend genuinely reads this to inject the source into AXIOM's system prompt (confirmed real, not decorative, per `CLAUDE.md`'s Phase 10 verification). When nothing is attached, an explicit note clarifies: "AXIOM will still use its tools, this just hints which source you mean." | — | — |
| Attached-context chip's "✕" | Click | Client-side only, clears the attachment | — | — |
| "Tool Calls This Session" log | — | Read-only, aggregates every tool call across every message already loaded into the thread, reusing the same `ToolCallBlock` component as the inline per-message rendering — **seeing a tool name appear twice on screen (once inline, once here) is correct-by-design, not a duplication bug** (per `CLAUDE.md`'s own note on this exact point) | — | — |

**Empty states:** No messages in the current thread yet (and not currently
sending) → "Ask AXIOM anything" + explanatory text. No saved sessions yet →
"No conversations yet." No saved prompts yet → "No saved prompts yet." No
tool calls yet this session → "No tools called yet."

**Known issues:**
- The role-bypass finding above (**NEW FINDING**) — this is the single most
  consequential access-control gap surfaced anywhere in this document.
- The already-documented "Phantom high-risk tools" bug (`CLAUDE.md`
  Known-broken) directly affects how much this screen's Autonomous mode
  actually gates in practice — see above.
- **NEW FINDING**: `CLAUDE.md`'s Known-broken table still carries an open row
  titled "`request_approval` tool is broken" (claiming
  `PolicyEngine.request_approval()` doesn't exist) — but a *later* row in the
  same table ("22-site tool punch list — `governance_tools.py`") describes
  this exact tool being fixed (redirected to the real `create_request()`
  method) and **live-verified**, including a real `ApprovalRequest` row being
  created through it. This looks like the same class of stale-row
  bookkeeping gap already caught and partially cleaned up in this project's
  own Phase 19 pre-walkthrough session (two other rows were marked
  `[RESOLVED]` then) — this third one appears to have been missed. Not fixed
  here, logged for the same triage.
- The severe, already-documented WebSocket auth gap (`WS /ws/chat/{tenant_id}/{session_id}`,
  no JWT check at all) is real but **not reachable through this screen or any
  other part of the actual product UI** — grepped the entire frontend for any
  WebSocket usage and found none; this screen (and the whole app) only ever
  uses the REST `POST /chat/` endpoint. The WS route is exposed by the
  backend but dormant from the product's own perspective — still a real gap
  if hit directly, just not one a normal user path can trigger.

---

## Screens — Group 6: Team, Billing, Settings

*Files read for this group: `frontend/src/app/(app)/team/page.tsx`,
`frontend/src/app/(app)/billing/page.tsx`, `frontend/src/app/(app)/settings/page.tsx`,
`frontend/src/lib/{api,theme}.ts`, `backend/api/v1/{team,billing,settings}.py`.
These three screens (Phase 17) are the only ones in the app where the frontend's
role-based hiding was built to deliberately mirror the backend's real role
gates — a useful contrast to every screen in Groups 2–5, which show every
control to every role regardless of what the backend actually allows.*

### 22. Team — `/team`

**File:** `frontend/src/app/(app)/team/page.tsx`

**Purpose:** View the member roster, invite new teammates, change roles,
remove members, and manage pending invites.

**How to reach it:** Sidebar → Admin → "Team".

**Role visibility:** **Real, deliberate role-based hiding**, unlike every
screen in Groups 2–5. `canManage` (`role === "owner" || "admin"`, read from
the decoded JWT) gates:
- The "+ Invite Member" button — entirely absent for Data Engineer/Data
  Analyst/Viewer, not just disabled.
- The "Pending Invites" card — not rendered at all for non-managers, and its
  underlying query (`GET /team/invites`) is never even fired for them
  (`enabled: canManage`) — matches the backend's own restriction of that
  endpoint to Owner/Admin exactly.
- Per-member role editing — non-managers see a plain read-only badge instead
  of the `<Select>`; the "Actions" column (Remove button) is omitted
  entirely for them.
Every role, including Viewer, can still see the member roster itself
(name/email/role/status/joined) — matches `GET /team/members` being ungated
for any authenticated tenant member.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "+ Invite Member" button (Owner/Admin only) | Click | Opens the invite modal | — | — |
| Modal — Email + Role `<Select>` (defaults to Viewer) + "Send Invite" (disabled until email is non-empty) | Click | `POST /team/invites` `{email, role}` | The modal **does not close** — it switches to showing the created invite's manually-shareable link (`{origin}/invite/accept?token=...`), with an explicit note that Resend's sandbox can only actually deliver to the workspace owner's own address today, so this link may need to be shared by hand. A "Done" button closes it. | Danger toast with the real backend message (e.g. "This email is already a member of this workspace") |
| Member row — role `<Select>` (Owner/Admin only; disabled + tooltip if blocked) | Select | `PATCH /team/members/{id}/role` `{role}` — blocked (disabled, with the real reason as a tooltip) when: the target is an Owner and the caller isn't ("Only an owner can change an owner's role"), or the target is the last active Owner ("Cannot demote the last owner") — these client-side checks are computed from the same roster data already on the page and mirror the backend's actual guard, not an invented stricter rule | "Role updated." toast, roster refetches | Danger toast with the real backend error message (this mutation's error handler does surface `ApiError`'s real message, unlike most other screens' generic toasts) |
| Member row — "Remove" button (Owner/Admin only, shown only for currently-active members; disabled + tooltip if blocked) | Click | `DELETE /team/members/{id}` — **no confirmation dialog**, immediate. Blocked (disabled+tooltip) when: it's the caller's own row ("You can't remove yourself"), the target is an Owner and the caller isn't, or the target is the last active Owner. | "Member removed." toast, roster refetches — the row is **not** deleted from the table, it flips to a gray "Removed" status badge and its Actions disappear (soft-removal, matches the backend's `is_active=False`, not a hard delete) | Danger toast with the real backend message |
| Pending Invites row — "Revoke" button (shown only while `status === "pending"`) | Click | `DELETE /team/invites/{id}` | "Invite revoked." toast, list refetches | Generic "Failed to revoke invite." toast (this one does *not* surface the backend's real message, unlike the role/remove mutations above) |

**Empty states:** The member roster is never empty (every tenant has at least
one member). Pending Invites (managers only) with zero invites ever created →
"No invites yet."

**Known issues:** None beyond the already-documented, cross-referenced gap
that a removed member's still-valid JWT keeps working until it naturally
expires (`CLAUDE.md` Known-broken, "Removed/demoted team members keep full
access...") — this screen's own soft-removal behavior (row goes gray,
Actions disappear) is correct and working exactly as designed; the gap is in
session/token handling elsewhere, not in anything this screen does wrong.

---

### 23. Billing — `/billing`

**File:** `frontend/src/app/(app)/billing/page.tsx`

**Purpose:** View the current plan and this month's usage against its
limits, and (Owner/Admin) change plans.

**How to reach it:** Sidebar → Admin → "Billing".

**Role visibility:** Plan name and all 4 usage bars are visible to every
role (`GET /billing/usage` and `GET /billing/plan` are both ungated). The
plan-change `<Select>` + "Confirm change" control, and the exceeded-limit
warning beneath it, only render for Owner/Admin (`canManage`) — matches
`POST /billing/change-plan` being role-gated server-side.

**Interactive elements:**
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| "Change plan" `<Select>` (Owner/Admin only) | Select | Client-side only — populated from the real `GET /billing/plans` (public endpoint, not a hardcoded list, unlike the Settings AI Model tab) | If the newly-selected plan's real limits would already be exceeded by the tenant's *current* usage, a red warning appears immediately (computed client-side from data already loaded, no extra call): "Your current usage already exceeds {plan}'s limits for: {resources}. The change will still go through — existing usage is grandfathered, but any new usage of these will be blocked until you're back under the limit." **This is an honest reflection of real backend behavior, not an invented client-side rule** — the backend genuinely allows the downgrade unconditionally (see `CLAUDE.md`'s "`POST /billing/change-plan` executes real, unconditional plan changes..." Known-broken row) and this banner does not disable the Confirm button. | — |
| "Confirm change" button (disabled while pending, no plan selected, or the selection matches the current plan) | Click | `POST /billing/change-plan` `{plan}` | "Plan changed to {Name}." toast; both the plan card and usage bars refetch | Danger toast with the real backend message |
| Usage bars (4: AI Credits, Pipeline Runs, Data Sources, Team Members) | — | Read-only, from the already-fetched usage data. Colored by the backend's own real `status` field (`ok`→green, `warning`→yellow, `exceeded`→red) — **not recomputed client-side from the raw numbers**. A `null` limit (Scale tier's unlimited resources) shows "· Unlimited" and a full/inert bar rather than a percentage. | — | — |
| "Checkout & invoices" section | — | Fully static, zero API calls, zero fabricated data: "Coming soon — Stripe billing isn't wired up yet." | — | — |

**Empty states:** N/A — plan and usage data always exist for a real tenant.

**Known issues:** This screen's own copy is unusually transparent about a
real, already-documented backend gap rather than hiding it: the plan card
states outright "Plan changes take effect immediately — there's no payment
step yet (dev mode). This will change before launch," and the
exceeded-limit warning (above) discloses the unconditional-downgrade
behavior honestly instead of pretending to block it. See `CLAUDE.md`'s
Known-broken table for the two underlying gaps this screen is being honest
about: no payment gate at all, and no usage-based downgrade block.

---

### 24. Settings — `/settings`

**File:** `frontend/src/app/(app)/settings/page.tsx`

**Purpose:** Five tabs — Workspace (name/timezone/description), Notifications
(Slack/email alert routing), AI Model (per-tenant LLM override), Theme
(per-user light/dark/system), and API Keys (CRUD for platform API keys that
don't yet authenticate anything).

**How to reach it:** Sidebar → Admin → "Settings".

**Role visibility:** Mixed per tab, and correctly reflected in the UI:
- **Workspace, Notifications, AI Model**: read-only for Data Engineer/Data
  Analyst/Viewer (real current values shown, every input `disabled`, no Save
  button rendered, an explicit "Only owners and admins can change this — you
  have read-only access." notice) — matches `PATCH /settings/` being
  Owner/Admin-gated.
- **API Keys**: fully hidden behind a message ("Only owners and admins can
  view or manage API keys.") for other roles — and unlike the read-only
  pattern above, the underlying list query (`GET /api-keys/`) is never even
  fired for them (`enabled: canManage`), matching that endpoint being
  Owner/Admin-only server-side, not just its mutations.
- **Theme**: **no role gating at all** — every role can change their own
  theme, since it's a personal preference (`PATCH /auth/me` has no role
  requirement).

**Interactive elements:**

*Workspace tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Name / Timezone / Description inputs | Type (managers only — disabled otherwise) | — | — | — |
| "Save" button (managers only, disabled if saving or Name is empty) | Click | `PATCH /settings/` `{name, timezone, description}` | "Settings saved." toast, settings refetch (shared query backing this + Notifications + AI Model tabs) | "Failed to save settings." toast |

*Notifications tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Slack webhook URL / Alert email inputs, 4 "Notify on" checkboxes (Incident created / Pipeline failed / Deployment failed / Approval required) | Type/toggle (managers only) | — | — | — |
| "Save" button (managers only) | Click | `PATCH /settings/` `{notification_prefs: {slack_webhook_url, alert_email, notify_on}}` — **always sends the complete current state of all 4 toggles and both fields, not just what changed**; the backend's own deep-merge logic (documented in `CLAUDE.md` as handling a genuinely partial update correctly) is never actually exercised by this specific caller, since this form never sends a partial object | "Settings saved." toast, settings refetch | "Failed to save settings." toast |

*AI Model tab:*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Model `<Select>` ("Use plan default" / "Gemini 3.5 Flash" / "Llama 3.3 70B (Groq)") | Select (managers only) | This 2-entry list is hardcoded client-side, deliberately kept in manual sync with the backend's `SUPPORTED_MODEL_OVERRIDES` — already tracked as a known drift risk in `CLAUDE.md`'s Known-broken table, not a new finding here | — | — |
| "Save" button (managers only) | Click | `PATCH /settings/` `{ai_model_override: value \|\| null}` | "Settings saved." toast, refetch | "Failed to save settings." toast |

*Theme tab (no role gate):*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Light / Dark / System buttons (highlighted button reflects the current preference) | Click | Applies the new theme to the page **immediately and optimistically** (DOM attribute + `localStorage`) *before* the network call resolves, then `PATCH /auth/me` `{theme}` | "Theme updated." toast; the highlighted button updates to match (state only actually updates in the success handler) | "Failed to save theme preference." toast. **NEW FINDING**: because the theme was already applied optimistically before the call was even made, a failed save leaves the page visibly rendering the new theme (and `localStorage` already holding it) while the highlighted button reverts to reflecting the old value once `onError` — or doesn't update at all, since only `onSuccess` calls `setPref` — leaving the button selection and the actually-rendered theme out of sync until the next full reload. On that reload, the `(app)` shell's own server-reconciliation effect would pull the *old* value back from `GET /auth/me` (since the save never actually persisted), silently overwriting the just-applied `localStorage` choice back to the previous theme — a subtle, self-correcting-on-reload inconsistency, not a persistent bug. |
| "Currently rendering: Light/Dark" text | — | Read-only, resolves "System" to the OS's actual current preference via `matchMedia` for display purposes only | — | — |

*API Keys tab (managers only; others see a single restricted-access message):*
| Element | Action | Calls | On success | On failure |
|---|---|---|---|---|
| Explanatory text | — | States plainly: "API keys are for reference and audit today — nothing in AXIOM currently accepts one as a request credential. Authenticating requests with a key is planned but not yet built." — matches the real, current backend capability exactly (`CLAUDE.md`'s Not-yet-built list), no oversold copy | — | — |
| Key name input + "Create" button (disabled if empty) | Click | `POST /api-keys/` `{name}` | Opens a modal showing the real raw secret **exactly once**, with an explicit "won't be shown again" warning, a "Copy" button (writes to the clipboard), and "Done." The raw key lives only in local component state (`revealedKey`) — never written into the React Query cache, never logged, reset to `null` the moment the modal closes. List refetches in the background (masked shape only, `key_prefix`/timestamps, never the raw key). | "Failed to create API key." toast |
| Key row — "Revoke" button (shown only if not already revoked) | Click | `DELETE /api-keys/{id}` — no confirmation dialog | "Key revoked." toast, list refetches, row shows a gray "Revoked" badge in place of the button | "Failed to revoke key." toast |

**Empty states:** API Keys tab with none created yet → "No API keys yet."
Other tabs always have real current values to show (even if blank/unset).

**Known issues:**
- The Theme tab's optimistic-apply-before-confirm race (**NEW FINDING**,
  above) — minor and self-correcting, but real.
- AI Model allowlist drift risk — already tracked in `CLAUDE.md`, not new.
- API Keys' honest "not yet a real credential" copy is a positive example,
  not an issue — noted for contrast with less careful copy elsewhere.

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
- [x] **Group 4: Automations, CI/CD, Approvals, Analytics, Audit.** Automations
      is a documented, intentional Coming Soon stub. New findings logged (not
      fixed): Analytics and Audit Logs are *undocumented* stubs — real,
      working equivalents of both already exist (Dashboard for analytics,
      Governance's Audit Log tab for the audit trail) but the sidebar's
      dedicated top-level items for them are dead ends, which is confusing
      and not called out anywhere as a known Coming Soon item; CI/CD's
      `PATCH /cicd/incidents/{id}/resolve` endpoint has no frontend caller at
      all; the same role-gated-but-unhidden button pattern from Groups 2–3
      continues on CI/CD and Approvals.
- [x] **Group 5: AI Employees, Chat.** AI Employees matches its documented
      scope exactly, no findings. Chat has the single most consequential
      finding in this document (**NEW**): AXIOM's tool-calling path is gated
      only by `operation_mode` + a hardcoded risk tier, never by the calling
      user's role — a Viewer can have AXIOM execute, via chat, actions the
      same Viewer would be 403'd on through the normal UI, compounded by the
      already-documented "phantom high-risk tools" bug that leaves Autonomous
      mode gating almost nothing in practice. Also found a second stale
      Known-broken row in `CLAUDE.md` (`request_approval` tool marked broken
      but actually fixed and live-verified later in the same table) — same
      bookkeeping gap class as the two already cleaned up pre-walkthrough.
      Confirmed the WS chat auth gap, while real, is unreachable from any
      actual product screen.
- [x] **Group 6: Team, Billing, Settings (5 tabs).** All screens documented.
      These three (Phase 17) are the only screens in the app that correctly
      mirror backend role gates in the UI — a real, positive contrast to
      Groups 2–5's recurring pattern. One new finding: Settings' Theme tab
      applies a new theme optimistically (DOM + localStorage) before its
      `PATCH /auth/me` call resolves; on a failed save the button highlight
      and the actually-rendered theme can go out of sync until the next
      reload, which silently reverts to the server's old value. Billing's own
      copy is unusually transparent about its two known backend gaps (no
      payment gate, no usage-based downgrade block) rather than hiding them.
      **All 24 screens are now documented — screen coverage is complete.**
- [ ] End-to-end user flows
- [ ] Glossary
- [ ] Role-permission matrix
- [ ] Export to PDF
