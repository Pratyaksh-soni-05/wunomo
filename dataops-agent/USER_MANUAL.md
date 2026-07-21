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

## Progress tracker

- [x] **Group 1: Landing & Authentication** — Landing, Login, Signup, Google
      callback, Onboarding, Invite accept. 2 new findings logged (both above,
      not yet fixed): the broken `/accept-invite` vs `/invite/accept` emailed
      link path, and invited members skipping onboarding.
- [ ] Group 2: Dashboard, Sources, Catalog, Pipelines
- [ ] Group 3: Transforms, Quality, Incidents, Governance
- [ ] Group 4: Automations, CI/CD, Approvals, Analytics, Audit
- [ ] Group 5: AI Employees, Chat
- [ ] Group 6: Team, Billing, Settings (5 tabs)
- [ ] End-to-end user flows
- [ ] Glossary
- [ ] Role-permission matrix
- [ ] Export to PDF
