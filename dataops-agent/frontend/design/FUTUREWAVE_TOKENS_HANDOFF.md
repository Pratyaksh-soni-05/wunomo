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

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#FBF9E4` (Pearl Perfect) | `#0A0A0B` |
| `--surface` | `#FFFEF5` | `#121214` |
| `--surface-hover` | `#F3F0DC` | `#1A1A1D` |
| `--border` | `#E6E1C8` | `#26262A` |
| `--border-strong` | `#D3CBA8` | `#3A3A40` |

### Text

| Token | Light | Dark | Contrast (dark, vs `--_dark-bg`) |
|---|---|---|---|
| `--text-primary` | `#16233A` | `#F2F2F3` | 17.689:1 |
| `--text-secondary` | `#3A4A63` | `#9A9AA2` | 7.085:1 |
| `--text-muted` | `#6B7C94` | `#6E6E76` | 3.916:1 — **large text / non-essential UI only, never body copy.** Deliberately fails the 4.5:1 body floor; only clears the 3:1 large-text/UI-chrome bar. |
| `--text-disabled` | `#A7B4C4` | `#5A5A66` | — |
| `--on-dark` | `#FFFEF5` (both themes, constant) | same | Text painted on a permanently-dark surface (primary buttons, toasts, tooltips) — deliberately **not** the same token as `--surface`, which flips per theme. Conflating the two caused dark-text-on-dark primary buttons in an earlier phase; keep them separate. |

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

## 5. What NOT to re-derive

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

## 6. Source of truth

`dataops-agent/frontend/src/styles/tokens.css` is authoritative. This
document is a compiled reference as of 2026-08-19 (Phase 6's close) — if
`tokens.css` changes after this date and this file isn't updated to match,
trust the file.
