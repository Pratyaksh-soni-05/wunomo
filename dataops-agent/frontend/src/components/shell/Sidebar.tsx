"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  RAIL_NAV_ITEMS, RAIL_FOOTER_ITEMS, ICON_PROJECT, ICON_NEW_PROJECT, type NavItem,
} from "./navItems";
import { useToast } from "@/components/ui";
import { WorkspacePicker } from "@/components/auth/WorkspacePicker";
import { WunomoMark } from "@/components/brand";
import {
  getToken, getMyWorkspaces, switchWorkspace, saveSession, clearSession,
  listProjects, getProjectChannels, getMergedApprovals, type DecodedUser,
} from "@/lib/api";

/**
 * The rail (2026-09-14, slice 3) — rebuilt to match
 * docs/design/wunomo-all-screens.html exactly, replacing the old ~19-item,
 * multi-section, domain-crossfading sidebar. See
 * docs/design/UI_REBUILD_INVENTORY.md, slice 3, for the full disagreement
 * log against the preview and the reasoning behind every deviation below.
 *
 * Collapse-to-icons is retired, not omitted — a deliberate decision
 * (findings item 90), not a gap: neither preview shows a collapsed state,
 * and 5 static items + a Projects section is short enough that collapsing
 * it no longer earns its own complexity the way it did against the old
 * sidebar's shape.
 */
export function Sidebar({
  mobileOpen,
  user,
}: {
  mobileOpen: boolean;
  user: DecodedUser | null;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  const [pickerOpen, setPickerOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);

  const workspacesQuery = useQuery({
    queryKey: ["my-workspaces"],
    queryFn: () => getMyWorkspaces(getToken() as string),
    enabled: pickerOpen,
  });

  async function handleSwitch(tenantId: string) {
    setSwitching(true);
    try {
      const result = await switchWorkspace(getToken() as string, tenantId);
      saveSession(result.access_token, result.tenant_id, result.user_id);
      // Full reload, not router.push — every React Query cache entry in
      // this app is implicitly scoped to whichever tenant was active when
      // it was fetched (unchanged reasoning from the pre-slice-3 sidebar).
      window.location.href = "/dashboard";
    } catch {
      toast.push("Couldn't switch workspaces. Try again.", "danger");
      setSwitching(false);
      setPickerOpen(false);
    }
  }

  function handleLogout() {
    clearSession();
    router.push("/login");
  }

  useEffect(() => {
    if (!accountMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (accountRef.current && !accountRef.current.contains(e.target as Node)) setAccountMenuOpen(false);
    };
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("click", onClick);
    };
  }, [accountMenuOpen]);

  // "Needs you" badge — real pending-approval count (getMergedApprovals is
  // the same risk-tiered feed the /approvals page itself renders, so the
  // rail's number never disagrees with what clicking through shows).
  const approvalsQuery = useQuery({
    queryKey: ["merged-approvals"],
    queryFn: () => getMergedApprovals(getToken() as string),
  });
  const needsYouCount = approvalsQuery.data?.count ?? 0;

  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(getToken() as string) });
  const projects = projectsQuery.data?.projects ?? [];

  // A project's own chats are only nested under it while you're actually
  // looking at that project (/projects/[id]) — matches the preview, whose
  // RAIL() template only ever injects .rsub items for the screen's own
  // active project, never for every project at once (see the slice 3
  // disagreement log). No project container exists yet (slice 5), so this
  // is the only "you're in project X" signal available today.
  const activeProjectId = pathname.startsWith("/projects/") ? pathname.split("/")[2] : null;
  const activeProjectChannelsQuery = useQuery({
    queryKey: ["project-channels", activeProjectId],
    queryFn: () => getProjectChannels(getToken() as string, activeProjectId as string),
    enabled: !!activeProjectId,
  });
  const activeProjectChannels = activeProjectChannelsQuery.data?.channels ?? [];

  function railItem(item: NavItem, badge?: ReactNode) {
    const href = `/${item.slug}`;
    const active = pathname === href;
    return (
      <Link key={item.slug} href={href} className={["sidebar-item", active ? "active" : ""].filter(Boolean).join(" ")}>
        <span className="sidebar-item-icon">{item.icon}</span>
        <span>{item.label}</span>
        {badge}
      </Link>
    );
  }

  return (
    <aside className={["sidebar", mobileOpen ? "mobile-open" : ""].filter(Boolean).join(" ")}>
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">
          <WunomoMark />
        </div>
        <div className="sidebar-logo-text">Wunomo</div>
      </div>

      <button className="sidebar-newproject" onClick={() => router.push("/projects?new=1")}>
        {ICON_NEW_PROJECT}
        New project
      </button>

      <nav className="sidebar-nav">
        {RAIL_NAV_ITEMS.map((item) =>
          railItem(
            item,
            item.slug === "approvals" && needsYouCount > 0 ? (
              <span className="badge-count badge-attention">{needsYouCount}</span>
            ) : undefined
          )
        )}

        <div className="sidebar-section">
          <Link href="/projects" className="sidebar-section-label sidebar-section-label-link">
            Projects
          </Link>
        </div>

        {projectsQuery.isLoading ? (
          <div className="sidebar-item-skeleton" />
        ) : (
          projects.map((p) => {
            const isActive = p.id === activeProjectId;
            return (
              <div key={p.id}>
                <Link
                  href={`/projects/${p.id}`}
                  className={["sidebar-item", pathname === `/projects/${p.id}` ? "active" : ""].filter(Boolean).join(" ")}
                >
                  <span className="sidebar-item-icon">{ICON_PROJECT}</span>
                  <span>{p.name}</span>
                </Link>
                {isActive && activeProjectChannels.map((c) => (
                  <Link key={c.id} href={`/chat?session=${c.id}`} className="sidebar-rsub">
                    {c.name}
                  </Link>
                ))}
              </div>
            );
          })
        )}
      </nav>

      <div className="sidebar-footer">
        {RAIL_FOOTER_ITEMS.map((item) => railItem(item))}

        <div className="sidebar-account" ref={accountRef}>
          <button className="sidebar-account-trigger" onClick={() => setAccountMenuOpen((v) => !v)}>
            <span className="sidebar-account-avatar">{initials}</span>
            <span className="sidebar-account-name">
              {user?.email ?? "—"}
              {user?.role ? ` · ${user.role}` : ""}
            </span>
          </button>

          {accountMenuOpen && (
            <div className="sidebar-account-menu">
              <button
                className="sidebar-account-menu-item"
                onClick={() => {
                  setAccountMenuOpen(false);
                  setPickerOpen(true);
                }}
              >
                Switch workspace
              </button>
              <button className="sidebar-account-menu-item" onClick={handleLogout}>
                Log out
              </button>
            </div>
          )}
        </div>
      </div>

      <WorkspacePicker
        open={pickerOpen}
        options={workspacesQuery.data?.options ?? []}
        currentTenantId={user?.tenant_id}
        title="Switch workspace"
        subtitle={switching ? "Switching…" : "Every workspace this email has an active account in."}
        onClose={() => !switching && setPickerOpen(false)}
        onPick={handleSwitch}
      />
    </aside>
  );
}
