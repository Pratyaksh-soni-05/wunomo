"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import type { Incident } from "@/lib/api";

export function HealthBanner({ incident, onDismiss }: { incident: Incident; onDismiss?: () => void }) {
  const router = useRouter();
  return (
    <div
      style={{
        background: "var(--warning-bg)",
        border: "1px solid var(--warning-border)",
        borderRadius: "var(--radius-lg)",
        padding: "14px 16px",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" strokeWidth="2">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      <div style={{ flex: 1 }}>
        <span className="font-medium text-sm">{incident.title}.</span>{" "}
        <span className="text-sm text-secondary">{incident.description}</span>
      </div>
      {/* Correction 2 (2026-08-19): an action inside a status banner must
          contrast with the banner, not match it — a warning-filled button
          on a warning-toned banner read as decoration, not a CTA. Default
          Button is Tier 1 / --accent-fill; the banner keeps its warning
          tone, the action doesn't inherit it. */}
      <Button size="sm" onClick={() => router.push("/incidents")}>
        Investigate
      </Button>
      {onDismiss && (
        <button
          className="btn btn-ghost btn-icon"
          aria-label="Dismiss"
          onClick={onDismiss}
          style={{ color: "var(--text-muted)" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
}
