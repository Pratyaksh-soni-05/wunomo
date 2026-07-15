"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";

interface Notification {
  id: number;
  type: "success" | "danger" | "warning" | "info";
  title: string;
  body: string;
  time: string;
  read: boolean;
}

// Placeholder content — no notifications backend exists yet (lands with the
// real Dashboard/Incidents wiring in later phases). Static so this panel has
// something to render for the Phase 7 shell/interaction verification.
const PLACEHOLDER_NOTIFICATIONS: Notification[] = [
  { id: 1, type: "warning", title: "Pipeline failed", body: "Daily Sales Aggregation failed at 06:00", time: "2m ago", read: false },
  { id: 2, type: "info", title: "Approval needed", body: "Deploy commit abc123 to production", time: "15m ago", read: false },
  { id: 3, type: "success", title: "Quality check passed", body: "Customer data contract validated", time: "1h ago", read: true },
  { id: 4, type: "danger", title: "Schema drift detected", body: "Source: DataOps Postgres — 1 column added", time: "2h ago", read: true },
];

export function NotificationsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState(PLACEHOLDER_NOTIFICATIONS);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("click", onClick);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="notif-panel" ref={ref}>
      <div className="notif-panel-header">
        <span className="font-semibold text-sm">Notifications</span>
        <Button variant="ghost" size="sm" onClick={() => setItems((prev) => prev.map((n) => ({ ...n, read: true })))}>
          Mark all read
        </Button>
      </div>
      <div className="notif-list">
        {items.map((n) => (
          <div
            key={n.id}
            className={["notif-item", !n.read ? "unread" : ""].filter(Boolean).join(" ")}
            onClick={() => setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)))}
          >
            <span className={`status-dot ${n.type} pulse`} style={{ marginTop: 5, flexShrink: 0 }} />
            <div className="notif-item-body">
              <div className="font-medium text-sm">{n.title}</div>
              <div className="text-muted text-sm" style={{ marginTop: 2 }}>{n.body}</div>
              <div className="text-xs text-muted" style={{ marginTop: 4 }}>{n.time}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="notif-panel-footer">
        <a>View all notifications</a>
      </div>
    </div>
  );
}
