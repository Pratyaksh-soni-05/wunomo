# Futurewave Design Tokens — Handoff

Purpose: let a separate session (marketing-site or otherwise) reuse this
product's verified design system without re-deriving anything already
established here. Every value and ratio below is either copied directly from
`dataops-agent/frontend/src/styles/tokens.css` (the single source of truth —
if this doc and that file ever disagree, the file wins) or a fact already
measured and recorded during this rollout (`docs/context/
WALKTHROUGH_FINDINGS_2026-08.md`, `docs/context/SESSION_LOG.md`). Nothing
here is new work — it's a compiled reference.

---

## 1. Theming mechanism

Three states, not two — this matters for anyone porting the palette:

- An explicit user choice stamps `data-theme="dark"` or `data-theme="light"`
  on `<html>`.
- No explicit choice (`data-theme` absent) falls through to
  `@media (prefers-color-scheme: dark)`, scoped as
  `:root:not([data-theme="light"])` so an explicit light choice always wins
  over the OS preference.
- Dark-mode literal values are defined **once**, as private `--_dark-*`
  tokens on `:root`; both dark entry points (`[data-theme="dark"]` and the
  `@media` fallback) just re-point the public token names at those same
  `--_dark-*` values. If you're porting this system elsewhere, keep that
  dedup — it's what stops the two dark blocks from drifting apart, and they
  already drifted once (item 54) when only one of two component-level rules
  citing the same idea got updated.

## 2. Full token tables

### Surfaces & borders

**Light values corrected 2026-08-20/21.** The Futurewave rollout landed
2026-08-19 but never actually touched these five tokens — light mode kept
running on the old Pearl Perfect cream (`--bg: #FBF9E4`, `--surface:
#FFFEF5`, etc.) underneath everything else that shipped, which is why the
live product still read as "the old palette" regardless. If you ported the
cream values from an earlier copy of this doc, they were wrong from the
start of the Futurewave rollout, not a later regression — replace them.
Dark mode was already correct and is untouched here.

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#F7F8FC` | `#0A0A0B` |
| `--surface` | `#FFFFFF` | `#121214` |
| `--surface-hover` | `#EEF1FA` | `#1A1A1D` |
| `--border` | `#E3E7FC` | `#26262A` |
| `--border-strong` | `#C9D2EE` | `#3A3A40` |

### Text

| Token | Light | Dark | Contrast (dark, vs `--_dark-bg`) |
|---|---|---|---|
| `--text-primary` | `#16233A` | `#F2F2F3` | 17.689:1 |
| `--text-secondary` | `#3A4A63` | `#9A9AA2` | 7.085:1 |
| `--text-muted` | `#6B7C94` | `#6E6E76` | 3.916:1 — **large text / non-essential UI only, never body copy.** Deliberately fails the 4.5:1 body floor; only clears the 3:1 large-text/UI-chrome bar. |
| `--text-disabled` | `#A7B4C4` | `#5A5A66` | — |
| `--on-dark` | `#FFFFFF` (both themes, constant — corrected from the cream `#FFFEF5` alongside the surfaces above) | same | Text painted on a permanently-dark surface (primary buttons, toasts, tooltips) — deliberately **not** the same token as `--surface`, which flips per theme. Conflating the two caused dark-text-on-dark primary buttons in an earlier phase; keep them separate. |

### Accent (brand blue)

| Token | Light | Dark | Notes |
|---|---|---|---|
| `--accent-fill` | `#0056FF` | `var(--text-primary)` (`#F2F2F3`) | **Dark mode inverts this to light-on-dark, not blue.** Blue is reserved for exactly the wordmark/monogram and the focus ring in dark mode — every other accent-fill consumer (primary buttons, chips, chat bubbles, toasts) goes grey-on-dark instead. This is a deliberate brand rule, not a fallback. |
| `--accent-fill-hover` | `#0047D6` | `#FFFFFF` | |
| `--accent-text` | `#0056FF` (5.496:1/surface, 5.238:1/bg) | `var(--text-secondary)` (grey, not blue — same "blue only for wordmark/focus-ring" rule) | |
| `--focus-ring` | `#0056FF` | `#2277FF` | **The two are not interchangeable.** `#0056FF` measures only 3.558:1 against dark surfaces — fails AA. `#2277FF` measures 4.854:1 on `--_dark-bg`, 4.589:1 on `--_dark-surface`. Always use the token, never hardcode either hex, or you will eventually put the light value somewhere dark. |
| `--brand-blue` | tracks `--focus-ring` (same value) | tracks `--focus-ring` (same value) | The general-purpose "real accent colour, verified safe in both themes" token — added for item 54's near-black-ceiling fix (see §4 below). Use this, not a fresh hex, whenever you need "the blue" and don't have a more specific token in mind. |

### Semantic status (success / warning / danger / info)

Each has a **text/icon** value (theme-varying, AA-verified against
`--surface`/`--bg`) and a **fill** value (theme-invariant, verified against
`--on-dark`) — these are deliberately two different tokens, not one reused
for both jobs. A single shared hue for each status failed AA as plain text
in at least one theme, and separately failed hard as a fill holding
`--on-dark` text (as low as ~3.26:1) — that's why the split exists.

| Status | Light text/icon | Dark text/icon | Fill (both themes) | Fill contrast on `--on-dark` |
|---|---|---|---|---|
| Success | `#15803d` (4.955:1/surface) | `#4ADE80` (9.965:1/surface-hover) | `#15803d` | 4.955:1 |
| Warning | `#92400e` (7.005:1/surface) | `#FBBF24` (10.401:1/surface-hover) | `#b45309` | 4.961:1 |
| Danger | `#c81e1e` (5.668:1/surface) | `#F87171` (6.277:1/surface-hover) | `#dc2626` | 4.771:1 |
| Info | `#0e7490` (5.293:1/surface) | `#22D3EE` (9.608:1/surface-hover) | `#0e7490` | 5.293:1 |

Status **badge/chip backgrounds** in dark mode are opaque
(`var(--_dark-surface-hover)`), not a translucent same-hue tint — a
translucent same-hue tile under the bright text measured ~1.1–1.2:1,
effectively invisible. If porting a status badge, use an opaque neutral
chip behind the bright text, not a colour-matched translucent one.

### Chart

| Token | Light | Dark | Notes |
|---|---|---|---|
| `--chart-accent` | `#4C76A0` (Ocean-600) | `#8FB0D0` (lightened for dark legibility) | Deliberately **not** on the Futurewave accent blue — a chart line has no AA text obligation, so this stayed on the older Ocean primitive scale. |
| `--chart-grid` | `rgba(107,124,148,0.15)` (both themes, invariant) | same | |
| `--chart-accent-fill-a12` | `color-mix(in srgb, var(--ocean-500) 12%, transparent)` | same mechanism | Area-fill under a chart-accent line. |

**Known, verified fact, not yet contradicted anywhere in the app**:
`--chart-accent` and any status colour (`--success`/`--warning`/`--danger`/
`--info`) measure only **1.05–1.30:1 luminance separation** from each other
— if a chart ever plots both on the same canvas, they will not read as
distinct series. This has been safe so far only because nothing in the
shipped app puts them together (confirmed 2026-08-19, Phase 6 items 3-5's
audit: the only chart code in the app, `TrendCharts.tsx`, either combines
two status colours together or uses chart-accent alone, never chart-accent
+ status). **If you build a chart anywhere — this product or a marketing
site reusing these tokens — that combines a chart-accent line with a status
line, budget for a real distinctness check before shipping it; don't assume
this pairing is safe just because the tokens exist.**

### Code / monospace surfaces

There is **no `--code-comment` custom property.** What exists is a CSS
class, `.code-comment` (and `.code-block::placeholder`), which reaches
`var(--midnight-300)` directly:

```css
.code-block { background: var(--midnight-900); color: var(--on-dark); }
.code-comment { color: var(--midnight-300); }
```

`--midnight-900` (`#0A1B30`) and `--midnight-300` (`#6A8FB8`) are both
**theme-invariant** — the code-block surface stays the same dark navy in
both light and dark app themes (it's a code editor, not a themed
surface). **Verified ratio: `--midnight-300` vs `--midnight-900` = 5.14:1**
— passes, in both themes, since neither value changes with theme. If you
reuse this pairing, don't re-derive that number; it's already measured.

### Sidebar (always-dark chrome)

The sidebar is a permanently-dark nav spine regardless of the overall app
theme — not a themed surface that happens to look dark. Light-mode app theme
→ `--sidebar-bg: var(--deep-ground)` (`#061024`, the same "dark brand
chrome" navy as the auth panel). Dark-mode app theme → `--sidebar-bg:
var(--bg)` (`#0A0A0B`, matching the rest of the dark app). Either way, this
means **every sidebar text/icon/state token needs to satisfy contrast
against a near-black surface, unconditionally** — see §4 below, this is
exactly the surface class the near-black-ceiling rule exists for.

| Token | Value | Notes |
|---|---|---|
| `--sidebar-text` | `rgba(255,255,255,0.62)` | Theme-invariant |
| `--sidebar-text-hover` | `rgba(255,255,255,0.9)` | |
| `--sidebar-text-faint` | `rgba(255,255,255,0.55)` | Raised from 0.3 (2.58:1) to clear 4.5:1 (5.29:1) — a real, deliberate contrast fix, not the original design intent |
| `--sidebar-footer-text-muted` | `rgba(255,255,255,0.6)` | Raised from 0.38 (3.30:1) to 5.99:1, same reasoning |
| `--sidebar-hover-bg` | `rgba(255,255,255,0.08)` | |
| `--sidebar-hairline` | `rgba(255,255,255,0.06)` | |
| `--sidebar-active-bg` | `color-mix(in srgb, var(--accent-fill) 40%, transparent)` (light) / `var(--surface-hover)` (dark) | Fill only — see §4, this alone does **not** carry the "active" signal in dark mode |
| `--sidebar-active-border` | `var(--accent-fill)` (light, 3.41:1 vs `--deep-ground`) / `var(--brand-blue)` (dark, fixed 2026-08-19) | Feeds a left-edge box-shadow bar in components.css, not a full-perimeter border — see §4 |

### Shadows, radius, layout, type

Theme-invariant except shadow opacity (darker/stronger in dark mode).
Not reproduced in full here — copy directly from `tokens.css` lines
226–253 and 288–292 if needed; nothing there has a contrast implication
worth restating.

## 3. Button tier system

Three tiers, one shared base:

- **Tier 1** (`.btn-primary` / `.btn-danger` / `.btn-success`): solid fill,
  **52px minimum height**, no size-modifier escape from that floor.
  `.btn-anchored` is the one sanctioned exception — a Tier 1 button anchored
  inline to an input it submits (not a standalone page CTA) matches that
  field's height instead, 44px floor either way.
- **Tier 2** (`.btn-secondary` / `.btn-ghost`): transparent at rest, a 1px
  border and a subtle background lift appear on hover — never a colour
  shift on the label itself. **44px minimum height.**
- **Tier 3** (`.btn-icon`): icon-only, same hover language as Tier 2, but
  **enforces a 44×44 target unconditionally** — `.btn-icon.btn-sm` does
  **not** get a size-modifier escape hatch, on purpose (a small icon glyph
  inside a 44×44 hit target is fine; a smaller hit target is not).

`.btn-secondary` and `.btn-ghost` intentionally share one visual treatment —
this was a deliberate convergence, not an oversight (neither the old
"visible border at rest" secondary nor a colour-shifting ghost matched the
actual Tier 2 spec, so both variant names now point at the same rules).

**Landing pages run a second, separate sizing scheme (2026-08-21) — don't
conflate it with the Tier system above.** The two above apply to the
authenticated app; `design/futurewave-reference.html`'s own button spec is
slightly different (44px default including Tier-2-equivalents, not just a
44px floor with Tier 1 always at 52px) and both landing pages now match it
via a `.landing-page`-scoped override, never by editing the base
`.btn`/`.btn-primary` rules above:

```css
.landing-page .btn { min-height: 44px; padding: 0 20px; font-size: 14px; font-weight: 550; border-radius: 9px; }
.landing-page .btn-lg { min-height: 52px; padding: 0 30px; font-size: 15.5px; } /* Tier-1-standalone only: hero CTA, final-CTA */
```

Marketing-site has no authenticated app to carve out (the whole site is
landing pages), so the same `.landing-page`-scoped pattern is used there
too, for parity, even though it could have gone on the base rules directly.
One real conflict, adapted rather than forced, same in both repos: the
logged-out/only nav (full cursive wordmark, ~245px wide at 26px tall, plus
theme toggle plus one or two 44px buttons) doesn't fit its own content
below ~480px. Product drops the secondary "Log in" link and the toggle at
that width; marketing (no secondary link to drop) drops just the toggle.
Both shrink the wordmark to 20px tall there. Report only, not a rule to
generalize — the wordmark's fixed aspect ratio is what makes this tight,
not the button spec itself.

## 4. The near-black-ceiling rule (amended, current version — read this, not an earlier draft)

**On a near-black surface (`#061024`/`#0A0A0B`-class — `--deep-ground`,
`--bg`), no subtle background tint reaches 3:1 contrast.** This isn't a bug
in any one component's tokens — it's what the contrast math does this close
to true black. White at 25% alpha only hits 2.14:1; a 50%-alpha accent fill
over `--deep-ground` only hits 1.71:1.

This rule was given wrong **twice** before landing on the version below —
both failures are real, measured, and worth understanding if you're porting
this pattern rather than just the conclusion:

1. **First attempt: chase fill contrast harder.** Doesn't work — the fill
   itself can't reach 3:1 this close to black without stopping being subtle
   and becoming a visible box.
2. **Second attempt (the original §4, before this amendment): "rely on a
   solid border instead of the fill."** This sounds right but isn't
   sufficient on its own — `tr.selected`'s first implementation used a
   *neutral grey* border (`--accent-subtle-border`, drawn from the same
   near-black colour family as everything around it) and measured **1.15:1
   against its own fill, 1.24:1 against the page surface** — still
   invisible, just moved from fill to border without checking the border
   itself also needed a real distinct colour. The same mistake was
   independently made in two more places before it was caught everywhere:
   `.sidebar-item.active` (1.75:1 border-vs-base, 1.04:1 fill-vs-hover) and
   `.chat-session-item.active` (1.24:1 border-vs-base) — both built earlier
   in this rollout, both citing the same original rule, both wrong the same
   way. All three fixed the same day, once the pattern was understood.

**The corrected rule — use this version:** a selection/active-state marker
on a near-black surface needs **(a)** a real, saturated, out-of-family
accent colour — never a neutral grey pulled from the same dark palette as
the surface around it — **and (b)** a shape structurally distinct from
whatever lines already exist on that surface. A full 1px border competes
with a table's existing row dividers, or a nav item's own resting border,
and reads as noise, not signal, even in the right colour. **What actually
works, verified live at 100% zoom with a real hovered element beside a real
active one, three times independently:** a solid 3–4px edge bar on the
element's leading edge only —

```css
/* the pattern, generalized from tr.selected / .sidebar-item.active /
   .chat-session-item.active */
.your-selected-state {
  background: var(--your-subtle-fill); /* quiet reinforcement, not load-bearing */
  box-shadow: inset 3px 0 0 var(--brand-blue); /* this is what actually carries the signal */
  color: var(--text-primary); /* text brightening, the other half of the original rule, still correct */
}
```

A 1px border at full opacity in the real accent colour would likely also
satisfy (a) and (b) — the edge-bar shape is the belt-and-suspenders version
that's actually shipped, not the only valid implementation.

**Independent supporting evidence this is the natural answer, not a patch
bolted on after two failures**: the Tasks detail page's failed-step banner
(built earlier, unrelated to this fix, never itself broken) already renders
a left-edge coloured bar driven by a dynamic token reference
(`` `var(--${reason.variant})` ``) to make a failure state read clearly.
Someone reached for the same shape-over-tint answer, independently, for a
different problem. Two people arriving at the same shape for two different
near-black legibility problems is a real signal this generalizes, not
coincidence.

Full measured evidence for all three fixes: `docs/context/
WALKTHROUGH_FINDINGS_2026-08.md` item 54 and its Tasks-banner precedent
note; the amendment's original landing point in
`design/CLAUDE_CODE_BRIEF_full_frontend.md` §4.

## 5. Text over a gradient carries its own scrim — a second instance of §4's lesson, found in the landing hero

**Headline vs. subhead is a different contrast bar, not the same one — get
this right first, before anything else in this section.** The headline is
large text (≥24px, or ≥18.66px bold) under WCAG, which needs **3:1**, not
4.5:1. Only the subhead (body-sized copy) needs **4.5:1**. This distinction
was gotten wrong once during this rollout — the scrim was tuned only to the
subhead's 4.5:1 target, and the headline, which actually has a *lower* bar
to clear, still failed anyway (2.68:1 at one intermediate scrim value)
because the mesh's pale patches happened to sit worse under the headline
specifically. Getting the threshold backwards costs a full unnecessary round
of "strengthen the scrim until the wrong number passes" — check which
element needs which ratio before tuning anything.

**CSS-vs-canvas layer-order trap, found restoring this mesh from the
reference (2026-08-20) — state this plainly so it isn't rediscovered:** CSS
`background-image` with multiple comma-separated layers paints the
**first-listed layer on top**. A `<canvas>` compositing sequence (like
`design/futurewave-reference.html`'s own blob-drawing code) paints in
**array order, each later call over the earlier ones** — last-drawn is
topmost. These are opposite conventions. Porting a canvas blob list
straight into a CSS `background-image` list, in the same order, silently
inverts the stacking — the blob meant to sit on top ends up on the bottom.
This is exactly what happened here: the mesh read as a flat, washed-out
horizontal band instead of the reference's diagonal composition, because
the CSS list was in the canvas's paint order instead of its reverse. Fix:
when porting any canvas-drawn composition to CSS `background-image`,
**reverse the layer list.** `components.css`'s `.landing-hero-mesh` keeps
each blob numbered in a comment (matching the reference's own array order)
specifically so this is checkable at a glance, not just asserted.

`.landing-hero`'s mesh background (§2's `--mesh-*` tokens) was verified
numerically — worst-case 6.04:1 for white text across the whole 22%–82%
text zone, aspect-independent by construction — and still failed in the
built page, at every breakpoint, because **the content sitting on top of
that gradient doesn't obey the same percentage math the gradient does.**
Nav height and badge height are fixed-pixel; the hero's total height (and
so every percentage-based gradient stop) changes with viewport. The two
drift against each other. Measured: the headline's own top edge landed
anywhere from 19.8% to 22.4% of hero height depending on breakpoint — never
reliably inside the "safe" 22%+ zone the gradient math assumed, so its
worst-sampled point kept catching the tail of a blob the mesh's own numbers
said shouldn't reach that far.

**This is the same lesson as §4's near-black-ceiling rule, in a different
shape: don't depend on a background you don't control at the exact point
text actually sits.** §4's fix was a shape (an edge bar) that reads
regardless of the surface under it. This fix is the direct analogue for
body copy sitting over a large decorative gradient: **give the text its
own background layer that travels with it**, sized to the text's real box
via CSS Grid stacking (two elements sharing one `grid-area`, so the scrim
auto-sizes to whatever the text naturally occupies — no JS measurement,
no guessed percentage), rather than trusting a percentage-of-container
zone to still be dark wherever the content stack happens to land that day.

```css
.text-wrap { display: grid; } /* shrink-wraps to its content */
.text-wrap .scrim { grid-area: 1 / 1; /* sits behind, sized to the text's own box */ }
.text-wrap .visible-text { grid-area: 1 / 1; /* the real content, stacked on top */ }
```

**Two things this cost real debugging time to learn, worth carrying
forward:**
- **General rule, not a Phase-8 anecdote: a shrink-wrapped container puts
  its widest line exactly where any edge-fade is weakest.** Any element
  sized to fit its content — a scrim, a card, a highlight box, a badge —
  shrinks until its box edge touches its longest line/widest glyph run.
  If that same box also carries a fade-to-transparent edge (a radial-
  gradient scrim, a soft drop shadow used as a floor, a vignette), the
  fade's weakest point and the text's own edge land in the same place by
  construction — not by bad luck, and not specific to this hero. **This
  applies to every text-over-gradient layout in this codebase and beyond,
  not just `.landing-hero-scrim`.** The fix is always the same: give the
  shrink-wrapped box real padding beyond its tightest content bounds (this
  build uses `clamp(32px,6vh,64px) clamp(60px,9vw,140px)` on
  `.landing-hero-content-visible`) so the fade happens *outside* where the
  glyphs are, not at them. **The marketing site will hit this on its own
  first gradient-backed hero or section** — check for it there before
  shipping, don't wait to rediscover it the same way this build did.
- **A contrast-sampling script that screenshots a text element and reads
  its own pixels will sample the text's own glyph colour, not the
  background behind it, wherever a rendered pixel happens to be inside a
  character's ink.** This produced a false "1.00:1, pure white" reading at
  every breakpoint that had nothing to do with the actual background — the
  sampled "lightest point" was a white pixel *of the letter itself*. The
  reference file's own probe avoids this by sampling its underlying canvas
  directly, never the text DOM node's rendered output; this codebase's CSS
  mesh has no such canvas, so the correct technique is to temporarily set
  the text (and its descendants — `<em>`/`<b>` carry their own computed
  colour) to `color: transparent` before sampling, then restore it. Any
  contrast script written against a CSS (non-canvas) text-on-gradient
  layout needs this, or its numbers cannot be trusted.

**Scrim/ramp history, in order — read this before touching either value
again:**

1. Original ship: **25%/14%** scrim, worst-case cleared 4.5:1 by 1.7–2.8×.
2. 2026-08-20, mesh restored to the reference's real diagonal composition
   (§ layer-order fix above): the corrected mesh's pale patches reach
   further into the text zone than the old flat-band version did. 25%/14%
   now failed. Raised to 50%/30% — still failed (headline 2.68:1 against a
   3:1 bar, subhead 4.44:1 against 4.5:1). Raised again to **66%/42%** —
   passed, but read as a visible dark rectangle sitting over the mesh
   rather than an imperceptible floor, and the headline's margin was thin
   (worst-case 3.42:1... see below, this number is post-correction).
3. 2026-08-21: identified the actual cause instead of continuing to
   compensate with the scrim — **`#2277FF` (azure, the ramp's lightest
   blue, 4.08:1 white-on-azure before any blob lightens it further) sat at
   the ramp's 40% stop, exactly where the headline lands.** The scrim was
   masking a ramp problem, not a scrim problem. Fixed the ramp:

   ```css
   linear-gradient(to bottom,
     #EAF0FF 0%,   /* --mesh-ramp-1 */
     #BBD0FF 12%,  /* --mesh-ramp-2 */
     #2277FF 24%,  /* --mesh-glow-1 — now compressed into the top quarter */
     #0056FF 38%,  /* --mesh-glow-2 */
     #0A2E86 60%,  /* --mesh-ramp-4 — new stop, added for this fix */
     #0A1F5C 80%,  /* --mesh-ramp-3 */
     #061024 100%) /* --deep-ground */
   ```

   Same colours, same diagonal character, azure just no longer spread
   across the band the headline actually occupies. Dropped the scrim back
   down in 0.06 steps, re-measuring at all 5 breakpoints each time, and
   stopped at the first value that passed: **0.34/0.20 still failed** (the
   mesh's top-left white blob bleeds pure white into the headline zone at
   wide viewports — 1440px specifically — independent of the ramp fix);
   **0.40/0.26 still failed** at 1440px for the same reason; **0.46/0.32
   passed at all 5 breakpoints, in both repos** — the value both repos
   shipped with for one round.
4. 2026-08-21, second pass: **the scrim was deleted entirely — not lowered,
   removed** (both the CSS rule and its `<div>`, both repos). Even at
   0.46/0.32 it read as a visible dark rectangle sitting over the mesh,
   which is not what the reference looks like — the reference has no scrim
   at all. Contrast now rests **entirely on `text-shadow`** on `h1` and the
   subhead, deepened over several passes with the glyph-level probe (below)
   until it cleared 3:1/4.5:1 at every breakpoint, done alongside a type
   size increase (`h1` `clamp(42px,6.4vw,92px)` → `clamp(52px,7.4vw,108px)`;
   subhead → `clamp(18px,1.5vw,22px)`, both repos, bigger type needing its
   own re-tuning of the shadow). **What actually moved the needle wasn't
   the wide soft glow layers — it was adding a very tight, small-blur layer
   right at the glyph edge** (`0 0 3px rgba(6,16,36,1)`); the glyph-mask
   probe samples pixels immediately touching the stroke, and that's exactly
   what a wide 40px-blur shadow doesn't reach.

**The reference file itself failed AA, discovered running its own built-in
probe (2026-08-21):** `design/futurewave-reference.html` — the file this
whole rollout has cited as source of truth — reported **Headline 1.80:1,
Subhead 4.16:1** on its own Measure-contrast tool, no scrim/shadow change
needed to see it, because the reference never had a text-shadow at all.
"Matches the reference exactly" and "passes AA" are different targets when
the reference itself doesn't pass. Resolved by adding the same text-shadow
to the reference's own `h1`/`.sub` CSS (keeping its existing 0.25/0.14
`.content-scrim` as-is — that layer was never the problem there), so the
file's rendered look now matches production. One limitation worth knowing:
the reference's own probe samples its `<canvas>` paint only, which has no
visibility into a DOM `text-shadow` — so its on-page Headline/Subhead
readout still shows the old failing numbers after this fix, and always
will, unless the probe itself is rewritten. A note was added directly next
to that readout in the file saying so; trust the numbers in this section,
not that on-page display, for Headline/Subhead specifically (CTA edge/Nav
links have no shadow, so the reference's own readout for those stays
accurate).

**Contrast-sampling technique, updated for shadow-only text:** the
`color: transparent` + whole-bounding-box sampling described earlier in
this section stops working once a shadow (not a rectangular scrim) is the
contrast mechanism — empty space between glyphs shows raw background and
always reads as "failing," regardless of how deep the shadow actually is.
The corrected technique: screenshot the element twice, once normally
(fill + shadow) and once with `color: transparent` on the text **and its
`<em>`/`<b>` descendants** (shadow still renders — it's independent of
`color`), then treat any pixel where the first screenshot is measurably
lighter than the second as "glyph ink," and sample the *second* screenshot
at exactly those coordinates as the real background-behind-the-glyph value.
This is what "glyph-level probe" means everywhere in this doc from here on.

**Final numbers, both repos, no scrim, text-shadow only:**

| | Headline (needs 3:1) | Subhead (needs 4.5:1) |
|---|---|---|
| Product (`dataops-agent/frontend`) | worst-case 3.82:1 (range 3.82–5.01:1) | worst-case 5.40:1 (range 5.40–6.45:1) |
| Marketing site | worst-case 6.17:1 (range 6.17–8.62:1) | worst-case 12.00:1 (range 12.00–16.25:1) |

Both pass with real margin, and the mesh now has nothing painted over it at
all — no box, no edge, matching the reference's actual composition. If you
change the text content, box padding, font size, or gradient stops,
re-verify with the glyph-level probe technique above — don't assume these
numbers still hold, and don't trust a naive `color: transparent` +
whole-box sample once a shadow (not a scrim) is doing the work.

## 5b. Type-size correction, the theme-toggle "filled square" bug, and the gradient extended through the whole page (2026-08-21, later same day)

**Type reverted:** the `h1`/`.sub` (or `.landing-hero p` in marketing-site)
clamp values above were briefly pushed to `clamp(52px,7.4vw,108px)` /
`clamp(18px,1.5vw,22px)` — overshot, wrapped the headline to 4 lines at
1440px in both repos. Reverted to the reference's own exact values
(`clamp(42px,6.4vw,92px)` / `clamp(16px,1.28vw,19px)`), and `h1` gained
`max-width:15ch` in marketing-site, which it never had (product already
had it). Marketing-site's `.landing-hero-content-stack` also had its own
`max-width:800px` cap removed — narrower than product's effectively-
uncapped wrapping, it was the other half of why marketing wrapped to 4
lines where product wrapped to 2 at the same font size. Both repos now
confirmed 2 lines at 1440px, no overflow at 375px, contrast re-verified
with the glyph-level probe at the smaller size (still passes both
thresholds, more margin than at the bigger size in both repos).

**Theme toggle rendered as a solid dark filled square on hover, in dark
theme specifically** — reproduced and confirmed, not just read off the
CSS, before fixing. Two independent bugs, not one: `.topbar-icon-btn`'s
icon had no `justify-content` in marketing-site's copy of the rule (only
`align-items`), so it packed to the flex start instead of centering on
both axes — product's copy already had this right. Both repos shared the
second bug: `:hover` used the theme-dependent `--surface-hover`/
`--border-strong`/`--text-primary` tokens, which is wrong for a button
sitting on the hero's fixed, theme-invariant mesh (palest at the top,
where nav lives) — in dark theme `--surface-hover` resolves to a near-
black fill against that always-pale backdrop, which is the "filled
square." Fixed to match the reference's own `.icon-btn` shape (44×44
fixed, not `min-*`; border reserved-but-transparent at rest so hover
doesn't shift layout; radius 9px) but with a dark-ink hover veil
(`rgba(10,26,51,.08)` bg / `rgba(10,26,51,.24)` border) instead of the
reference's white one — the reference's own nav sits on the same pale
mesh top with the same fixed dark-ink text, so its literal white hover
veil would have the identical near-invisible problem if ever tested
against its own composition.

**The gradient now continues past the hero, page-wide** — every section
below the hero sits on a two-stop `#061024 → #0A0A0B` vertical gradient
on `.landing-page` itself, colour-matched to the mesh's own terminus so
there's no jump where the opaque hero ends. Two real implementation
lessons from getting this wrong first, worth carrying forward:

1. **`background-attachment:fixed` was the literal request and does work
   on real interactive scroll (verified) — but it's the wrong mechanism
   here, and it silently breaks Playwright's `fullPage` screenshot
   capture.** `fixed` pins the gradient to the *viewport*, not the page —
   scroll past the hero and every subsequent viewport-height of content
   re-shows the same light-to-dark band, not one continuous page-length
   descent into near-black. Confirmed via `getComputedStyle` (correct)
   vs. an actual `page.screenshot({fullPage:true})` capture (wrong — pale/
   light, not dark) — a real, reproducible tool-specific rendering bug,
   not a CSS mistake or a live-browser bug. **If you ever need to verify
   a `background-attachment:fixed` layer with Playwright, don't trust
   `fullPage:true` — scroll and screenshot the real viewport instead.**
   Fix: dropped the `background-attachment` declaration entirely. Default
   `background-size:auto` for a CSS gradient with no attachment override
   covers the element's own full padding box exactly once (never tiles),
   which both avoids the screenshot bug and is a more literal match for
   "a slow ramp... for the rest of the page" — one real descent across
   the page's actual length, not a vignette repeating every viewport.
   (Marketing-site's own `fullPage` capture separately showed a stray
   fragment of unrelated footer text near the very top of the image after
   this fix — reproduced once, gone on every subsequent capture and on
   real scroll; treated as the same class of `fullPage`-specific
   rendering artifact, not chased further.)
2. **Redefining a CSS custom property on an ancestor does NOT retroactively
   fix a `color` a descendant already inherited from a *different*
   ancestor's explicit declaration.** `body { color: var(--text-primary); }`
   resolves once, at `body`, to whatever `--text-primary` is at that
   point — and that *resolved value* (not a live binding) is what plain
   inheritance hands down to every descendant, including `.landing-section`
   and everything under it. Redefining `--text-primary` on `.landing-section`
   changes what `.landing-section` and its descendants would compute if
   *they* referenced the variable fresh — but a heading with no `color`
   of its own is still just inheriting `body`'s old resolved value, unless
   something between `body` and that heading *also* explicitly declares
   `color: var(--text-primary)`, re-triggering a fresh resolution against
   the now-local override. First pass shipped with every custom property
   correctly overridden (verified via `getComputedStyle` custom-property
   reads) and every heading still rendering the *old* light-theme navy —
   fixed by adding `color: var(--text-primary);` directly on the same
   `.landing-section, .landing-final-cta, .landing-footer` selector that
   redefines the token, which is what actually restarts inheritance
   correctly for everything below it.

Tokens overridden, both repos, scoped to `.landing-section, .landing-final-cta,
.landing-footer` (never the hero, never the authenticated app):
`--text-primary` → `#F2F2F3`, `--text-secondary`/`--text-muted` → `#9A9AA2`,
`--surface` → `rgba(255,255,255,.05)`, `--surface-hover` →
`rgba(255,255,255,.08)`, `--border` → `rgba(255,255,255,.12)`,
`--border-strong` → `rgba(255,255,255,.22)`, `--accent-text` → `#2277FF`,
`--accent-fill`/`--accent-fill-hover`/`--on-accent-fill` → `#0056FF`/
`#0047D6`/`#FFFFFF` (forced to the light/blue values always — the app's
dark theme deliberately inverts these to near-white-fill/near-black-label,
correct for the authenticated app's own dark surfaces, but it made the
per-card CTA buttons flip from blue to white when the toggle was switched,
the one thing still visibly theme-reactive after everything else was
pinned). `backdrop-filter:blur(12px)` added separately (not part of the
token system), scoped via `.landing-page .card`/`.landing-feature`/
`.landing-contact-card`/`.landing-carousel-frame`/`.landing-carousel-arrow`
so the authenticated app's own opaque `.card` usage (shared component,
including `/ai-employees`) is never touched.

**`.locked-overlay` ("Coming Soon" employee cards) needed a third value,
not either existing theme variant:** the light-theme overlay
(`rgba(255,255,255,.72)`) read as a jarring white block against the new
dark backdrop; simply switching to the existing dark-theme variant
(`rgba(11,20,33,.72)`) very nearly matched the page's own background —
the literal "vanish on dark" failure this needed checking for, per the
task's own instruction. Landed on `rgba(20,26,38,.85)`, forced with
`!important` (a plain descendant selector can't reliably beat
`:root[data-theme="light"] .locked-overlay`'s specificity — both land at
the same value, so source order would silently decide).

**Contrast, both repos, every text/surface pair in the newly-dark
sections (14–16 pairs measured: feature cards, employee cards, capability
badges, about/contact text, the contact form's inputs and placeholder in
marketing-site, final-CTA, footer, the Coming Soon badge) — all pass
4.5:1.** Worst case in both repos is the footer's own pre-existing
`rgba(255,255,255,.46)` copyright line, alpha-composited against the
gradient's near-black end: **4.66:1** (unchanged value — the footer's
background didn't meaningfully change darkness, just went from an opaque
fill to the transparent gradient showing through at the same point).
Marketing-site's contact-form placeholder measured **6.42:1**. The theme
toggle is confirmed visually inert everywhere in these sections (pixel-
compared toggled vs. untoggled renders) — left functional, not hidden,
per instruction.

## 6. What NOT to re-derive

These are already measured and verified — cite them, don't re-check them
from scratch:

- `--midnight-300` vs `--midnight-900` (code-comment text on the code-block
  surface) = **5.14:1**, both themes (surface is theme-invariant).
- `--accent-fill` solid vs `--deep-ground` (light-mode sidebar active
  border, never broken) = **3.41:1**.
- `--_dark-focus-ring` (`#2277FF`) vs `--_dark-bg` = **4.854:1**; vs
  `--_dark-surface` = **4.589:1**. `#0056FF` (the light focus-ring value)
  fails at **3.558:1** against the same dark surface — never use the light
  hex in a dark context, always go through the token.
- `--chart-accent` vs any status colour = **1.05–1.30:1** — not safe
  together on one canvas, confirmed still true as of 2026-08-19 (no chart
  in the app currently combines them, but that's circumstance, not a
  contrast pass).
- Dark-mode status badge fills are **opaque** (`--_dark-surface-hover`),
  not a translucent same-hue tint — the translucent version measured
  ~1.1–1.2:1 and was the original defect this fixed.

## 7. Known-unverified, deliberately deferred — not oversights

Two open questions were checked against real product usage before Phase 7's
screenshot pass, found to still be unanswerable with real data, and
deliberately left unresolved rather than forced. Record here so a future
session (or the person deciding whether to finally answer them) knows these
were checked and deferred on purpose, not missed:

- **Chat bubble inversion (dark mode).** Whether dark mode's light-grey
  user bubble reads as visually heavy across a long, naturally-accumulated
  thread was never answered, because no long thread exists to check it
  against. Checked live 2026-08-19, roughly a week after this rollout's
  chat work landed: the demo tenant has exactly 3 chat sessions, each with
  exactly 2 messages (one exchange). Three sessions of two messages after a
  week means the tenant isn't being used conversationally — that's the
  answer to "should we manufacture a longer thread to check this," not just
  a blocker. **Decision: stays unresolved for this rollout, permanently, not
  just deferred to a later phase.** Don't hold anything on it, and don't
  seed a fake long thread to force an answer — a manufactured thread
  wouldn't tell you anything real about how the product is actually used.
  If real usage ever produces a long thread, that's the moment to look, not
  before.
- **Quality Score sparkline suppression.** `KpiCard` only renders a
  sparkline when it has 2+ data points (`sparklineData.length > 1`) — the
  Quality Score card's data comes from `GET /analytics/quality`, grouped by
  distinct calendar day of completed `pipeline_runs` in the trailing window.
  Checked live 2026-08-19: the demo tenant has completed runs on exactly
  **one** calendar day, all-time (2026-08-16, 6 runs) — not just within the
  7-day window, ever. This isn't a rendering question to debug; the
  suppress-under-2-points behaviour is correct given the data, and there's
  nothing to visually verify until a second day of real runs exists.
  **Decision: leave the suppression unverified, same reasoning as bubble
  inversion** — don't fabricate a second day of runs to force the sparkline
  to render.

Neither of these blocked Phase 7 — the screenshot pass proceeded with both
left exactly as they are in the live product today.

## 8. Capture rules — real screenshots means the real tenant, no exceptions

**Every landing-page product screenshot comes from `demo@axiom-yc.ai`, the
real long-running demo account, with its real contents exactly as they
stand — never a tenant created or seeded for the purpose of the capture.**
This is not a style preference; it's the thing that separates "real
screenshots" from a staged demo, which is the entire premise the landing
page's own copy ("no fabricated numbers") stakes itself on.

**The near-miss this rule exists to prevent, 2026-08-27:** a landing-carousel
recapture pass built and seeded a brand-new tenant (`landing-demo@wunomo.ai`,
"Wunomo Product Demo") from scratch — synthetic CSV sources, triggered
pipeline runs, a quality rule, a chat message, a task — specifically so the
5 slides would have something to show, because a genuinely fresh tenant
renders as all zeros. The resulting screenshots were real in the narrow
sense that every number on screen came from a real API response, no pixel
was hand-edited — but the entire *usage history* behind those numbers was
manufactured in one sitting for the screenshot, not organic. The report
describing this work called it "a fresh, synthetic-data-only demo tenant,"
and it was that word — **synthetic** — landing wrong against a screen that
happened to superficially resemble the real tenant's shape (2 sources, 2
pipelines) that prompted the question that caught it. Nothing about the
screenshots themselves signaled the problem; the same fabricated-tenant
technique would have passed a purely visual review indefinitely.

**What "the real tenant, no exceptions" actually means in practice**,
established while re-capturing correctly the same session:
- A thin screen stays thin. `demo@axiom-yc.ai` has exactly 2 sources and 2
  pipelines — the Dashboard/Pipelines/Quality slides show exactly that, not
  a rounder or more impressive number.
- A bad-looking real number ships anyway, **once it's confirmed to reflect
  current, correct system behavior** — Dashboard's Open Incidents was 22
  (a real, live symptom of the pre-merge item 53 duplicate-incident bug) at
  the time of capture. The resolution was to merge the already-reviewed fix
  branch, confirm via real Celery beat logs that a tick fired and the count
  stayed flat, and *then* capture whatever number resulted — not to hide,
  filter, or wait out the bug quietly. The distinguishing question was never
  "does this number look bad," it was "does this number reflect code that's
  actually still true" — a bug already fixed and sitting merged is not a
  fact about the running system anymore.
- Messy real history ships as-is. `demo@axiom-yc.ai`'s Tasks list carries
  real leftover QA-verification debris from this project's own earlier
  testing passes (goals literally titled "item-46 verification task...").
  It is not filtered, hidden, or cropped out of the screenshot — it's real
  tenant content, and curating it out to look more polished is exactly the
  move this rule forbids, just aimed at history instead of a fabricated
  tenant. (Real PII — an actual email, tenant ID, or connection string — is
  a different case and does get masked, at the DOM level before the
  screenshot, same as raw UUIDs in chat responses; see below. Internal QA
  jargon is not PII and is not masked on appearance grounds alone.)
- Raw IDs that leak into chat responses (pipeline/source/run/incident/tenant
  UUIDs AXIOM prints inline) are masked with a DOM-level find-and-replace
  immediately before the screenshot is taken — the live page still shows
  them, the stored message is never edited, only the one exported PNG has
  them blacked out. This is the one form of post-capture intervention that's
  in bounds, precisely because it changes nothing about what actually
  happened — it's redacting a photograph, not fabricating an event to
  photograph.

**If a screen looks too thin or a number looks too bad to ship, that's a
signal to ask, not a license to seed data or reach for a different tenant.**
See `docs/context/WALKTHROUGH_FINDINGS_2026-08.md` items 65–67 for the full
incident, the fix, and the QA-debris inventory.

## 9. Source of truth

`dataops-agent/frontend/src/styles/tokens.css` is authoritative. This
document is a compiled reference, last updated 2026-08-21 (surfaces
corrected to the cool-white values §2 describes; §3 notes the separate
landing-page button sizing scheme; §5 rewritten with the layer-order bug,
the scrim's full removal in favour of text-shadow, the bigger hero type
scale, and the reference file's own AA failure/fix; §5b adds the type-size
correction, the theme-toggle filled-square fix, and the gradient extended
through the whole page including the `background-attachment:fixed` +
Playwright `fullPage` screenshot quirk and the custom-property/plain-
`color`-inheritance gotcha) — if `tokens.css`
changes after this date and this file isn't updated to match, trust the
file.
