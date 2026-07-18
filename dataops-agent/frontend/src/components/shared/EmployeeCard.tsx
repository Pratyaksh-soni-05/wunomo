import { ReactNode } from "react";
import { Card, CardBody, Badge } from "@/components/ui";
import type { Employee } from "@/lib/employees";

// Shared by /ai-employees and the landing page's roster section - only the
// active employee's CTA differs between callers (auth-aware on the landing
// page, always "Open AXIOM" on the already-auth-gated /ai-employees page),
// so that's the one thing left to the caller.
export function EmployeeCard({ employee: e, cta }: { employee: Employee; cta?: ReactNode }) {
  return (
    <Card hover style={{ position: "relative" }}>
      {!e.active && (
        <div className="locked-overlay">
          <Badge variant="gray">Coming Soon</Badge>
        </div>
      )}
      <CardBody>
        <div className="flex items-start justify-between" style={{ marginBottom: 12 }}>
          <div className="flex items-center gap-3">
            <div
              className={`badge badge-${e.variant}`}
              style={{ width: 40, height: 40, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14 }}
            >
              {e.name.slice(0, 2)}
            </div>
            <div>
              <div className="font-display" style={{ fontSize: 15, fontWeight: 600 }}>{e.name}</div>
              <div className="text-muted text-sm">{e.role}</div>
            </div>
          </div>
          {e.active && <Badge variant="success">Active</Badge>}
        </div>
        <p className="text-muted text-sm" style={{ marginBottom: 12, lineHeight: 1.5 }}>{e.desc}</p>
        <div className="flex flex-wrap gap-1" style={{ marginBottom: 14 }}>
          {e.caps.map((c) => (
            <span key={c} className="badge badge-gray" style={{ fontSize: 11 }}>{c}</span>
          ))}
        </div>
        {e.active && cta && (
          <div style={{ paddingTop: 12, borderTop: "1px solid var(--border)" }}>
            {cta}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
