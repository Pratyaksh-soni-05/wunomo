"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Select, Badge, Tabs, Skeleton } from "@/components/ui";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import { EmployeeAvatar } from "./EmployeeAvatar";
import { ToolCallBlock } from "./ToolCallBlock";
import { useProjectScope } from "@/lib/projectScope";
import { EMPLOYEE_TYPE_LABEL } from "@/lib/employeeTypes";
import { liveWorkBadge, liveWorkStepLine } from "@/lib/activeTaskDisplay";
import type { LocalChatMessage } from "./types";
import {
  getActiveTasks, getSources,
  type ActiveTaskRailItem, type ChannelMemberAgent, type ChatContext, type PendingApproval,
} from "@/lib/api";

const ACTIVE_TASKS_POLL_MS = 20000;
const ACTIVE_TASKS_IDLE_POLL_MS = 60000;

/**
 * §7.6's Live work panel -- replaces ProjectContextPanel (renamed, not
 * just relabeled: this pane's whole job changed). Four tabs matching
 * spec exactly: Live work (new, default, functional), Team (the old
 * "Agents" tab's roster + Hire another, moved across unchanged), Data
 * (the old Sources list + Attach Context picker, moved across
 * unchanged -- explicitly NOT disabled per spec's own note: spec assumed
 * nothing real existed here yet, but it does), Files (disabled -- there
 * really is nothing behind it until the Output model lands in stage 6).
 *
 * The old "Activity" tab's two sections split differently: Active Tasks
 * is superseded by Live work's real task cards (§7.6's own anatomy, not
 * the old bare chat-tool-log-item list); the Tool Calls log is a
 * different thing -- history, and Live work explicitly has no archive --
 * kept reachable inside Live work under a closed-by-default "Recent
 * activity" <details> section rather than dropped.
 *
 * Task cards are built from GET /tasks/active (ActiveTaskRailItem),
 * filtered to this session exactly like the old Active Tasks section
 * was -- see this build's own report for the real fields §7.6's table
 * assumes (a numeric %, an upstream task's agent name) that don't exist
 * anywhere on Task/TaskStep, and how liveWorkBadge/liveWorkStepLine below
 * degrade honestly against what's actually there.
 */
export function LiveWorkPanel({
  token,
  projectId,
  messages,
  attachedContext,
  onAttach,
  onClear,
  onGoToApprovals,
  currentUserRole,
  sessionId,
  channelAgents,
  mobileOpen,
}: {
  token: string;
  projectId: string;
  messages: LocalChatMessage[];
  attachedContext: ChatContext | null;
  onAttach: (ctx: ChatContext) => void;
  onClear: () => void;
  onGoToApprovals: () => void;
  currentUserRole?: string | null;
  sessionId: string | null;
  channelAgents?: ChannelMemberAgent[];
  // Below 1180px this pane is a hidden-by-default overlay/bottom-sheet
  // (§7.1's Responsive note) toggled from MessageThread's header --
  // undefined/true above that breakpoint, where CSS keeps it always
  // visible regardless of this prop (see .livework-panel's own rule).
  mobileOpen?: boolean;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [tab, setTab] = useState("livework");
  const [hireOpen, setHireOpen] = useState(false);

  const { agentRoster, sourceIds, loading: scopeLoading } = useProjectScope(token, projectId);
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });
  const projectSources = (sourcesQuery.data?.sources ?? []).filter((s) => sourceIds.has(s.id));

  const toolLog = messages.flatMap((m) =>
    (m.tool_calls || []).map((call) => ({ call, approval: m.approvals?.find((a: PendingApproval) => a.name === call.tool) }))
  );

  const activeTasksQuery = useQuery({
    queryKey: ["active-tasks"],
    queryFn: () => getActiveTasks(token),
    enabled: !!token,
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? ACTIVE_TASKS_POLL_MS : ACTIVE_TASKS_IDLE_POLL_MS),
  });
  const sessionTasks = sessionId
    ? (activeTasksQuery.data ?? []).filter((t) => t.originating_session_id === sessionId)
    : [];

  const agentsById = new Map((channelAgents ?? []).map((a) => [a.id, a]));

  return (
    <div className={["chat-sidebar-right", "livework-panel", mobileOpen ? "open" : ""].filter(Boolean).join(" ")}>
      <Tabs
        items={[
          { id: "livework", label: "Live work" },
          { id: "team", label: "Team" },
          { id: "files", label: "Files", disabled: true },
          { id: "data", label: "Data" },
        ]}
        activeId={tab}
        onChange={setTab}
      />

      {tab === "livework" && (
        <>
          <div className="chat-context-section">
            {sessionTasks.length === 0 ? (
              <div className="livework-empty">
                <div className="livework-empty-title">Nothing running</div>
                <div className="livework-empty-body">
                  Tag an employee in the chat and their work will appear here as it happens.
                </div>
              </div>
            ) : (
              sessionTasks.map((t) => (
                <TaskCard key={t.id} task={t} agentsById={agentsById} onClick={() => router.push(`/tasks/${t.id}`)} />
              ))
            )}
          </div>

          {toolLog.length > 0 && (
            <details className="chat-context-section livework-recent-activity">
              <summary>Recent activity</summary>
              <div style={{ marginTop: 8 }}>
                {toolLog.map((entry, i) => (
                  <div className="chat-tool-log-item" key={i}>
                    <ToolCallBlock call={entry.call} approval={entry.approval} onGoToApprovals={onGoToApprovals} currentUserRole={currentUserRole} />
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}

      {tab === "team" && (
        <div className="chat-context-section">
          {scopeLoading ? (
            <Skeleton height={40} style={{ borderRadius: 6, marginBottom: 6 }} />
          ) : agentRoster.length === 0 ? (
            <div className="chat-empty-note">No agents in this project yet.</div>
          ) : (
            agentRoster.map((a) => (
              <div
                key={a.id} className="chat-tool-log-item" style={{ cursor: "pointer" }}
                onClick={() => router.push(`/agents/${a.id}`)}
              >
                <div className="font-medium text-sm">{a.name}</div>
                <div className="text-xs text-muted" style={{ marginTop: 2 }}>
                  {EMPLOYEE_TYPE_LABEL[a.employee_type] ?? a.employee_type} · {a.sources.length} source
                  {a.sources.length === 1 ? "" : "s"}
                </div>
              </div>
            ))
          )}
          <Button
            size="sm" variant="secondary" style={{ width: "100%", marginTop: 8, justifyContent: "center" }}
            onClick={() => setHireOpen(true)}
          >
            Hire another
          </Button>
        </div>
      )}

      {tab === "data" && (
        <>
          <div className="chat-context-section">
            <div className="chat-context-section-title">Sources</div>
            {sourcesQuery.isLoading || scopeLoading ? (
              <Skeleton height={40} style={{ borderRadius: 6 }} />
            ) : projectSources.length === 0 ? (
              <div className="chat-empty-note">No sources granted to this project yet.</div>
            ) : (
              projectSources.map((s) => (
                <div key={s.id} className="chat-tool-log-item">
                  <div className="font-medium text-sm">{s.name}</div>
                  <Badge variant="info" style={{ marginTop: 2 }}>{s.source_type}</Badge>
                </div>
              ))
            )}
            <Link
              href={`/projects/${projectId}/workbench/sources`}
              className="text-xs" style={{ display: "block", marginTop: 8, color: "var(--accent-text)" }}
            >
              Open in Workbench →
            </Link>
          </div>

          <div className="chat-context-section">
            <div className="chat-context-section-title">Attached Context</div>
            {attachedContext ? (
              <div className="chat-context-chip" style={{ marginBottom: 0, display: "flex", width: "100%", justifyContent: "space-between" }}>
                <span>📎 {attachedContext.source_name}</span>
                <button onClick={onClear} title="Remove">✕</button>
              </div>
            ) : (
              <>
                <div className="chat-empty-note" style={{ marginBottom: 6 }}>
                  No data source attached — AXIOM will still use its tools, this just hints which source you mean.
                </div>
                <Select
                  aria-label="Attach a source"
                  value=""
                  style={{ fontSize: 11 }}
                  onChange={(e) => {
                    const src = projectSources.find((s) => s.id === e.target.value);
                    if (src) onAttach({ source_id: src.id, source_name: src.name });
                  }}
                >
                  <option value="">Attach a source…</option>
                  {projectSources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </Select>
              </>
            )}
          </div>
        </>
      )}

      <HireAgentModal
        token={token}
        open={hireOpen}
        onClose={() => setHireOpen(false)}
        initialProjectId={projectId}
        onHired={() => qc.invalidateQueries({ queryKey: ["project-agents", projectId] })}
      />
    </div>
  );
}

function TaskCard({
  task, agentsById, onClick,
}: {
  task: ActiveTaskRailItem;
  agentsById: Map<string, ChannelMemberAgent>;
  onClick: () => void;
}) {
  const badge = liveWorkBadge(task.status);
  const agent = task.agent_id ? agentsById.get(task.agent_id) : undefined;
  return (
    <div className="livework-card" onClick={onClick}>
      <div className="livework-card-row1">
        <EmployeeAvatar name={agent?.name ?? task.agent_name ?? "AXIOM"} employeeType={agent?.employee_type} size="sm" />
        <span className="livework-card-title truncate">{task.goal}</span>
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </div>
      {/* No progress track: units_total is never known for a real task
          (see liveWorkStepLine's own note) -- a bar with nothing real to
          drive it would "animate to a fake value," exactly what §3's
          Progress bar rule forbids. */}
      <div className="livework-card-step">{liveWorkStepLine(task)}</div>
    </div>
  );
}
