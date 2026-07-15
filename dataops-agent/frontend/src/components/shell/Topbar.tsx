"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { ALL_NAV_ITEMS } from "./navItems";
import { ThemeToggle } from "./ThemeToggle";
import { NotificationsPanel } from "./NotificationsPanel";
import { useToast } from "@/components/ui";
import type { DecodedUser } from "@/lib/api";

export function Topbar({
  onToggleSidebar,
  onOpenCommandPalette,
  user,
}: {
  onToggleSidebar: () => void;
  onOpenCommandPalette: () => void;
  user: DecodedUser | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const toast = useToast();
  const [notifOpen, setNotifOpen] = useState(false);

  const activeSlug = pathname.split("/")[1];
  const activeItem = ALL_NAV_ITEMS.find((i) => i.slug === activeSlug);
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  return (
    <header className="topbar">
      <button className="topbar-icon-btn" onClick={onToggleSidebar} title="Toggle sidebar">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      <div className="breadcrumb">
        <a onClick={() => router.push("/dashboard")} style={{ cursor: "pointer" }}>Wunomo</a>
        <span className="breadcrumb-sep">/</span>
        <span style={{ color: "var(--text-secondary)", fontWeight: 500 }}>{activeItem?.label ?? "..."}</span>
      </div>

      <div style={{ height: 16, width: 1, background: "var(--border)", flexShrink: 0 }} />

      <div className="topbar-search" onClick={onOpenCommandPalette}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <span className="topbar-search-ph">Search or run a command…</span>
        <kbd style={{ fontSize: 10, color: "var(--text-muted)", background: "var(--surface-hover)", border: "1px solid var(--border)", padding: "1px 5px", borderRadius: 4, fontFamily: "var(--font-mono)", fontWeight: 500, flexShrink: 0 }}>
          Ctrl+K
        </kbd>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
        <div className="ai-status">
          <div className="ai-dot" />
          <span>AXIOM Online</span>
        </div>
        <div style={{ height: 16, width: 1, background: "var(--border)" }} />
        <select
          className="env-select"
          defaultValue="prod"
          onChange={(e) => toast.push(`Switched to ${e.target.options[e.target.selectedIndex].text}`, "default")}
        >
          <option value="prod">Production</option>
          <option value="staging">Staging</option>
          <option value="dev">Development</option>
        </select>
        <ThemeToggle />
        <div style={{ position: "relative" }}>
          <button className="topbar-icon-btn" onClick={() => setNotifOpen((v) => !v)} title="Notifications">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            <div className="notif-dot" />
          </button>
          <NotificationsPanel open={notifOpen} onClose={() => setNotifOpen(false)} />
        </div>
        <div
          className="topbar-avatar"
          onClick={() => toast.push(user ? `${user.email} · ${user.role}` : "Not signed in", "default")}
          title={user?.email ?? "Account"}
        >
          {initials}
        </div>
      </div>
    </header>
  );
}
