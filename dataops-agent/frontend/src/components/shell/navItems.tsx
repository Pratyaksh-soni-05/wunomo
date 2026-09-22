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
 * docs/design/UI_REBUILD_INVENTORY.md, slice 3). Needs you is /approvals,
 * rebuilt in slice 9 into the real combined screen this label always
 * implied — same route, real content now. Scheduled had no existing
 * equivalent at all, so it was the one genuinely new route — real as of
 * slice 10 (2026-09-15): the tenant-wide ScheduledAgentTask list, agent
 * schedules only (pipeline schedule_cron stays in Workbench, its own
 * unrelated mechanism with no deactivation-reason concept).
 * Settings and Team both already exist. Team's "& billing" half was a
 * rail-copy decision made ahead of the real merge in slice 3 — the merge
 * itself shipped in slice 12 (2026-09-15): /billing retired, its content
 * moved into /team as a real second tab, deep-linked via ?tab=billing
 * (the quota-exceeded toast's "Go to Billing" now lands there directly,
 * not through the retirement redirect).
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
 * when a route's real content hasn't caught up to its rail rebrand yet.
 * /approvals no longer needs that exception (slice 9, 2026-09-15) — the
 * page itself is the real Needs You screen now, so its breadcrumb/palette
 * label matches the rail's.
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
 * Slice 12 (2026-09-15) — six placement decisions, each a real
 * destination or a real "not available," never a silent gap:
 *   - AI Employees retired: the hire-agent flow already shows the same
 *     roster, this was a redundant second copy of it. -> /agents.
 *   - Global Agents list kept as-is (an explicit decision, not a gap —
 *     agents are tenant-owned and can span projects, so "every agent
 *     I've hired" genuinely has no other home).
 *   - Governance retired outright, split two ways: Contracts moved into
 *     each project's Workbench (source-scoped, same as Sources —
 *     confirmed producer_source_id is required at creation despite being
 *     schema-nullable, so no unscoped case exists, unlike Pipelines/
 *     Incidents). Audit Log moved into Settings as a real tab
 *     (tenant-wide by nature, same as every other Settings tab) —
 *     which also superseded the separate /audit stub that predated this
 *     slice and never had real content of its own.
 *   - Data Catalog retired the same way as Sources/Quality/CI-CD: real,
 *     source-scoped content, moved into Workbench.
 *   - Billing retired, merged into /team as a real second tab
 *     (?tab=billing) — not just relabeled, the three live call sites
 *     that deep-link here (both chat pages' quota-exceeded toast,
 *     TaskCreateModal) were repointed to land on the tab directly.
 *   - Automations retired with no migration destination — no backend
 *     ever existed for it, confirmed by grep, nothing to point at.
 *   - Analytics retired the same way, but NOT for the same reason —
 *     a full backend already exists unused behind it (overview,
 *     recent-runs, pipelines, quality, KPI GET+POST, usage, a typed
 *     client already in lib/api.ts). Logged as findings item 101 so
 *     that surface isn't silently forgotten just because its stub is
 *     gone; building the real screen is its own future slice.
 */
export const ALL_NAV_ITEMS: NavItem[] = [
  { slug: "home", label: "Home" },
  { slug: "dashboard", label: "Dashboard" },
  { slug: "scheduled", label: "Scheduled" },
  { slug: "approvals", label: "Needs You" },
  { slug: "settings", label: "Settings" },
  { slug: "team", label: "Team & Billing" },
  { slug: "billing", label: "Billing (now part of Team & billing)" },
  { slug: "projects", label: "Projects" },
  { slug: "agents", label: "Agents" },
  { slug: "ai-employees", label: "AI Employees (moved into the hire-agent flow)" },
  { slug: "chat", label: "AXIOM" },
  { slug: "tasks", label: "Tasks" },
  { slug: "sources", label: "Data Sources (moved into each project's Workbench)" },
  { slug: "catalog", label: "Data Catalog (moved into each project's Workbench)" },
  { slug: "pipelines", label: "Pipelines (unscoped only — the rest moved into each project's Workbench)" },
  { slug: "transforms", label: "Transforms (moved into each project's Workbench)" },
  { slug: "quality", label: "Quality (moved into each project's Workbench)" },
  { slug: "incidents", label: "Incidents (unscoped only — the rest moved into each project's Workbench)" },
  { slug: "governance", label: "Governance (Contracts moved to Workbench, Audit Log moved to Settings)" },
  { slug: "governance", label: "Contracts (moved into each project's Workbench)" },
  { slug: "governance", label: "Lineage (moved into each project's Workbench)" },
  { slug: "automations", label: "Automations (not available in this workspace)" },
  { slug: "cicd", label: "CI / CD (moved into each project's Workbench)" },
  { slug: "analytics", label: "Analytics (not available yet)" },
  { slug: "audit", label: "Audit Logs (now a tab in Settings)" },
];
