"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { WORKSPACE_NAV_SECTIONS, AXIOM_NAV_SECTIONS, isAxiomDomain, type NavDomain } from "./navItems";
import { useToast } from "@/components/ui";
import { WorkspacePicker } from "@/components/auth/WorkspacePicker";
import { WunomoMark } from "@/components/brand";
import { getToken, getSettings, getMyWorkspaces, switchWorkspace, saveSession, type DecodedUser } from "@/lib/api";

// Crossfade timing for the workspace<->AXIOM sidebar-content swap (2026-08
// IA restructure): fade the old domain's items out, then the new domain's
// items in. Each half uses --t-fast (100ms); the two halves together land
// close to --t-slow's 280ms, the same duration already used for this
// sidebar's own collapse/expand animation, so the swap doesn't feel like a
// different speed than the rest of the shell.
const FADE_OUT_MS = 140;

export function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  user,
}: {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  user: DecodedUser | null;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  // Item 1: the sidebar's top row is now a real workspace switcher, not
  // the hardcoded "Production" placeholder it used to be - real name via
  // the existing settings fetch, real option list fetched lazily (only
  // once the picker is actually opened, since most sessions never touch
  // this) via the same shape login's own WorkspacePicker already uses.
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: () => getSettings(getToken() as string) });
  const [pickerOpen, setPickerOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
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
      // Full reload, not router.push - every React Query cache entry in
      // this app is implicitly scoped to whichever tenant was active when
      // it was fetched, and nothing reconciles that on a tenant change.
      // A fresh load is the only way every already-mounted component is
      // guaranteed to refetch under the new tenant instead of silently
      // showing stale cross-tenant data for a few seconds.
      window.location.href = "/dashboard";
    } catch {
      toast.push("Couldn't switch workspaces. Try again.", "danger");
      setSwitching(false);
      setPickerOpen(false);
    }
  }

  const domain: NavDomain = isAxiomDomain(pathname) ? "axiom" : "workspace";

  // Derived synchronously from the current path on first render - a hard
  // refresh or deep link into any AXIOM-domain route (e.g. /tasks/[id])
  // must paint the AXIOM sidebar immediately, never workspace-then-flash.
  // `fading` only ever gets set true by the effect below, after a real
  // domain change post-mount - never on the initial render.
  const [displayDomain, setDisplayDomain] = useState<NavDomain>(domain);
  const [fading, setFading] = useState(false);
  const prevDomainRef = useRef<NavDomain>(domain);

  useEffect(() => {
    if (domain === prevDomainRef.current) return;
    prevDomainRef.current = domain;
    setFading(true);
    const t = setTimeout(() => {
      setDisplayDomain(domain);
      setFading(false);
    }, FADE_OUT_MS);
    return () => clearTimeout(t);
  }, [domain]);

  const sections = displayDomain === "axiom" ? AXIOM_NAV_SECTIONS : WORKSPACE_NAV_SECTIONS;

  return (
    <aside className={["sidebar", collapsed ? "collapsed" : "", mobileOpen ? "mobile-open" : ""].filter(Boolean).join(" ")}>
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">
          <WunomoMark />
        </div>
        <div className="sidebar-logo-text">
          Wunomo<span> AI</span>
        </div>
      </div>

      <div className="sidebar-workspace">
        {displayDomain === "axiom" ? (
          <button className="sidebar-back-link" onClick={() => router.push("/ai-employees")}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="m12 19-7-7 7-7" />
              <path d="M19 12H5" />
            </svg>
            <span>Back to Workspace</span>
          </button>
        ) : (
          <div className="sidebar-workspace-sel" onClick={() => setPickerOpen(true)}>
            <span className="sidebar-workspace-name">{settingsQuery.data?.settings.name ?? "Workspace"}</span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--sidebar-chevron)" strokeWidth="2.5">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </div>
        )}
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

      <nav className="sidebar-nav">
        <div key={displayDomain} className={["sidebar-nav-content", fading ? "fading" : ""].filter(Boolean).join(" ")}>
          {sections.map((section, i) => (
            <div key={i}>
              {section.label && (
                <div className="sidebar-section">
                  <div className="sidebar-section-label">{section.label}</div>
                </div>
              )}
              {section.items.map((item) => {
                const href = `/${item.slug}`;
                const active = pathname === href;
                return (
                  <Link key={item.slug} href={href} className={["sidebar-item", active ? "active" : ""].filter(Boolean).join(" ")}>
                    {item.icon}
                    <span>{item.label}</span>
                    {item.badge && (
                      <span className={["badge-count", item.badge.variant === "live" ? "badge-live" : ""].filter(Boolean).join(" ")}>
                        {item.badge.text}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </div>
      </nav>

      <div className="sidebar-footer">
        <div className="avatar" style={{ background: "var(--midnight-500)", border: "1.5px solid var(--sidebar-avatar-border)" }}>
          {initials}
        </div>
        <div className="sidebar-footer-info">
          <div className="sidebar-footer-name">{user?.email ?? "—"}</div>
          <div className="sidebar-footer-sub">{user?.role ?? ""}</div>
        </div>
        <button className="sidebar-toggle-btn" onClick={onToggle} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: collapsed ? "rotate(180deg)" : "none" }}>
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      </div>
    </aside>
  );
}
