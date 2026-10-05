import { ReactNode } from "react";

export interface NavItem {
  slug: string;
  label: string;
  /** Rendered only by the sidebar's own rail items — CommandPalette renders
   * its own generic marker per result, Topbar's breadcrumb renders label
   * text only, so an off-rail item genuinely never needs one. */
  icon?: ReactNode;
  /** IA-rail pass (blueprint §03): renders as an inert row with a tooltip
   * instead of a <Link> — the same "real, honest disabled state" Tabs.tsx
   * already established for LiveWorkPanel's Files tab, not a dimmed link
   * pointing at nothing. Never paired with a slug that resolves to a real
   * page — Outputs and Connections both have no tenant-wide page to point
   * at (see this pass's own report), so this is the option, not a stopgap
   * for something that'll get a route later this same pass. */
  disabled?: boolean;
  disabledReason?: string;
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
// IA-rail pass (blueprint §03) — Outputs (a document glyph) and
// Connections (two linked nodes) are the two destinations §03 names that
// this pass doesn't build; both rendered disabled (see NavItem.disabled)
// needing a real icon so the disabled row isn't blank where every
// sibling has one. Outputs is real as of blueprint §11 (2026-10-05, once
// the Output model existed) -- its icon stays, only RAIL_NAV_ITEMS'
// `disabled`/`disabledReason` were removed. Connections remains disabled;
// this comment's "both" is now stale for Outputs specifically.
export const ICON_OUTPUTS = railIcon(
  <>
    <path d="M4.8 2.5h4.4l2 2v8.3a.7.7 0 0 1-.7.7H4.8a.7.7 0 0 1-.7-.7V3.2a.7.7 0 0 1 .7-.7z" />
    <path d="M9.2 2.5v2h2" />
  </>
);
export const ICON_CONNECTIONS = railIcon(
  <>
    <circle cx="5" cy="5.2" r="1.7" />
    <circle cx="11" cy="10.8" r="1.7" />
    <path d="M6.2 6.4l3.6 3.2" strokeLinecap="round" />
  </>
);

/**
 * The persistent rail. IA-rail pass (blueprint §03, 2026-09-29) —
 * restructured to match §03's seven named destinations (Command Center,
 * Projects, Team, Approvals, Outputs, Connections, Settings), plus
 * Scheduled kept even though §03 doesn't name it: the feature is real and
 * useful, the blueprint's omission reads as a miss, not a decision (see
 * this pass's own report). Rail structure only — no destination page was
 * rebuilt; every slug here already pointed at a real page before this
 * pass and still does.
 *
 * One uninterrupted array, all eight as siblings — a follow-up fix within
 * the same pass. The first cut split this into RAIL_NAV_ITEMS_TOP (just
 * Command Center) + RAIL_NAV_ITEMS (the rest) with the live Projects list
 * rendered in between and Settings pinned in a separate footer block —
 * which left "PROJECTS" as a plain section-label link with no real nav
 * item of its own, and made Team/Approvals/Outputs/Connections/Scheduled
 * render BELOW the project list, reading as that project's children
 * rather than workspace-level siblings. §03 has no such hierarchy — all
 * seven (plus Scheduled) are peers. Sidebar.tsx now renders this whole
 * array as one block, with "projects" a real item in it (icon, href,
 * active state, all identical to every other item here), and the live
 * recent-projects list rendered as its own visually subordinate section
 * strictly after this entire block.
 *
 * Real re-mappings this pass made, not just relabels:
 * - Command Center -> /home. The page itself is unchanged this pass
 *   (§03's "live x-ray" content is a separate, later pass) — only the
 *   label and rail position change, matching what the destination is
 *   named, not what it currently shows.
 * - Projects -> /projects (the list page — unchanged; §03 itself
 *   describes this destination as "the list, then the workspace").
 * - Team -> /agents (the cross-project employee roster, real since slice
 *   12 but never railed) — NOT the old "Team & billing" slug. §03's Team
 *   is about employees (AI agents); the old rail's "Team & billing" was
 *   about human members/invites/billing, which maps to §03's Settings
 *   instead ("people & roles, billing") — two different concepts that
 *   happened to share a label before this pass.
 * - Approvals -> /approvals, same route, renamed from "Needs you" (the
 *   page's own <h1> renamed to match — a rail label pointing at a page
 *   titled something else would read as a bug, not a rename).
 * - Outputs, Connections: real §03 destinations that had nothing to route
 *   to at the time of this pass (no Output model; Connections only
 *   exists project-scoped under each project's Workbench). Rendered
 *   disabled with a tooltip then — see ICON_OUTPUTS/ICON_CONNECTIONS
 *   above and Sidebar.tsx's disabled-item branch for that mechanism.
 *   Outputs is enabled as of blueprint §11 (2026-10-05, once the Output
 *   model existed); Connections remains disabled. Do not point a still-
 *   disabled item at a page that doesn't exist.
 *
 * Settings keeps its own slug/label unchanged; what changed is what's
 * folded into it (Team & billing's tabs, see settings/page.tsx) and its
 * position — no longer a separate footer block, now the last of this one
 * uninterrupted group, matching where §03 places it among its siblings.
 */
export const RAIL_NAV_ITEMS: NavItem[] = [
  { slug: "home", label: "Command Center", icon: ICON_HOME },
  { slug: "projects", label: "Projects", icon: ICON_PROJECT },
  { slug: "agents", label: "Team", icon: ICON_TEAM },
  { slug: "approvals", label: "Approvals", icon: ICON_NEEDS_YOU },
  { slug: "outputs", label: "Outputs", icon: ICON_OUTPUTS },
  {
    slug: "connections", label: "Connections", icon: ICON_CONNECTIONS, disabled: true,
    disabledReason: "Not tenant-wide yet — manage sources inside each project's Workbench.",
  },
  { slug: "scheduled", label: "Scheduled", icon: ICON_SCHEDULED },
  { slug: "settings", label: "Settings", icon: ICON_SETTINGS },
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
  { slug: "home", label: "Command Center" },
  { slug: "dashboard", label: "Dashboard" },
  { slug: "scheduled", label: "Scheduled" },
  { slug: "approvals", label: "Approvals" },
  // Added 2026-10-05 (blueprint §11 UI): outputs had no ALL_NAV_ITEMS
  // entry at all while the rail item was disabled (nothing to route to),
  // so Topbar's breadcrumb rendered blank and the command palette
  // couldn't find it by name -- neither mattered while the route was
  // disabled; both do now that it's real.
  { slug: "outputs", label: "Outputs" },
  { slug: "settings", label: "Settings" },
  { slug: "team", label: "Team & Billing (now tabs inside Settings — People & Roles, Billing)" },
  { slug: "billing", label: "Billing (now part of Team & billing)" },
  { slug: "projects", label: "Projects" },
  { slug: "agents", label: "Agents (railed as \"Team\")" },
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
