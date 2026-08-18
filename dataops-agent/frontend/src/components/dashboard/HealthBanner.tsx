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
      <Button
        size="sm"
        style={{ background: "var(--warning-fill)", color: "var(--on-dark)", borderColor: "var(--warning-fill)" }}
        onClick={() => router.push("/incidents")}
      >
        Investigate
      </Button>
      {onDismiss && (
        <button
          aria-label="Dismiss"
          onClick={onDismiss}
          style={{
            background: "none", border: "none", cursor: "pointer", padding: 4,
            color: "var(--text-muted)", display: "flex", alignItems: "center",
          }}
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
