# Wunomo — full frontend upgrade

Read this entire file before doing anything. It runs in phases. **Each phase
ends with you stopping and reporting.** Do not chain phases.

---

## 0. Standing rules

- Branch `feat/futurewave`, cut from master. Never commit to master.
- **Do not touch backend files. Do not touch `docs/context/`.** Another session
  is working the repo in parallel.
- **No Tailwind, no utility classes.** Hand-written CSS with design tokens.
  Every colour goes through the token layer. A hex outside the token file is a
  bug.
- **Never invent data.** Not in a component, a fixture, or a screenshot. If the
  demo tenant has three pipelines, the screen shows three pipelines. Sparse is
  the real state and it ships sparse. Design a real empty state instead.
- `design/futurewave-reference.html` is the approved **visual target**, not
  source. It is standalone HTML with inline CSS and hardcoded hexes — the
  opposite of this codebase. Match what it looks like; reimplement through
  tokens. Do not copy its CSS.
- Brand components live in `components/brand/`. They inherit `currentColor` and
  must never be given a hardcoded `fill`.

### Sequencing dependency — read this first

A parallel session is working an audit backlog whose batch 1 includes the
item 24 nav-domain mapping and deleting `AxiomFab.tsx`. Both land in
`navItems.tsx` and the sidebar, which **Phase 5 below also rewrites.**

Do not start Phase 5 until that IA work is merged. Restyle the settled
structure, not a moving one. If you reach Phase 5 and it hasn't merged, stop
and say so rather than working around it.

---

## 1. The two themes are different design languages

This is deliberate. Light mode is the Futurewave blue direction. Dark mode is
near-monochrome. They share structure, type, spacing, and motion — not palette.

### Light

| Role | Value | Notes |
|---|---|---|
| Accent fill | `#0056FF` | white label on it = **5.56:1** ✓ |
| Accent text/link | `#0056FF` | on white = **5.56:1** ✓ |
| Accent hover | `#0047D6` | |
| Accent subtle bg | `#E3E7FC` | |
| Deep ground | `#061024` | gradient terminus, footer |

### Dark — greyscale chrome

| Token | Value | Contrast on `#0A0A0B` |
|---|---|---|
| `--bg` | `#0A0A0B` | — |
| `--surface` | `#121214` | — |
| `--surface-raised` | `#1A1A1D` | — |
| `--border` | `#26262A` | — |
| `--border-hover` | `#3A3A40` | — |
| `--text` | `#F2F2F3` | **17.7:1** ✓ |
| `--text-muted` | `#9A9AA2` | **7.3:1** ✓ |
| `--text-subtle` | `#6E6E76` | **3.9:1** — large text and non-essential UI only, never body copy |

**Blue in dark mode appears in exactly two places:** the wordmark/monogram, and
the focus ring. Everything else in the chrome is greyscale. Buttons, active nav
state, links, hover states — all grey.

Blue used in dark is `#2277FF` (**4.86:1** on `#0A0A0B` ✓), **not** `#0056FF`,
which measures 3.56:1 there and fails AA. This distinction is load-bearing;
do not collapse the two blues into one token.

### Status colours survive in both themes — non-negotiable

The greyscale rule is for **chrome only**. Semantic state must stay chromatic
or the dense screens lose their primary signal. A failed pipeline cannot be
grey. Verified on `#0A0A0B`:

| State | Dark | Ratio |
|---|---|---|
| Success / passing | `#4ADE80` | 11.4:1 ✓ |
| Warning / degraded | `#FBBF24` | 12.9:1 ✓ |
| Error / failed / incident | `#F87171` | 7.2:1 ✓ |
| Running / in progress | `#9A9AA2` | 7.3:1 ✓ |

Never encode state by colour alone — every status needs an icon or a label
alongside it.

### Where gradients are allowed

**Yes:** public landing, login, signup, marketing, empty states, and a bounded
header strip at the top of a page.
**No:** behind tables, charts, chat transcripts, forms, or any dense data
region. Dark mode gets no gradient at all beyond a near-flat surface lift.

---

## 2. Typography

- Display: **Instrument Serif** via `next/font/google`. **Regular and italic
  only — no bold, no weight axis.** Never request 600 or 700; you'll get a
  synthesised faux bold. Use at 28px and above only.
- Body, UI, data: **Inter**. Everything under 28px, and anything needing weight
  emphasis.
- Numeric data keeps `font-variant-numeric: tabular-nums`.

---

## 3. Buttons — three tiers, not one

The requested treatment (bare text, border on hover) is correct for
**secondary and below**. It is wrong for primary actions: item 10 in
`docs/context/WALKTHROUGH_FINDINGS_2026-08.md` says buttons are too small **and
too low-contrast**, and a bare-text primary CTA makes the contrast worse while
fixing the size. Claude's own interface does the same split.

**Tier 1 — Primary. Solid fill.**
"Book a demo", "Send", "Run pipeline", "Save", "Create". Filled `#0056FF` in
light, filled `--text` on `--bg` (light-on-dark inversion) in dark. 52px tall,
white/inverted label. Hover deepens the fill and adds a soft shadow.

**Tier 2 — Secondary. Ghost with hover box.** *(the treatment you described)*
Transparent at rest, label only. On hover: 1px border in `--border-hover`, a
subtle background lift, no colour shift. Transition `--t-slow`, 280ms.
44px minimum height.

**Tier 3 — Tertiary / icon / nav.**
Same ghost-to-bordered behaviour, 44×44 minimum target even where the glyph is
16px.

**All tiers:** visible 2px focus ring at 2px offset, on keyboard focus only
(`:focus-visible`). In dark mode the focus ring is the one non-logo blue.

---

## PHASE 0 — Audit. Change nothing.

Report back:

1. Both theme blocks of the token file, verbatim.
2. Every consumer of `--accent`, grouped by: filled surface, text/link, border,
   icon, chart series, status indicator. **This is the blast radius.**
3. Whether one `--accent` token currently does both fill and text duty. If so,
   splitting it is the largest single job in this rollout.
4. Any component hardcoding a hex instead of using a token.
5. Current button component — sizes, variants, hover, focus.
6. Current login/signup layout and what it shares with the product shell.
7. `docs/SELF_TEST_GUIDE.md` — every section referencing literal button labels,
   colours, or UI states this work invalidates.
8. `docs/self_test_assets/` — all 9 screenshots, which go stale.
9. What the demo tenant actually contains: sources, pipelines, incidents,
   quality rules, chat history. This determines what screenshots can show.
10. Whether the parallel session's IA work has merged yet.

**Stop. Report. Wait.**

---

## PHASE 1 — Token layer only

- Both palettes into both theme blocks.
- Split accent into fill and text tokens if Phase 0 found them conflated.
- Add the greyscale dark scale.
- Add status tokens, chromatic in both themes.
- Gradient tokens for permitted surfaces only.
- Keep `--t-slow: 280ms` and existing easing — new motion must feel like it
  belongs with the sidebar's workspace/AXIOM crossfade.

Produce a **contrast table**: every foreground/background pair, ratio in both
themes, pass/fail against AA. Anything under 4.5:1 for body or 3:1 for large
gets fixed now, not later.

**Stop. Report the table.**

---

## PHASE 2 — Button system

Implement the three tiers above across the shared component. Then find and
convert every ad-hoc button in the codebase — there will be some. Report the
count.

This lands before any screen so there's one screenshot retake, not two.

**Stop. Report.**

---

## PHASE 3 — Login and signup

Split-screen, matching the reference: **left panel** carries the brand, **right
panel** carries the form.

Left, light mode: the Futurewave mesh, deepening to `#061024` at the base. Left,
dark mode: near-black with a subtle surface lift, no colour.
Both: the wordmark top-left, and a short line of copy set in **Instrument
Serif** — this is the only place in the product where the display serif appears,
and it's what visually ties the app to the landing page.

Right: `--surface`, form fields, primary CTA at Tier 1.

Write the copy line yourself from `docs/context/WUNOMO_MASTER_CONTEXT.md` — do
not invent positioning claims, customer counts, or logos. If the reference shows
"Trusted by 1000+ founders", that is not our claim and does not appear.

Mobile: panels stack, brand panel collapses to a header band.

**Stop. Show both themes.**

---

## PHASE 4 — Dashboard

One screen, so I can react before twenty more.

- New tokens applied. Keep the existing bento layout unless something broke.
- Header strip may carry a bounded gradient in light. Card region may not.
- Large numbers keep tabular-nums.
- Empty cards stay empty, with a designed empty state.
- Verify both themes before reporting.

**Stop. Show both themes.**

---

## PHASE 5 — Shell: sidebar and topbar

**Blocked until the parallel session's IA work has merged.** Confirm first.

- Sidebar items become Tier 3 buttons: ghost, hover reveals the bordered box.
- Preserve the two-mode workspace/AXIOM crossfade exactly, including `--t-slow`.
- Active state in dark mode is a grey surface lift plus a border, not a blue
  fill.
- Collapsed sidebar: the monogram **must not render below 32px** — it stops
  reading as a "w" and looks like a "u". Use the tiled treatment from
  `app/icon.svg` if you need it smaller.

**Stop. Report.**

---

## PHASE 6 — Remaining screens, in this order

1. AXIOM chat — the screen people stare at for hours, and the hardest test
2. Sources, Pipelines, Incidents — the dense tables, hardest legibility test
3. Quality, Governance, Analytics
4. Catalog, Transforms, Automations, CI-CD, Approvals
5. Settings, Billing, and everything remaining

Report after 1, after 2, and at the end. Both themes each time.

---

## PHASE 7 — Screenshots

Only when the product is done and approved.

- From the running app at `localhost:3000`, real demo tenant, nothing seeded,
  nothing edited into the image.
- 1440px viewport, 2× DPR.
- Dashboard and AXIOM chat in **dark theme** for the landing page — they sit on
  a blue gradient and dark reads better against it.
- Scrub names, emails, connection strings, tenant IDs.
- Retake the 9 stale `docs/self_test_assets/` screenshots in the same pass.
- Landing captures to `public/screenshots/`.

**Stop. Show me the captures before they go anywhere.**

---

## PHASE 8 — Landing page

- `src/app/page.tsx` is the only place in the codebase still rendering the
  brand as raw rasters: `<img src="/wunomo-mark.jpeg">` at **lines 78 and
  207**, `<img src="/wunomo-wordmark.png">` at **line 101**. This phase is
  where those three get swapped for `WunomoMark`/`WunomoWordmark` from
  `components/brand/`, and where `public/wunomo-mark.jpeg` and
  `public/wunomo-wordmark.png` get deleted once nothing renders them —
  confirmed by grep to be unreferenced anywhere else. Do not migrate or
  delete them earlier (Phase 2 and Phase 5 touch buttons and the shell, not
  the landing page).
- Hero matches `design/futurewave-reference.html`.
- **The wordmark bands are `position: absolute` inside the hero, which has
  `overflow: hidden`.** Never `position: fixed`, never on `<body>`. Every
  section below the hero gets an opaque background so nothing bleeds through.
- Implement the mesh as layered CSS `radial-gradient`s, **not** the reference's
  canvas. The canvas exists only so the reference could sample pixels for its
  contrast readout. CSS is correct for production.
  - **Then verify:** open the reference at 1440 / 1280 / 1024 / 768 and confirm
    your CSS reproduces the same stops. Report ratios at the darkest **and**
    lightest point behind the headline and behind the subhead, per width — not
    an average. Nothing lighter than `#0056FF` may sit behind body-size text.
- Phase 7 screenshots into the product frame.
- Footer: wordmark plus **"Wunomo is a product of Alpha Parallel."**
- `app/icon.svg`, `apple-icon.png`, `favicon.ico` go in **root `app/`**, not
  inside a route group — in a group they only apply to that group's routes and
  the workspace keeps the default favicon.
- Generate `app/opengraph-image.png` (1200×630) last.

---

## Motion

**Animate:** the two hero bands drifting a few percent over 64s and 78s (hero
only); button hover/focus at `--t-slow`; the sidebar crossfade (unchanged);
one hero fade on first load.

**Do not animate:** anything on data refresh, poll, or re-render; table rows;
chart redraws; chat message arrival; workspace route transitions; numbers
counting up.

**No animation library.** All of the above is CSS keyframes and transitions.
Do not add anime.js, Framer Motion, or GSAP — ~17KB gzipped for two drifts is
the wrong trade. If something later genuinely needs sequencing, we add it then.

Everything wraps in `@media (prefers-reduced-motion: no-preference)`. Under
reduced motion the bands are static and the page is fully usable.

---

## Definition of done

- No hardcoded hex outside the token file.
- Contrast table produced; every pair AA in both themes.
- Gradient-behind-text ratios reported at darkest and lightest point, per
  breakpoint.
- Status colour never the sole carrier of meaning.
- `prefers-reduced-motion` verified.
- Keyboard focus visible on every interactive element.
- Responsive to 375px.
- No new dependency in `package.json`.
- No backend file touched, no `docs/context/` touched, nothing on master.
