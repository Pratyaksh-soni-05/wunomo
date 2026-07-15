"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ALL_NAV_ITEMS } from "./navItems";

interface Command {
  label: string;
  action: () => void;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const commands: Command[] = useMemo(
    () => ALL_NAV_ITEMS.map((item) => ({ label: item.label, action: () => router.push(`/${item.slug}`) })),
    [router]
  );

  const filtered = query ? commands.filter((c) => c.label.toLowerCase().includes(query.toLowerCase())) : commands;

  useEffect(() => {
    if (!open) return;
    setQuery("");
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function run(cmd: Command) {
    cmd.action();
    onClose();
  }

  return (
    <>
      <div className="cmd-palette-backdrop" onClick={onClose} />
      <div className="cmd-palette">
        <div className="cmd-input">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            autoFocus
            placeholder="Search actions, pages, sources..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span className="cmd-kbd">ESC</span>
        </div>
        <div className="cmd-results">
          <div className="cmd-section-label">Pages</div>
          {filtered.map((c) => (
            <div key={c.label} className="cmd-item" onClick={() => run(c)}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="2" />
              </svg>
              <span>{c.label}</span>
              <span className="cmd-kbd">↵</span>
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: "20px 14px", fontSize: 13, color: "var(--text-muted)" }}>No matches</div>
          )}
        </div>
      </div>
    </>
  );
}
