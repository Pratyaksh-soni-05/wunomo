# Wunomo AI — Design Tokens (locked, Phase 0)

Derived token values for the frontend build. This is the source of truth for
`frontend/styles/tokens.css` once the scaffold lands (Phase 2) — written here so a
fresh session doesn't depend on this conversation's artifact, which isn't visible
outside the chat that published it.

Full interactive version (swatches, hover tooltips, type samples) was published as a
Claude artifact during Phase 0; this file has the same values in plain reference form.

## Core colors (given, not derived)

| Name | Hex | Role |
|---|---|---|
| Midnight | `#122C4F` | Sidebar, primary text, primary buttons |
| Pearl Perfect | `#FBF9E4` | Page background, cards (light mode) |
| Noir | `#000000` | Page background (dark mode), code blocks |
| Ocean | `#5B88B2` | Links, active states, focus rings, secondary accent |

## Derived scales — light mode

**Midnight scale** (sidebar, primary actions, headings — cool, from Midnight's hue)
```
midnight-900  #0A1B30
midnight-800  #0F2440
midnight-700  #122C4F   ← base (Midnight itself)
midnight-600  #1B3A63
midnight-500  #26507F
midnight-400  #3D6B9E
midnight-300  #6A8FB8
midnight-200  #A3BFDA
midnight-100  #D6E3EF
midnight-50   #EFF4F9
```

**Ocean scale** (links, active states, focus rings)
```
ocean-700  #35526E
ocean-650  #416487
ocean-600  #4C76A0
ocean-500  #5B88B2   ← base (Ocean itself)
ocean-400  #7EA0C2
ocean-300  #9FB9D3
ocean-200  #C3D6E5
ocean-100  #E1EBF3
ocean-50   #F1F6FA
```

**Surfaces & borders** (warm, from Pearl Perfect's cream undertone)
```
surface        #FFFEF5   (card background — slightly lighter/whiter than page bg)
bg             #FBF9E4   (page background — Pearl Perfect itself)
surface-hover  #F3F0DC
border         #E6E1C8
border-strong  #D3CBA8
```

**Text / ink** (cool, from Midnight's hue — deliberate warm-canvas/cool-ink pairing)
```
text-primary    #16233A
text-secondary  #3A4A63
text-muted      #6B7C94
text-disabled   #A7B4C4
```

## Derived scales — dark mode (`:root[data-theme="dark"]`)

**Surfaces** (Noir page, Midnight-derived elevated panels — sidebar stays Midnight in *both* themes, a constant "spine")
```
bg             #000000   (Noir — page background)
surface        #0F2440   (card background — midnight-800)
sidebar-bg     #122C4F   (same as light mode — Midnight)
surface-hover  #1B3A63   (midnight-600)
border-strong  #26507F   (midnight-500)
```

**Ocean scale (dark)** — lighter tints for contrast against Noir
```
ocean-400  #7EA0C2
ocean-300  #9FB9D3   ← primary link/active color in dark mode
ocean-200  #C3D6E5
ocean-500  #5B88B2   (base, used sparingly at full saturation)
```

**Text / ink (dark)** — softened Pearl Perfect, not pure white (keeps the warm brand character)
```
text-primary    #F5F3E6
text-secondary  #B8C2D1
text-muted      #7A8CA3
text-disabled   #4A5568
```

## Semantic colors (unchanged hues in both themes — conventional status colors)

| | Hue | Light bg / border | Dark bg / border |
|---|---|---|---|
| Success | `#16a34a` | `#EAF7EE` / `#BFE5C9` | `rgba(22,163,74,.15)` / `rgba(22,163,74,.4)` |
| Warning | `#d97706` | `#FBF1E1` / `#F0D9AE` | `rgba(217,119,6,.15)` / `rgba(217,119,6,.4)` |
| Danger  | `#dc2626` | `#FBEAEA` / `#F3C6C6` | `rgba(220,38,38,.15)` / `rgba(220,38,38,.4)` |
| Info    | `#0891b2` (from original prototype, unchanged) | `#ecfeff` / `#a5f3fc` | `rgba(8,145,178,.15)` / `rgba(8,145,178,.4)` |

## Typography — locked

| Role | Typeface | Source | Notes |
|---|---|---|---|
| Display / headings | **Fraunces** | Google Fonts | Page titles, section headers, landing hero, metric values where editorial feel fits. Weights: 500, 600 (matches artifact sample) |
| UI / body | **General Sans** | Fontshare | Navigation, buttons, tables, forms, chat, all functional text. Weights: 400, 500, 600, 700 |
| Code / mono | **JetBrains Mono** | Google Fonts | Code blocks, SQL editor, commit hashes, timestamps, API keys — unchanged from the original prototype |

**Self-hosting requirement (Phase 2):** download both font families and serve from
`frontend/public/fonts/` with local `@font-face` declarations — no runtime Google
Fonts/Fontshare CDN calls. Use `font-display: swap` and `<link rel="preload">` for
the critical weights (General Sans 400/600, Fraunces 600) to avoid layout shift on
first paint. (This session's sandbox couldn't reach either font CDN to fetch the real
files for the Phase 0 sample — the artifact used system-font approximations,
clearly disclosed there. Fetching the real font files is a Phase 2 task.)

## Layout tokens (carried over unchanged from the prototype)

```
sidebar-w            220px
sidebar-w-collapsed  60px
topbar-h             52px
radius-xs/sm/md/lg/xl/full   4px / 6px / 10px / 12px / 16px / 9999px
t-fast/normal/slow   100ms / 180ms / 280ms ease
```
