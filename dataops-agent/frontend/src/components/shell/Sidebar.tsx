"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  RAIL_NAV_ITEMS, ICON_PROJECT, ICON_NEW_PROJECT, type NavItem,
} from "./navItems";
import { useToast } from "@/components/ui";
import { WorkspacePicker } from "@/components/auth/WorkspacePicker";
import { WunomoMark } from "@/components/brand";
import {
  getToken, getMyWorkspaces, switchWorkspace, saveSession, clearSession,
  listProjects, type DecodedUser,
} from "@/lib/api";
import { useNeedsYou } from "@/lib/needsYou";

/**
 * The rail (2026-09-14, slice 3) — rebuilt to match
 * docs/design/wunomo-all-screens.html exactly, replacing the old ~19-item,
 * multi-section, domain-crossfading sidebar. See
 * docs/design/UI_REBUILD_INVENTORY.md, slice 3, for the full disagreement
 * log against the preview and the reasoning behind every deviation below.
 *
 * IA-rail pass (blueprint §03, 2026-09-29): restructured to §03's seven
 * named destinations + Scheduled (kept, real and useful, §03's own
 * omission — see this pass's report). RAIL_NAV_ITEMS renders as ONE
 * uninterrupted block (Command Center, Projects, Team, Approvals,
 * Outputs, Connections, Scheduled, Settings, in that order) — a same-pass
 * follow-up fix: the first cut split Command Center out above the live
 * Projects list and Settings into a separate footer, which left "PROJECTS"
 * as a bare section-label link (not a real nav item) and made the other
 * five read as that project's children rather than workspace-level
 * siblings. §03 has no such hierarchy; all eight are peers. The live
 * recent-projects list renders strictly AFTER this whole block, as its
 * own clearly-subordinate section.
 *
 * The nested per-project channel list (under whichever project was
 * active) is removed this pass — not a straight deletion, a real bug
 * fix: its links pointed at /chat?session={id}, the old global chat
 * route, which drops the user out of the project shell (no header, no
 * tabs) even though the link lived inside that project's own row.
 * Channel switching already lives in the project header's "⋯" menu
 * (blueprint chrome pass), which stays inside the shell correctly — see
 * this pass's own report for what, if anything, still needs the rail's
 * copy.
 *
 * Collapse-to-icons is retired, not omitted — a deliberate decision
 * (findings item 90), not a gap: neither preview shows a collapsed state,
 * and a handful of static items + a Projects section is short enough
 * that collapsing it no longer earns its own complexity the way it did
 * against the old sidebar's shape.
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
      window.location.href = "/home";
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

  // "Needs you" badge (slice 9, 2026-09-15) — the same combined,
  // deduped derivation the Needs You screen itself renders (lib/needsYou.ts),
  // so the rail's number can never disagree with what clicking through
  // shows again. Before this slice it counted getMergedApprovals().count
  // only, silently blind to every task needing attention (a DRAFT_PLAN,
  // a dead PAUSED_FAILED_STEP) — this fixes that, not just relabels it.
  const needsYou = useNeedsYou(getToken() as string);
  const needsYouCount = needsYou.count;

  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(getToken() as string) });
  const projects = projectsQuery.data?.projects ?? [];

  // Signals "you're in project X" for highlighting its row in the
  // Projects list below — the per-project nested channel list this used
  // to also drive is gone (IA-rail pass; see this file's own top comment
  // for the real bug that removal fixes, not just a preview-fidelity
  // choice).
  const activeProjectId = pathname.startsWith("/projects/") ? pathname.split("/")[2] : null;

  function railItem(item: NavItem, badge?: ReactNode) {
    if (item.disabled) {
      return (
        <div
          key={item.slug}
          className="sidebar-item disabled"
          title={item.disabledReason}
          aria-disabled="true"
        >
          <span className="sidebar-item-icon">{item.icon}</span>
          <span>{item.label}</span>
        </div>
      );
    }
    const href = `/${item.slug}`;
    // "Projects" is the one item with real sub-routes reachable from
    // elsewhere in the app (/projects/[id]/...) -- §03 itself describes
    // this destination as "the list, then the workspace," so both count
    // as being "in Projects." Every other item here is a bare leaf route.
    const active = item.slug === "projects" ? pathname.startsWith("/projects") : pathname === href;
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

        {/* Recent projects -- strictly below the whole nav block above,
            clearly subordinate to it (plain text label, not a link:
            "Projects" above already is the real destination, a second
            link to the same place here would be redundant). */}
        <div className="sidebar-section">
          <span className="sidebar-section-label">Recent</span>
        </div>

        {projectsQuery.isLoading ? (
          <div className="sidebar-item-skeleton" />
        ) : (
          projects.map((p) => {
            const isActive = p.id === activeProjectId;
            return (
              <Link
                key={p.id}
                href={`/projects/${p.id}/chat`}
                className={["sidebar-item", isActive ? "active" : ""].filter(Boolean).join(" ")}
              >
                <span className="sidebar-item-icon">{ICON_PROJECT}</span>
                <span>{p.name}</span>
              </Link>
            );
          })
        )}
      </nav>

      <div className="sidebar-footer">
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
