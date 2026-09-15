"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Select, Badge, Tabs, Skeleton } from "@/components/ui";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import { ToolCallBlock } from "./ToolCallBlock";
import { taskStatusVariant, taskStatusLabel } from "@/components/tasks/taskDisplay";
import { useProjectScope } from "@/lib/projectScope";
import type { LocalChatMessage } from "./types";
import { getActiveTasks, getSources, type ChatContext, type PendingApproval } from "@/lib/api";

const ACTIVE_TASKS_POLL_MS = 20000;
const ACTIVE_TASKS_IDLE_POLL_MS = 60000;

const EMPLOYEE_TYPE_LABEL: Record<string, string> = { dataops: "DataOps Engineer" };

/**
 * Project Chat tab's right panel (slice 7, 2026-09-15) — three tabs
 * (Agents / Data / Activity), matching wunomo-redesign-v2.html's own side
 * panel exactly by tab count, mapped deliberately rather than 1:1 by name:
 * Agents is new (a roster, nothing in the old stacked ContextPanel showed
 * this); Data holds the project's sources (new) plus the pre-existing
 * Attached Context picker; Activity holds Active Tasks and Tool Calls as
 * two labeled subsections, not an interleaved merge -- they're different
 * granularities (a Task is durable and outlives the conversation, a tool
 * call is this-session-only) and merging them into one feed would lose
 * that distinction for no real gain (explicit decision, 2026-09-15).
 *
 * Deliberately a separate component from ContextPanel, not that component
 * made configurable -- /chat's own AXIOM Direct sessions and non-project
 * channels have no project to show an Agents/Data roster for, so
 * ContextPanel there is untouched. Matches this whole rebuild's own
 * precedent of a filtered/adapted copy per surface rather than one
 * component branching on every caller's shape.
 *
 * The preview's Agents pane shows a status dot (idle/active) per agent --
 * not carried over. AgentInstance.status (backend/models/all_models.py)
 * is only ACTIVE/OFFBOARDED, a lifecycle flag, not a live "is this agent
 * doing something right now" signal; nothing in this codebase tracks
 * that. Faking a permanently-idle dot would be worse than no dot at all,
 * same "Created {date} instead of a fabricated last-activity" rule Home's
 * own cards already follow (findings item 92). Shows what's real instead:
 * employee type and a real, live source count.
 */
export function ProjectContextPanel({
  token,
  projectId,
  messages,
  attachedContext,
  onAttach,
  onClear,
  onGoToApprovals,
  currentUserRole,
  sessionId,
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
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [tab, setTab] = useState("agents");
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

  return (
    <div className="chat-sidebar-right">
      <Tabs
        items={[
          { id: "agents", label: "Agents" },
          { id: "data", label: "Data" },
          { id: "activity", label: "Activity" },
        ]}
        activeId={tab}
        onChange={setTab}
      />

      {tab === "agents" && (
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

      {tab === "activity" && (
        <>
          {sessionId && (
            <div className="chat-context-section">
              <div className="chat-context-section-title">Active Tasks In This Conversation</div>
              {sessionTasks.length === 0 ? (
                <div className="chat-empty-note">No active tasks from this conversation.</div>
              ) : (
                sessionTasks.map((t) => (
                  <div
                    key={t.id} className="chat-tool-log-item" style={{ cursor: "pointer" }}
                    onClick={() => router.push(`/tasks/${t.id}`)}
                  >
                    <div className="font-medium text-sm truncate">{t.goal}</div>
                    <div className="text-xs text-muted" style={{ marginTop: 2 }}>
                      <Badge variant={taskStatusVariant(t.status)}>{taskStatusLabel(t.status)}</Badge>
                      {t.current_step && ` · Step ${t.current_step.step_index + 1}: ${t.current_step.description}`}
                    </div>
                    {t.action_text && (
                      <div className="text-xs" style={{ marginTop: 4, color: "var(--warning)", fontWeight: 600 }}>
                        {t.action_text}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          <div className="chat-context-section">
            <div className="chat-context-section-title">Tool Calls This Session</div>
            {toolLog.length === 0 ? (
              <div className="chat-empty-note">No tools called yet.</div>
            ) : (
              toolLog.map((entry, i) => (
                <div className="chat-tool-log-item" key={i}>
                  <ToolCallBlock call={entry.call} approval={entry.approval} onGoToApprovals={onGoToApprovals} currentUserRole={currentUserRole} />
                </div>
              ))
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
