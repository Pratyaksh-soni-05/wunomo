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

**Tier 1 exception — input-anchored buttons (added 2026-08-19, Correction 1):**
a Tier 1 button sitting inline with the field it submits — the chat composer's
Send button, a search bar's inline submit, anything in that shape — matches
the height of that field instead of the standalone 52px, floored at 44px. A
Send button taller than the textarea beside it is worse than the original
too-small complaint. Implemented as a `.btn-anchored` modifier
(`.btn-anchored.btn-primary` etc.) rather than reusing plain `.btn-sm`, since
`.btn-sm` also covers the dense-table row actions (Approve/Reject/Delete/
Resolve) that are deliberately **not** this exception — those stay at 52px
until Phase 6 decides how to handle table-row density (see that phase's note
below). Don't use `.btn-anchored` outside a genuine input-adjacent context.

**Tier 2 — Secondary. Ghost with hover box.** *(the treatment you described)*
Transparent at rest, label only. On hover: 1px border in `--border-hover`, a
subtle background lift, no colour shift. Transition `--t-slow`, 280ms.
44px minimum height.

**Tier 3 — Tertiary / icon / nav.**
Same ghost-to-bordered behaviour, 44×44 minimum target even where the glyph is
16px.

**Tier 3 exception — glyphs inside something smaller than 44px (added
2026-08-19, Correction 2):** two real cases can't take a 44px control without
breaking their own container — the ✕ inside `.chat-context-chip` (a 4px-padded
pill) and the hover-reveal ✕ on a chat session/saved-prompt row (would blow
out every row in the list to fit it). Both are deliberate, reasoned
exceptions, not oversights — do not "fix" them to 44×44 later. Instead they
get a **minimum 24×24 hit area** via padding/a pseudo-element that extends the
clickable region beyond the visible glyph, without changing visible layout —
`.chat-context-chip button`/`.chat-session-delete`/`.chat-saved-prompt-remove`
each carry `padding: 4px` (glyph is ~14-16px, so the hit area comes out to
~22-24px) and `margin: -4px` to pull that padding out of the visual flow so
the surrounding chip/row doesn't grow.

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

## PHASE 1 — Token layer, rename/split only. No palette values change.

Split by job — same computed colour, new name, so a future change to one job
(e.g. retuning the link colour) can't silently move an unrelated one (e.g. the
chart line beside it). This phase is a refactor, not a restyle: if a screen
looks different after it, something went wrong.

- Fill tokens (filled surface with a label on top)
- Text/link tokens (will need to satisfy AA against `--surface`/`--bg` — that
  check happens in 1b, once the real palette is in; don't chase it here)
- Border tokens
- Chart-series tokens (only need to read distinctly next to the
  success/warning/danger lines beside them — a different constraint than
  text/link, never conflate the two)
- Focus-ring token
- Fold in any hardcoded hex/rgba found in Phase 0's Q4 into a real token too,
  same value, just named.
- Collapse any hand-duplicated dark-mode block into a single source of
  truth if the file has one (private tokens the two dark entry points both
  reference, not two independently-typed literal lists).

**Stop. Report the diff summary.**

---

## PHASE 1b — The actual palette, plus the accessibility fixes it surfaces

*(Split out 2026-08-19 — the original Phase 1 above conflated "both palettes
into both theme blocks" with "split accent into fill and text tokens," which
are two different jobs done for two different reasons. Do 1 first, always;
its whole value is that nothing visually changes. Then 1b lands the real
Futurewave colours into the names 1 created, and now genuinely changes what
things look like — that's expected here, not a sign 1 was done wrong.)*

- Land the real palette (light: Futurewave blue direction; dark: greyscale
  chrome, blue only on the wordmark/monogram and the focus ring, semantic
  status stays chromatic in both themes) into the job-scoped tokens Phase 1
  created.
- Split each semantic status token (`--success`/`--warning`/`--danger`/
  `--info`) into a **text/icon** value (4.5:1 against `--surface`/`--bg`) and
  a **fill** value (4.5:1 against `--on-dark`, the label sitting on it) —
  same reasoning as Phase 1's accent split, just applied to the semantic
  scale instead of the brand scale. A fill/text pair that turns out to
  already share one working value doesn't need two different hexes; a pair
  that doesn't (e.g. `--warning` vs `.toast.warning`'s existing `#b45309`)
  needs two names regardless.
- Fix every AA failure the resulting contrast table finds **before** moving
  on, not deferred to whichever later phase happens to touch that screen —
  badges in particular, since dark mode's translucent badge fills measure
  around 1.1–1.2:1 (effectively invisible text), the same defect class as
  the dark-mode retokenisation this whole rollout started from.
- Produce the **contrast table**: every foreground/background pair, ratio in
  both themes, real composited value for anything translucent (not an
  estimate), pass/fail against AA. Anything under 4.5:1 body / 3:1 large
  gets fixed now.
- Confirm status is never colour-only: every badge and status dot needs an
  icon or text label riding alongside the colour, not instead of one.

**Resolved after the table was reported (2026-08-19 decisions), not left to
Phase 2/5 after all:**
- `--accent-fill` in dark mode goes **light-on-dark**, not blue and not grey:
  `--text-primary` fill (`#F2F2F3`) with `--on-accent-fill` (`--bg`, `#0A0A0B`,
  17.7:1) as the label, `--accent-fill-hover` → `#FFFFFF`. Applies to every
  consumer: `.btn-primary`, `.chip-selected`, `.chat-avatar`,
  `.chat-bubble-user-inner`, the base `.toast`, `.auth-brand` (whose secondary
  tagline text — `--on-accent-text` — gets its own dark override,
  `--border-hover`/`#3A3A40`, 10.1:1 on the now-light fill; the light-mode
  `--midnight-100` value would be near-invisible there). `--sidebar-bg` was
  never actually aliased to `--accent-fill` (it's `var(--midnight-700)`,
  independent since before Phase 1) — confirmed and commented defensively in
  the token file so a future edit doesn't accidentally wire them together;
  the sidebar stays untouched until Phase 5 regardless.
- `--accent-subtle-bg` is now wired: `tr.selected`, `.cmd-item:hover/.selected`,
  `.notif-item.unread`, `.credits-badge`, `.chat-context-chip` (were
  `--ocean-50`/`--ocean-100`). Dark value is an opaque low-lift grey
  (`--surface-hover`), not a translucent blue tint — the same fix class as
  the badges. A paired `--accent-subtle-border` was added for the two
  consumers that had a border (`--ocean-100` light / `--border` dark),
  otherwise a grey dark chip would’ve kept a blue-tinted edge.

**Still deferred to Phase 5 (sidebar/shell), not forgotten:**
- `Sidebar.tsx:120`'s `stroke="rgba(255,255,255,0.4)"` and `Sidebar.tsx:167`'s
  `border: "1.5px solid rgba(255,255,255,0.2)"` — two inline JSX literals,
  left alone on purpose since Phase 5 is already touching this file's markup.
- `.sidebar-item.active`/`.badge-count.badge-live`/`.input:focus`'s shadow
  still derive from `--ocean-500`, not the new accent blue — same reasoning,
  Phase 5's to reconcile.

**Chart-series distinctness — noted, not fixed (2026-08-19):** `--chart-accent`
measures 1.05–1.30:1 against the new success/warning/danger text colours in
both themes — similar luminance, different hue. Fine for typical colour
vision, a problem for colourblind viewers or a greyscale render. Not fixed
because `--chart-accent` doesn't currently share a canvas with any status
colour — `RunHistoryChart` pairs success+danger together (no blue line),
`QualityTrendChart` uses `--chart-accent` alone, `KpiCard` sparklines are
isolated single-series widgets. Whoever builds a chart that combines them
should pick a chart-accent hue with a real luminance gap from whichever
status colour rides beside it, not just a different hue at the same
lightness — this is waiting for them, not decided here.

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

**Queued from Phase 2 (Correction 4, 2026-08-19) — decide, don't rediscover:**
every dense table's row actions (Sources/Pipelines/Quality/Incidents/
Governance/Team/Settings/CI-CD/Approvals/Tasks — Trigger, Pause, Delete,
Approve, Reject, Resolve, Revoke...) are 2-3 `.btn-sm` buttons per row, and
Tier 1 (danger/success) has no size-modifier escape from its 52px floor, nor
does Tier 2/3's 44px. Every one of these rows has already grown. Item 2 above
is exactly where this has to get resolved — pick one, deliberately: taller
rows (simplest, costs vertical density), an overflow/kebab menu (reclaims
density, costs a click), or icon-only actions with tooltips (reclaims width,
costs discoverability). Whichever screen goes first sets the pattern for the
rest of item 2's list, so decide it once, not per-screen.

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
