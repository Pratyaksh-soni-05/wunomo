import { ReactNode } from "react";

export interface NavItem {
  slug: string;
  label: string;
  /** Rendered only by the sidebar's own rail items — CommandPalette renders
   * its own generic marker per result, Topbar's breadcrumb renders label
   * text only, so an off-rail item genuinely never needs one. */
  icon?: ReactNode;
}

/**
 * Icons redrawn to match docs/design/wunomo-all-screens.html exactly
 * (2026-09-14, slice 3) — viewBox 0 0 16 16, stroke-width 1.3, not the
 * previous 0 0 24 24 / stroke-width 2 set. Different coordinate system per
 * glyph, not a parameter tweak, so these are new paths, not the old ones
 * restyled.
 */
const railIcon = (path: ReactNode, extra?: Record<string, string>) => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" {...extra}>
    {path}
  </svg>
);

export const ICON_HOME = railIcon(<path d="M2.5 6.8 8 2.5l5.5 4.3V13a.7.7 0 0 1-.7.7H3.2a.7.7 0 0 1-.7-.7z" />);
export const ICON_SCHEDULED = railIcon(
  <>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M8 5v3.2l2 1.2" strokeLinecap="round" />
  </>
);
export const ICON_NEEDS_YOU = railIcon(
  <path d="M4 2.8v10.4M4 3.2h7.2l-1.4 2.3 1.4 2.3H4" />,
  { strokeLinecap: "round" }
);
export const ICON_PROJECT = railIcon(
  <>
    <rect x="2.5" y="4" width="11" height="8.5" rx="1.2" />
    <path d="M2.5 6.2h11M6 2.5v2" />
  </>
);
export const ICON_SETTINGS = railIcon(
  <>
    <circle cx="8" cy="8" r="2.1" />
    <path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1" />
  </>
);
export const ICON_TEAM = railIcon(
  <>
    <circle cx="6" cy="6" r="2.3" />
    <path d="M2 13.2c0-2.2 1.8-3.6 4-3.6s4 1.4 4 3.6M10.6 4.2a2.2 2.2 0 0 1 0 4M11.5 9.9c1.6.4 2.5 1.6 2.5 3.3" />
  </>
);
export const ICON_NEW_PROJECT = (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
    <path d="M8 3.5v9M3.5 8h9" />
  </svg>
);

/**
 * The persistent rail (2026-09-14, slice 3 — matches
 * wunomo-all-screens.html's RAIL template exactly). Five static
 * destinations; the "Projects" section beneath them is rendered separately
 * in Sidebar.tsx from live project data, not part of this static list.
 *
 * Slugs point at whatever real page already exists for each concept today,
 * not at new routes invented for this slice — "point at what's real" (see
 * docs/design/UI_REBUILD_INVENTORY.md, slice 3). Needs you is /approvals
 * (reworked in slice 9). Scheduled has no existing equivalent at all, so
 * it's the one genuinely new route, landing on a StubPage until slice 10.
 * Settings and Team both already exist unchanged; the "& billing" half of
 * Team's label is a rail-copy decision only in this slice — the actual
 * Billing page content hasn't merged into /team yet (see the
 * ALL_NAV_ITEMS note below).
 *
 * Home pointed at /dashboard through slice 3, as an interim "point at
 * what's real" measure — slice 4 is the real rework: Home now has its own
 * route (/home, built fresh) and /dashboard keeps its original KPI/
 * analytics content unchanged, no longer the landing page. See
 * docs/design/UI_REBUILD_INVENTORY.md, slice 4.
 */
export const RAIL_NAV_ITEMS: NavItem[] = [
  { slug: "home", label: "Home", icon: ICON_HOME },
  { slug: "scheduled", label: "Scheduled", icon: ICON_SCHEDULED },
  { slug: "approvals", label: "Needs you", icon: ICON_NEEDS_YOU },
];

export const RAIL_FOOTER_ITEMS: NavItem[] = [
  { slug: "settings", label: "Settings", icon: ICON_SETTINGS },
  { slug: "team", label: "Team & billing", icon: ICON_TEAM },
];

/**
 * Every route in the app, for the command palette (Ctrl+K) and Topbar's
 * breadcrumb lookup — NOT for the sidebar, which renders only
 * RAIL_NAV_ITEMS/RAIL_FOOTER_ITEMS/live project data above. This list is
 * deliberately larger than what's visible in the rail: every route the old
 * sidebar carried is still real, still works, and stays reachable here
 * even though slice 3 removes its dedicated nav button — see
 * docs/design/UI_REBUILD_INVENTORY.md, slice 3, "the interim-navigation
 * question." Labels here are each route's own honest current name, which
 * can genuinely differ from the rail's rebranded label for the same slug
 * (e.g. /approvals shows "Needs you" in the rail but still says
 * "Approvals" here and in the breadcrumb, because the page itself hasn't
 * been rebuilt into Needs You yet — slice 9's job, not this one's).
 *
 * Slice 6a (2026-09-14): Sources/Quality/CI-CD's old top-level routes
 * retired — each resolves cleanly per project with no unscoped population
 * (UI_REBUILD_INVENTORY.md §2), so unlike Pipelines/Incidents/Transforms
 * they don't get repurposed into a tenant-wide view in 6b, they just move
 * into each project's Workbench. Labels updated here to say so rather
 * than removed outright — the routes still exist (RetiredRouteRedirect,
 * a real redirect + explanation, not a 404), so a command-palette search
 * finding them and landing on that explanation is the intended path, not
 * a dead end.
 *
 * Slice 6b (2026-09-14): Pipelines/Incidents repurposed instead of
 * retired — each has a real unscoped population (a pipeline with no
 * source, an incident with no pipeline), so their old top-level routes
 * stay live and useful, just narrowed to unscoped-only, with a
 * ScopeBanner explaining the change on the page itself (same URL, real
 * content, not a redirect). Transforms was repurposed the same way
 * initially, then retired outright (2026-09-15, findings item 97) once
 * it turned out no code path can ever produce a sourceless TransformRun
 * — the repurposed view could only ever show empty, so it joined
 * Sources/Quality/CI-CD's plain retirement instead.
 *

 * Governance/Lineage correction (explicit instruction, 2026-09-14):
 * losing the Lineage tab can't leave a silent gap. /governance itself now
 * says so on its own now-inert Lineage tab (governance/page.tsx); this
 * list adds a second, separate "Lineage" entry pointing at the same
 * /governance slug purely so searching "lineage" in the command palette
 * surfaces that explanation, rather than finding nothing at all.
 */
export const ALL_NAV_ITEMS: NavItem[] = [
  { slug: "home", label: "Home" },
  { slug: "dashboard", label: "Dashboard" },
  { slug: "scheduled", label: "Scheduled" },
  { slug: "approvals", label: "Approvals" },
  { slug: "settings", label: "Settings" },
  { slug: "team", label: "Team" },
  { slug: "billing", label: "Billing" },
  { slug: "projects", label: "Projects" },
  { slug: "agents", label: "Agents" },
  { slug: "ai-employees", label: "AI Employees" },
  { slug: "chat", label: "AXIOM" },
  { slug: "tasks", label: "Tasks" },
  { slug: "sources", label: "Data Sources (moved into each project's Workbench)" },
  { slug: "catalog", label: "Data Catalog" },
  { slug: "pipelines", label: "Pipelines (unscoped only — the rest moved into each project's Workbench)" },
  { slug: "transforms", label: "Transforms (moved into each project's Workbench)" },
  { slug: "quality", label: "Quality (moved into each project's Workbench)" },
  { slug: "incidents", label: "Incidents (unscoped only — the rest moved into each project's Workbench)" },
  { slug: "governance", label: "Governance (Contracts, Audit Log)" },
  { slug: "governance", label: "Lineage (moved into each project's Workbench)" },
  { slug: "automations", label: "Automations" },
  { slug: "cicd", label: "CI / CD (moved into each project's Workbench)" },
  { slug: "analytics", label: "Analytics" },
  { slug: "audit", label: "Audit Logs" },
];
