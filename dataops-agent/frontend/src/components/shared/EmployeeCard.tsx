import { ReactNode } from "react";
import { Card, CardBody, Badge } from "@/components/ui";
import type { Employee } from "@/lib/employees";

// Shared by /ai-employees, the landing page's roster section, and /agents/
// hire - only the active employee's CTA differs between the first two
// callers (auth-aware on the landing page, always "Open AXIOM" on the
// already-auth-gated /ai-employees page), so that's the one thing left to
// the caller. `interactive` (default true, matching those two callers'
// existing look) controls the hover-elevate effect -- /agents/hire passes
// false because these cards are reference-only there (no cta, nothing
// happens on click): the same shadow-lift affordance that correctly signals
// "click me" on the other two pages was reading as a false promise on a
// page where the real action is the form below, not the cards (found live
// -- a user clicked the AXIOM card expecting it to do something).
export function EmployeeCard({
  employee: e, cta, interactive = true,
}: { employee: Employee; cta?: ReactNode; interactive?: boolean }) {
  return (
    <Card hover={interactive} style={{ position: "relative" }}>
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
