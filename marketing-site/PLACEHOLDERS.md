# Pre-deploy placeholder gate

Single checklist of every placeholder value in this app. All values below
are now real.

| Placeholder | File | Current value | Status |
|---|---|---|---|
| Cal.com booking link | `src/lib/config.ts` → `CAL_LINK` | `https://cal.com/wunomo/demo` | ✅ SET |
| WhatsApp — Pratyaksh Soni | `src/lib/config.ts` → `CONTACTS[0]` | `+91 77376 72577` | ✅ SET |
| WhatsApp — Daksh Gupta | `src/lib/config.ts` → `CONTACTS[1]` | `+91 94616 65538` | ✅ SET |
| Formspree form ID | `src/lib/config.ts` → `FORMSPREE_FORM_ID` | `mlgqqyon` | ✅ SET |
| Contact emails | `src/lib/config.ts` → `CONTACTS[*].email` | `pratyakshsoni2005@gmail.com`, `guptadaksh1509@gmail.com` | ✅ SET |

All config lives in one file (`src/lib/config.ts`) — nothing hardcodes any
of these values anywhere else (verified via grep).

**Config-level gate: cleared.**

## Deploy-readiness verdict (as of this file's last edit)

**Ready to deploy to a `*.vercel.app` preview URL.** Everything below was
verified live, not just read from source:

- Production build (`npm run build --turbopack`) is clean, zero errors,
  and the route is fully static-prerendered (`○ Static`) — no server-side
  data dependency of any kind.
- All 5 "Book a demo" CTAs resolve to `https://cal.com/wunomo/demo`
  (verified via `page.$$eval` against the rendered DOM), and that URL
  returns a real HTTP 200.
- Both WhatsApp links (`wa.me/917737672577`, `wa.me/919461665538`, each
  with the prefilled greeting) return real HTTP 200s.
- Both `mailto:` links have the correct addresses.
- The interest form was submitted for real against the live Formspree
  endpoint (`mlgqqyon`) via a headless browser — got a real success
  response and the on-page "Thanks — we got it" confirmation rendered.
  **A real test submission landed in the Formspree dashboard/inbox** —
  expected from this verification, not a bug; disregard it.
- `fonts.css` matches the product app's current version (content-diffed).
  **This is the one file in the "copy" list below actually safe to call
  aligned right now** — font files/weights haven't moved on either side.
- Confirmed the current dark-mode redesign values are present and in use:
  `--bg: #101015`, `--surface: #1B1B21`, `--text-primary: #F1F0E1` — not
  the old navy-on-black palette. **This was true when written; it no
  longer describes the product app's palette — see "Shared-file sync
  status" below.**
- All 6 font files (General Sans ×4 weights, Fraunces 600, JetBrains Mono
  500) load with real HTTP 200s and are genuinely `loaded` per the Font
  Loading API — identical behavior to the product app's own landing page,
  checked side by side. (Fraunces 500 and JetBrains Mono 400 show
  `unloaded` in both apps identically — that's correct, neither app's
  landing page ever renders text at those specific weights, so the browser
  never requests them; not an error.)
- Side-by-side screenshots (light + dark, both apps) confirm the same
  visual system — palette, type, spacing, card styling — with only the
  intended differences (branding/CTA copy).
- The one console error seen (`/_vercel/insights/script.js` → 404) is
  Vercel Analytics' own expected local-dev behavior — it has nothing to
  serve that script until the app is actually deployed on Vercel. Not a
  bug, resolves itself on real deployment.

**Not yet verified, because it requires the real Vercel/Cloudflare
environment**: HTTPS certificate issuance, the actual `wunomo.in` DNS
resolution, and Vercel Analytics actually recording a hit. These can only
be confirmed after deploying — see `DEPLOY.md`.

## Shared-file sync status

Three files in this app are **hand copies of a product-app source, kept
in sync by whoever last happened to port them — there is no build step,
package link, or CI check enforcing agreement.** This section exists so
that fact is stated once, plainly, instead of asserted-then-forgotten the
way the deploy-readiness verdict above did for months.

| File here | Copy of | Genuinely aligned right now? |
|---|---|---|
| `src/styles/fonts.css` | `dataops-agent/frontend/src/styles/fonts.css` | **Yes.** Same font files, same weights, same self-hosted approach on both sides — nothing has moved. |
| `src/styles/tokens.css` | `dataops-agent/frontend/src/styles/tokens.css` | **Yes, as of 2026-08-20** (branch `feat/futurewave-marketing`) — job-scoped accent split, greyscale dark, the semantic fill/text split, `--brand-blue`, the mesh ramp, `--deep-ground`, and the `--_dark-*` dedup pattern all ported, with real computed contrast values matching the product's own cited numbers exactly. Chart tokens, `--auth-brand-bg`, and the full `--sidebar-*` set deliberately not ported — this site has none of those consumers. **Will drift again the next time the product's tokens.css changes and nobody re-diffs** — this "Yes" is a snapshot, not a guarantee. |
| `src/styles/components.css` | `dataops-agent/frontend/src/styles/components.css` | **Partially, as of 2026-08-20.** This file used to be ported near-verbatim from the product's much larger component library; the 454 unreachable lines (729→275: sidebar/topbar/chat/auth/onboarding/etc — nothing this single-page site renders) were deleted, and every reachable rule using an old-palette value was repointed to the new tokens, cross-checked against the product's actual current values (not improvised). From this point on, treat this file as *this app's own*, not a mirror of the product's — porting a palette or a component pattern from the product should mean porting the relevant rule, not re-copying the whole file. **Known divergence, deliberate, not a gap**: this site does not use the product's three-tier button system (52px/44px minimum heights, `.btn-anchored`, unconditional 44×44 icon targets) — `.btn-primary` here keeps this site's own smaller proportions and gets a real `border-color` (`var(--accent-fill)`) rather than the product's `transparent`, which only makes sense inside that tier system. A future session should not "fix" this to match the product's button CSS more closely without deciding to adopt the tier system as a whole; half-porting it would be worse than the current, consistent divergence. |
| `src/lib/employees.ts` | `dataops-agent/frontend/src/lib/employees.ts` | **Unverified either way.** Mirrors the product's AI-employee roster copy by design (`employees.ts`'s own header comment says so) — nobody has re-diffed the two since this file was last written. If the roster copy changes on either side, the other won't know. |

**Nothing here is being fixed by adding a sync mechanism** — no shared
package, no build-time copy step, no CI diff check. That's a real,
deliberate choice this doc is recording, not proposing to change: the two
apps live on separate branches, deploy independently, and share no
runtime dependency by design (see `DEPLOY.md`'s "Not part of this task").
The cost of that choice is exactly what this table states — copies drift,
silently, until someone manually re-diffs them. Whoever next touches the
product's design tokens or the employee roster should know to check this
table, not trust that the copy is still current.

**Known shared leftover, logged once so it isn't rediscovered twice**:
`.landing-carousel-dot.active`, `.landing-contact-card:hover`'s
border-color, and `.input:focus`'s box-shadow are all still on the
pre-Futurewave `--ocean-*` primitives, **in both this file and the
product's own `components.css`** — the 2026-08-20 token port matched the
product's real current state on purpose rather than improvising a
different treatment, which means these three spots are consistent
between the two apps but not actually correct in either. Logged as item
64 in the product repo's `docs/context/WALKTHROUGH_FINDINGS_2026-08.md`
(on `master`, not visible from this branch's own `docs/` tree, which
predates that ledger) — check there before fixing, so a fix lands in
both `components.css` files at once rather than one at a time.
