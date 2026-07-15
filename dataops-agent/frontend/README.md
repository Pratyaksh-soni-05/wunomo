# Wunomo AI — Frontend

Next.js 15 (App Router) frontend for AXIOM. See `../../FRONTEND_BUILD_PLAN.md` (repo root)
for the full phase plan and `../DESIGN_TOKENS.md` for locked palette/typography values —
read both before making changes here.

## Development

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The root page (`src/app/page.tsx`) is
currently a component-library showcase (Phase 2 verification tool), not the real app shell —
that lands in Phase 7.

## Structure

- `src/styles/tokens.css` — CSS custom properties for the locked Midnight/Pearl Perfect/Noir/Ocean
  palette, light + dark mode. Source of truth values are in `../DESIGN_TOKENS.md`.
- `src/styles/fonts.css` — `@font-face` declarations for the self-hosted font files in
  `public/fonts/` (General Sans, Fraunces, JetBrains Mono — latin subset only). No runtime
  Google Fonts/Fontshare CDN calls.
- `src/styles/components.css` — core component styles (buttons, cards, badges, inputs, tabs,
  tables, toasts, modals, progress, skeletons), ported from the master design prototype's CSS
  and remapped onto the locked tokens above.
- `src/components/ui/` — the React component library wrapping the CSS above (`Button`, `Card`,
  `Badge`, `Input`/`Select`, `Table`, `Modal`, `Toast`/`useToast`, `Tabs`, `Progress`, `Skeleton`).

## Known gaps (tracked in the repo-root `CLAUDE.md`, not duplicated here)

No Zustand store, API client, auth, or app shell yet — those are later phases. This directory
is scaffold + design system + component library only (`FRONTEND_BUILD_PLAN.md` Phase 2).
