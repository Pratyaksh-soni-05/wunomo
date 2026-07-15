"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_SECTIONS } from "./navItems";
import { useToast } from "@/components/ui";
import type { DecodedUser } from "@/lib/api";

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
  const toast = useToast();
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  return (
    <aside className={["sidebar", collapsed ? "collapsed" : "", mobileOpen ? "mobile-open" : ""].filter(Boolean).join(" ")}>
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">
          <svg width="17" height="17" viewBox="0 0 28 28" fill="none">
            <path d="M14 2L26 9V19L14 26L2 19V9L14 2Z" fill="white" fillOpacity="0.15" stroke="white" strokeWidth="1.5" />
            <path d="M14 7L22 12V18L14 23L6 18V12L14 7Z" fill="white" fillOpacity="0.1" stroke="white" strokeWidth="1.5" />
            <circle cx="14" cy="15" r="3.5" fill="white" />
          </svg>
        </div>
        <div className="sidebar-logo-text">
          Wunomo<span> AI</span>
        </div>
      </div>

      <div className="sidebar-workspace">
        <div
          className="sidebar-workspace-sel"
          onClick={() => toast.push("Workspace switcher — coming in Phase 15", "default")}
        >
          <span className="sidebar-workspace-name">Production</span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="2.5">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_SECTIONS.map((section, i) => (
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
      </nav>

      <div className="sidebar-footer">
        <div className="avatar" style={{ background: "var(--midnight-500)", border: "1.5px solid rgba(255,255,255,0.2)" }}>
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
