"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { ALL_NAV_ITEMS } from "./navItems";
import { ThemeToggle } from "./ThemeToggle";
import { clearSession, checkDbHealth, getToken, getTaskCounts, type DecodedUser } from "@/lib/api";

const HEALTH_POLL_MS = 30000;
const TASK_COUNT_POLL_MS = 20000;

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
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const [dbHealthy, setDbHealthy] = useState<boolean | null>(null);
  const [activeTaskCount, setActiveTaskCount] = useState<number | null>(null);

  const activeSlug = pathname.split("/")[1];
  const activeItem = ALL_NAV_ITEMS.find((i) => i.slug === activeSlug);
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const ok = await checkDbHealth();
      if (!cancelled) setDbHealthy(ok);
    };
    poll();
    const interval = setInterval(poll, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const token = getToken();
      if (!token) return;
      try {
        const { active } = await getTaskCounts(token);
        if (!cancelled) setActiveTaskCount(active);
      } catch {
        // Non-fatal - leave the last known count in place rather than
        // flashing to a misleading 0.
      }
    };
    poll();
    const interval = setInterval(poll, TASK_COUNT_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!accountOpen) return;
    const onClick = (e: MouseEvent) => {
      if (accountRef.current && !accountRef.current.contains(e.target as Node)) setAccountOpen(false);
    };
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("click", onClick);
    };
  }, [accountOpen]);

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
        {activeTaskCount !== null && (
          <button
            className="topbar-icon-btn"
            style={{ display: "flex", alignItems: "center", gap: 6, width: "auto", padding: "0 10px", fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}
            onClick={() => router.push("/tasks")}
            title="Tasks not yet in a terminal state - running, queued, or waiting on you"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            {activeTaskCount} active
          </button>
        )}
        <div className="ai-status" title="Real-time database connectivity check">
          <div className="ai-dot" style={dbHealthy === false ? { background: "var(--danger)" } : undefined} />
          <span>{dbHealthy === false ? "AXIOM Offline" : "AXIOM Online"}</span>
        </div>
        <div style={{ height: 16, width: 1, background: "var(--border)" }} />
        <ThemeToggle />
        <div style={{ position: "relative" }} ref={accountRef}>
          <div
            className="topbar-avatar"
            onClick={() => setAccountOpen((v) => !v)}
            title={user?.email ?? "Account"}
          >
            {initials}
          </div>
          {accountOpen && (
            <div className="notif-panel" style={{ width: 220 }}>
              <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
                <div className="text-sm font-medium truncate">{user?.email ?? "Not signed in"}</div>
                <div className="text-xs text-muted" style={{ textTransform: "capitalize" }}>{user?.role ?? ""}</div>
              </div>
              <button
                className="flex items-center gap-2"
                style={{
                  color: "var(--text-secondary)", width: "100%", minHeight: 44, padding: "0 16px",
                  fontSize: 13, textAlign: "left", background: "none", border: "none", cursor: "pointer",
                }}
                onClick={() => {
                  clearSession();
                  router.push("/login");
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                <span>Log out</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
