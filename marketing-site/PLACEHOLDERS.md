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
- `tokens.css`/`fonts.css` are byte-identical to the product app's current
  versions (content-diffed, not just eyeballed — the only textual diff was
  a Windows CRLF line-ending artifact, confirmed via
  `diff --strip-trailing-cr`). `components.css` differs only by this app's
  own deliberate additions (hero pill, per-person contact cards, interest
  form layout) — nothing from the shared component styles was altered.
- Confirmed the current dark-mode redesign values are present and in use:
  `--bg: #101015`, `--surface: #1B1B21`, `--text-primary: #F1F0E1` — not
  the old navy-on-black palette.
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
