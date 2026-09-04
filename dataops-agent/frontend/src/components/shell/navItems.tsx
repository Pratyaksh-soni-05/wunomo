import { ReactNode } from "react";

export type NavDomain = "workspace" | "axiom";

export interface NavItem {
  slug: string;
  label: string;
  icon: ReactNode;
  phase?: number;
  badge?: { text: string; variant?: "count" | "danger" | "warning" | "live" };
  /** Which sidebar mode this item belongs to (2026-08 IA restructure —
   * see docs/context/SESSION_LOG.md). Every item needs exactly one. */
  domain: NavDomain;
}

export interface NavSection {
  label: string | null;
  items: NavItem[];
}

const icon = (path: ReactNode) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    {path}
  </svg>
);

export const NAV_SECTIONS: NavSection[] = [
  {
    label: null,
    items: [
      {
        slug: "dashboard",
        label: "Dashboard",
        phase: 9,
        domain: "workspace",
        icon: icon(
          <>
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
          </>
        ),
      },
    ],
  },
  {
    label: "Workspace",
    items: [
      {
        slug: "ai-employees",
        label: "AI Employees",
        phase: 18,
        domain: "workspace",
        icon: icon(
          <>
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </>
        ),
      },
    ],
  },
  {
    // Unlabeled on purpose, same convention as the Dashboard section above -
    // this is AXIOM's own domain (2026-08 IA restructure), only ever shown
    // by the AXIOM-mode sidebar (see AXIOM_NAV_SECTIONS below), where the
    // back-link header already establishes the context. A visible "AXIOM"
    // label here would be redundant with that header.
    label: null,
    items: [
      {
        slug: "chat",
        label: "AXIOM",
        phase: 10,
        badge: { text: "Live", variant: "live" },
        domain: "axiom",
        icon: icon(<path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />),
      },
      {
        slug: "tasks",
        label: "Tasks",
        domain: "axiom",
        icon: icon(
          <>
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
            <path d="m9 16 2 2 4-4" />
          </>
        ),
      },
      {
        // Wunomo Projects Phase 1, part two -- lives alongside AXIOM/Tasks,
        // not under Data or Admin, since a project's whole job is grouping
        // the agents doing the work, not the data itself.
        slug: "projects",
        label: "Projects",
        domain: "axiom",
        icon: icon(
          <>
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </>
        ),
      },
    ],
  },
  {
    label: "Data",
    items: [
      {
        slug: "sources",
        label: "Data Sources",
        phase: 12,
        domain: "axiom",
        icon: icon(
          <>
            <ellipse cx="12" cy="5" rx="9" ry="3" />
            <path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
            <path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" />
          </>
        ),
      },
      {
        slug: "catalog",
        label: "Data Catalog",
        phase: 14,
        domain: "axiom",
        icon: icon(
          <>
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </>
        ),
      },
      {
        slug: "pipelines",
        label: "Pipelines",
        phase: 12,
        domain: "axiom",
        icon: icon(<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />),
      },
      {
        slug: "transforms",
        label: "Transforms",
        phase: 14,
        domain: "axiom",
        icon: icon(
          <>
            <polyline points="16 18 22 12 16 6" />
            <polyline points="8 6 2 12 8 18" />
          </>
        ),
      },
    ],
  },
  {
    // Axiom-domain items only - kept under its original label. Approvals
    // used to also live in this section object, but shares no items with
    // either domain the other doesn't have, so it's now split into its
    // own section right below with its own label ("Governance") rather
    // than reusing this one - a shared NavSection's label is rendered by
    // BOTH domain-filtered views (sectionsForDomain only filters items,
    // not the label), so relabeling this section would have also
    // relabeled the axiom sidebar's own group - the one that literally
    // contains a "Governance" nav item - to "Governance" too.
    label: "Quality & Ops",
    items: [
      {
        slug: "quality",
        label: "Quality",
        phase: 12,
        domain: "axiom",
        icon: icon(<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />),
      },
      {
        slug: "incidents",
        label: "Incidents",
        phase: 12,
        domain: "axiom",
        icon: icon(
          <>
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </>
        ),
      },
      {
        slug: "governance",
        label: "Governance",
        phase: 12,
        domain: "axiom",
        icon: icon(
          <>
            <circle cx="12" cy="5" r="2" />
            <circle cx="5" cy="19" r="2" />
            <circle cx="19" cy="19" r="2" />
            <line x1="12" y1="7" x2="5" y2="17" />
            <line x1="12" y1="7" x2="19" y2="17" />
            <line x1="5" y1="19" x2="19" y2="19" />
          </>
        ),
      },
      {
        slug: "automations",
        label: "Automations",
        domain: "axiom",
        icon: icon(<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />),
      },
      {
        slug: "cicd",
        label: "CI / CD",
        domain: "axiom",
        icon: icon(
          <>
            <circle cx="18" cy="18" r="3" />
            <circle cx="6" cy="6" r="3" />
            <path d="M13 6h3a2 2 0 0 1 2 2v7" />
            <line x1="6" y1="9" x2="6" y2="21" />
          </>
        ),
      },
    ],
  },
  {
    // Workspace-only, split out of the section above (see its comment) -
    // renamed from "Quality & Ops" to "Governance" per explicit request:
    // it's a work queue, not a settings screen, so it doesn't belong
    // under Admin either.
    label: "Governance",
    items: [
      {
        slug: "approvals",
        label: "Approvals",
        phase: 12,
        domain: "workspace",
        icon: icon(
          <>
            <polyline points="9 11 12 14 22 4" />
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
          </>
        ),
      },
    ],
  },
  {
    label: "Admin",
    items: [
      {
        slug: "audit",
        label: "Audit Logs",
        domain: "workspace",
        icon: icon(
          <>
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </>
        ),
      },
      {
        slug: "team",
        label: "Team",
        phase: 17,
        domain: "workspace",
        icon: icon(
          <>
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </>
        ),
      },
      {
        slug: "billing",
        label: "Billing",
        phase: 17,
        domain: "workspace",
        icon: icon(
          <>
            <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
            <line x1="1" y1="10" x2="23" y2="10" />
          </>
        ),
      },
      {
        slug: "settings",
        label: "Settings",
        phase: 17,
        domain: "workspace",
        icon: icon(
          <>
            <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </>
        ),
      },
    ],
  },
];

// Union of every item regardless of domain - unchanged in shape/order from
// before the 2026-08 IA restructure. CommandPalette (Ctrl+K search) and
// Topbar (breadcrumb label lookup) both depend on this staying the full
// set - never filter it down to one domain.
export const ALL_NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);

function sectionsForDomain(domain: NavDomain): NavSection[] {
  return NAV_SECTIONS
    .map((s) => ({ ...s, items: s.items.filter((i) => i.domain === domain) }))
    .filter((s) => s.items.length > 0);
}

/** The default sidebar - everything except AXIOM's own chat/Tasks domain. */
export const WORKSPACE_NAV_SECTIONS: NavSection[] = sectionsForDomain("workspace");

/** Shown only while inside AXIOM's own routes (see isAxiomDomain below). */
export const AXIOM_NAV_SECTIONS: NavSection[] = sectionsForDomain("axiom");

/**
 * Route -> sidebar-domain mapping (2026-08 IA restructure). Single source
 * of truth - Sidebar.tsx calls this rather than hand-rolling its own path
 * check. Prefix match (not exact), so /tasks/[id] deep links count as
 * AXIOM's domain the same as the /tasks list itself.
 *
 * Expanded (2026-08-19) to cover every route whose nav item now carries
 * domain: "axiom" above - keep this list and the domain assignments on
 * those items in sync; nothing derives one from the other automatically.
 * Approvals deliberately stays out of this list (and domain: "workspace"
 * on its own item) - CI/CD deployment approvals are webhook-driven, not
 * AXIOM-initiated, and burying them behind an AI employee would make them
 * unreachable for their main use case.
 */
const AXIOM_DOMAIN_PREFIXES = [
  "/chat", "/tasks", "/projects", "/sources", "/catalog", "/pipelines", "/transforms",
  "/quality", "/incidents", "/governance", "/automations", "/cicd",
];

export function isAxiomDomain(pathname: string): boolean {
  return AXIOM_DOMAIN_PREFIXES.some((p) => pathname.startsWith(p));
}
