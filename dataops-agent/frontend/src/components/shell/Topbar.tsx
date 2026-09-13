"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ALL_NAV_ITEMS } from "./navItems";
import { ThemeToggle } from "./ThemeToggle";
import { Badge } from "@/components/ui";
import { taskStatusVariant, taskStatusLabel } from "@/components/tasks/taskDisplay";
import { checkDbHealth, getToken, getActiveTasks } from "@/lib/api";

const HEALTH_POLL_MS = 30000;
// Wunomo Projects Phase 4 frontend, slice 12: 20s matches the old
// tenant-wide tasks/counts poll's own cadence while anything is active;
// backs off to 60s (not stopped entirely, unlike the single-task detail
// page's terminal-state case) once the rail is empty, since a task can
// become active again from someone else's action, not just this user's.
const ACTIVE_TASKS_POLL_MS = 20000;
const ACTIVE_TASKS_IDLE_POLL_MS = 60000;

export function Topbar({
  onToggleSidebar,
  onOpenCommandPalette,
}: {
  onToggleSidebar: () => void;
  onOpenCommandPalette: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [railOpen, setRailOpen] = useState(false);
  const railRef = useRef<HTMLDivElement>(null);
  const [dbHealthy, setDbHealthy] = useState<boolean | null>(null);
  const token = getToken();

  const activeSlug = pathname.split("/")[1];
  const activeItem = ALL_NAV_ITEMS.find((i) => i.slug === activeSlug);

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

  // Shared ["active-tasks"] query key -- ContextPanel polls the exact same
  // key while a chat session is open, so this is one network call serving
  // both surfaces, not two independent polls (see queryClient.tsx's single
  // app-wide QueryClient).
  const activeTasksQuery = useQuery({
    queryKey: ["active-tasks"],
    queryFn: () => getActiveTasks(token as string),
    enabled: !!token,
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? ACTIVE_TASKS_POLL_MS : ACTIVE_TASKS_IDLE_POLL_MS),
  });
  const activeTasks = activeTasksQuery.data ?? [];
  const attentionTasks = activeTasks.filter((t) => t.needs_attention);
  const otherTasks = activeTasks.filter((t) => !t.needs_attention);

  useEffect(() => {
    if (!railOpen) return;
    const onClick = (e: MouseEvent) => {
      if (railRef.current && !railRef.current.contains(e.target as Node)) setRailOpen(false);
    };
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("click", onClick);
    };
  }, [railOpen]);

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
        {activeTasksQuery.data !== undefined && (
          <div style={{ position: "relative" }} ref={railRef}>
            <button
              className="topbar-icon-btn"
              style={{
                display: "flex", alignItems: "center", gap: 6, width: "auto", padding: "0 10px",
                fontSize: 12, fontWeight: 600,
                color: attentionTasks.length > 0 ? "var(--warning)" : "var(--text-secondary)",
              }}
              onClick={() => setRailOpen((v) => !v)}
              title="Tasks not yet in a terminal state - running, queued, or waiting on you"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
              {activeTasks.length} active
            </button>
            {railOpen && (
              <div className="notif-panel">
                <div className="notif-panel-header">
                  <span className="font-semibold text-sm">Active Tasks</span>
                  {attentionTasks.length > 0 && <Badge variant="warning">{attentionTasks.length} need you</Badge>}
                </div>
                <div className="notif-list">
                  {activeTasks.length === 0 ? (
                    <div className="chat-empty-note" style={{ padding: 16 }}>Nothing active right now.</div>
                  ) : (
                    <>
                      {attentionTasks.map((t) => (
                        <div
                          key={t.id}
                          className="notif-item unread"
                          onClick={() => {
                            setRailOpen(false);
                            router.push(`/tasks/${t.id}`);
                          }}
                        >
                          <div className="notif-item-body">
                            <div className="font-medium text-sm truncate">{t.goal}</div>
                            <div className="text-xs text-muted" style={{ marginTop: 2 }}>
                              {t.agent_name ?? "Unassigned"} · <Badge variant={taskStatusVariant(t.status)}>{taskStatusLabel(t.status)}</Badge>
                            </div>
                            {t.action_text && (
                              <div className="text-xs" style={{ marginTop: 4, color: "var(--warning)", fontWeight: 600 }}>
                                {t.action_text}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                      {otherTasks.map((t) => (
                        <div
                          key={t.id}
                          className="notif-item"
                          onClick={() => {
                            setRailOpen(false);
                            router.push(`/tasks/${t.id}`);
                          }}
                        >
                          <div className="notif-item-body">
                            <div className="font-medium text-sm truncate">{t.goal}</div>
                            <div className="text-xs text-muted" style={{ marginTop: 2 }}>
                              {t.agent_name ?? "Unassigned"} · <Badge variant={taskStatusVariant(t.status)}>{taskStatusLabel(t.status)}</Badge>
                              {t.current_step && ` · Step ${t.current_step.step_index + 1}: ${t.current_step.description}`}
                            </div>
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </div>
                <div className="notif-panel-footer">
                  <a onClick={() => { setRailOpen(false); router.push("/tasks"); }}>View all tasks</a>
                </div>
              </div>
            )}
          </div>
        )}
        <div className="ai-status" title="Real-time database connectivity check">
          <div className="ai-dot" style={dbHealthy === false ? { background: "var(--danger)" } : undefined} />
          <span>{dbHealthy === false ? "AXIOM Offline" : "AXIOM Online"}</span>
        </div>
        <div style={{ height: 16, width: 1, background: "var(--border)" }} />
        <ThemeToggle />
      </div>
    </header>
  );
}
