import { ReactNode } from "react";

export interface NavItem {
  slug: string;
  label: string;
  icon: ReactNode;
  phase?: number;
  badge?: { text: string; variant?: "count" | "danger" | "warning" | "live" };
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
        slug: "chat",
        label: "AXIOM",
        phase: 10,
        badge: { text: "Live", variant: "live" },
        icon: icon(<path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />),
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
        icon: icon(<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />),
      },
      {
        slug: "transforms",
        label: "Transforms",
        phase: 14,
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
    label: "Quality & Ops",
    items: [
      {
        slug: "quality",
        label: "Quality",
        phase: 12,
        icon: icon(<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />),
      },
      {
        slug: "incidents",
        label: "Incidents",
        phase: 12,
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
        icon: icon(<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />),
      },
      {
        slug: "cicd",
        label: "CI / CD",
        icon: icon(
          <>
            <circle cx="18" cy="18" r="3" />
            <circle cx="6" cy="6" r="3" />
            <path d="M13 6h3a2 2 0 0 1 2 2v7" />
            <line x1="6" y1="9" x2="6" y2="21" />
          </>
        ),
      },
      {
        slug: "approvals",
        label: "Approvals",
        phase: 12,
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
    label: "Analytics",
    items: [
      {
        slug: "analytics",
        label: "Analytics",
        icon: icon(
          <>
            <line x1="18" y1="20" x2="18" y2="10" />
            <line x1="12" y1="20" x2="12" y2="4" />
            <line x1="6" y1="20" x2="6" y2="14" />
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

export const ALL_NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);
