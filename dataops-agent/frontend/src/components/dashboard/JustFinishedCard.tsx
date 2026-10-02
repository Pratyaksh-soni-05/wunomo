"use client";

// Command Center (blueprint §05) -- "Just finished": green dot, filename,
// "agent · time ago · trust N", "Open" button. This product has no output-
// file record on a completed Task in list form (no filename, no trust
// score anywhere on TaskSummary) without an N+1 GET /tasks/{id} per row --
// same "don't fabricate a filename/trust badge" call already made for
// shape D (EmployeeResult) earlier this build. Shown instead: the task's
// own goal (what was asked, always real) as the headline, agent name +
// real completed_at recency as the meta line. No trust score anywhere.
import { useRouter } from "next/navigation";
import { EmployeeAvatar } from "@/components/chat/EmployeeAvatar";
import { timeAgo } from "@/lib/dates";
import type { TaskSummary, AgentListItem } from "@/lib/api";

export function JustFinishedCard({
  tasks, agentsById,
}: {
  tasks: TaskSummary[];
  agentsById: Map<string, AgentListItem>;
}) {
  return (
    <div className="just-finished-card card">
      <div className="spend-cycle-label">Just finished</div>
      {tasks.length === 0 ? (
        <div className="chat-empty-note">Nothing completed in the last 24 hours.</div>
      ) : (
        <div className="just-finished-rows">
          {tasks.map((t) => {
            const agent = t.agent_id ? agentsById.get(t.agent_id) : undefined;
            return <JustFinishedRow key={t.id} task={t} agentName={agent?.name ?? null} employeeType={agent?.employee_type ?? null} />;
          })}
        </div>
      )}
    </div>
  );
}

function JustFinishedRow({
  task, agentName, employeeType,
}: {
  task: TaskSummary;
  agentName: string | null;
  employeeType: string | null;
}) {
  const router = useRouter();
  return (
    <div className="just-finished-row" onClick={() => router.push(`/tasks/${task.id}`)}>
      <span className="just-finished-dot" aria-hidden="true" />
      <EmployeeAvatar name={agentName ?? "AXIOM"} employeeType={employeeType} size="sm" />
      <div className="just-finished-body">
        <div className="just-finished-title">{task.goal}</div>
        <div className="just-finished-meta truncate">
          {agentName ?? "Unassigned"} · {timeAgo(task.completed_at)}
        </div>
      </div>
    </div>
  );
}
