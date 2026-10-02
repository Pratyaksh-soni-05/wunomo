"use client";

// Command Center (blueprint §05) -- "Working now" is the hero: one row per
// active task. §05's own mock also wants a numeric "{pct}% · ~{n} min
// left" on the right of each row, but that requires units_total/units_done
// -- fields that don't exist anywhere on Task/TaskStep (see lib/
// activeTaskDisplay.ts's header comment). Per explicit instruction: name
// the current step only, never a bare percentage, never a spinner --
// exactly liveWorkBadge/liveWorkStepLine, LiveWorkPanel's own already-
// honest pattern, reused verbatim rather than re-approximated here.
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui";
import { EmployeeAvatar } from "@/components/chat/EmployeeAvatar";
import { liveWorkBadge, liveWorkStepLine } from "@/lib/activeTaskDisplay";
import type { ActiveTaskRailItem } from "@/lib/api";

export function WorkingNowList({ tasks }: { tasks: ActiveTaskRailItem[] }) {
  const router = useRouter();

  return (
    <div className="working-now-card card">
      <div className="working-now-header">
        <h3>Working now</h3>
        <Badge variant="info">{tasks.length} task{tasks.length === 1 ? "" : "s"}</Badge>
      </div>
      {tasks.length === 0 ? (
        <div className="chat-empty-note">Nothing running right now.</div>
      ) : (
        <div className="working-now-rows">
          {tasks.map((t) => {
            const badge = liveWorkBadge(t.status);
            return (
              <div key={t.id} className="working-now-row" onClick={() => router.push(`/tasks/${t.id}`)}>
                <EmployeeAvatar name={t.agent_name ?? "AXIOM"} employeeType={null} isWorking size="default" />
                <div className="working-now-body">
                  <div className="working-now-title truncate">{t.goal}</div>
                  <div className="working-now-meta truncate">
                    {t.agent_name ?? "Unassigned"}
                    {t.project_name ? ` · ${t.project_name}` : ""} · {liveWorkStepLine(t)}
                  </div>
                </div>
                <Badge variant={badge.variant}>{badge.label}</Badge>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
