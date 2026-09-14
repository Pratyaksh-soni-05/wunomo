// Wunomo UI-rebuild slice 6b (2026-09-14) -- /pipelines, /incidents,
// /transforms keep their old URLs but changed meaning (full tenant list ->
// unscoped-only list). Same problem /governance's Lineage tab had losing
// its content at a stable URL; same fix, adapted -- these three routes
// don't have Governance's internal tab bar to carry an inert notice, so
// the banner has to sit at the top of the page itself, visible on load.
export function ScopeBanner({ label }: { label: string }) {
  return (
    <div className="scope-banner">
      Showing {label} not tied to any project — project-scoped {label} now live in each project&apos;s
      Workbench.
    </div>
  );
}
