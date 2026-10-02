"use client";

// Command Center (blueprint §05) -- project cards strip, "same precedence
// as ProjectHeader" (computeProjectStatusBadge, shared via
// lib/projectStatusBadge.ts -- see that file's own header comment).
//
// Scope decision: built entirely from getActiveTasks() (already carries
// project_id/project_name/agent_id/agent_name per row, no extra call).
// This deliberately excludes the blueprint mock's "6 of 9 tasks done"
// lifetime counter -- getting that honestly requires this project's own
// agent roster (an N+1 GET /projects/{id}/agents per card) and doesn't
// even fit the page's own governing rule ("if nothing happened in the
// last 24h, it is not on this page") since a lifetime completion count
// isn't a last-24h fact. A project with zero rows in getActiveTasks() has
// had nothing happen and is correctly absent from this strip.
import type { CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui";
import { EmployeeAvatar } from "@/components/chat/EmployeeAvatar";
import { computeProjectStatusBadge } from "@/lib/projectStatusBadge";
import type { ActiveTaskRailItem } from "@/lib/api";

interface ProjectGroup {
  id: string;
  name: string;
  tasks: ActiveTaskRailItem[];
}

function groupByProject(tasks: ActiveTaskRailItem[]): ProjectGroup[] {
  const map = new Map<string, ProjectGroup>();
  for (const t of tasks) {
    if (!t.project_id) continue;
    const g = map.get(t.project_id) ?? { id: t.project_id, name: t.project_name ?? "Untitled project", tasks: [] };
    g.tasks.push(t);
    map.set(t.project_id, g);
  }
  return Array.from(map.values());
}

export function ProjectStatusStrip({ activeTasks }: { activeTasks: ActiveTaskRailItem[] }) {
  const router = useRouter();
  const groups = groupByProject(activeTasks);

  if (groups.length === 0) return null;

  return (
    <div className="project-status-strip" style={{ "--project-cols": Math.min(groups.length, 3) } as CSSProperties}>
      {groups.map((g) => {
        const badge = computeProjectStatusBadge(g.tasks);
        const agents = Array.from(new Map(g.tasks.map((t) => [t.agent_id ?? t.agent_name ?? "", t])).values()).slice(0, 4);
        return (
          <div key={g.id} className="project-status-card card" onClick={() => router.push(`/projects/${g.id}`)}>
            <div className="project-status-card-top">
              <span className="project-status-card-name truncate">{g.name}</span>
              <Badge variant={badge.variant}>{badge.label}</Badge>
            </div>
            <div className="project-status-card-subtitle">
              {g.tasks.length} task{g.tasks.length === 1 ? "" : "s"} active
            </div>
            <div className="avatar-stack">
              {agents.map((t, i) => (
                <div key={i} className="avatar-stack-item">
                  <EmployeeAvatar name={t.agent_name ?? "AXIOM"} employeeType={null} size="sm" />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
