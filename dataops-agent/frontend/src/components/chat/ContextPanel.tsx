"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Select, Badge } from "@/components/ui";
import { ToolCallBlock } from "./ToolCallBlock";
import { taskStatusVariant, taskStatusLabel } from "@/components/tasks/taskDisplay";
import type { LocalChatMessage } from "./types";
import { getActiveTasks, type ChatContext, type DataSourceItem, type PendingApproval } from "@/lib/api";

const ACTIVE_TASKS_POLL_MS = 20000;
const ACTIVE_TASKS_IDLE_POLL_MS = 60000;

export function ContextPanel({
  messages,
  sources,
  attachedContext,
  onAttach,
  onClear,
  onGoToApprovals,
  currentUserRole,
  token,
  sessionId,
}: {
  messages: LocalChatMessage[];
  sources: DataSourceItem[];
  attachedContext: ChatContext | null;
  onAttach: (ctx: ChatContext) => void;
  onClear: () => void;
  onGoToApprovals: () => void;
  currentUserRole?: string | null;
  token: string;
  sessionId: string | null;
}) {
  const router = useRouter();
  const toolLog = messages.flatMap((m) =>
    (m.tool_calls || []).map((call) => ({ call, approval: m.approvals?.find((a: PendingApproval) => a.name === call.tool) }))
  );

  // Same ["active-tasks"] query key the Topbar rail polls -- one shared
  // network call (see queryClient.tsx's single app-wide QueryClient),
  // filtered client-side down to this session's own tasks. Part A (Topbar)
  // is the tenant-wide, permission-filtered "back from lunch" view; this
  // is the narrower "what's this conversation spawned" view, sourced from
  // the exact same poll rather than a second one.
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
      {sessionId && (
        <div className="chat-context-section">
          <div className="chat-context-section-title">Active Tasks In This Conversation</div>
          {sessionTasks.length === 0 ? (
            <div className="chat-empty-note">No active tasks from this conversation.</div>
          ) : (
            sessionTasks.map((t) => (
              <div
                key={t.id}
                className="chat-tool-log-item"
                style={{ cursor: "pointer" }}
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
                const src = sources.find((s) => s.id === e.target.value);
                if (src) onAttach({ source_id: src.id, source_name: src.name });
              }}
            >
              <option value="">Attach a source…</option>
              {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </>
        )}
      </div>

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
    </div>
  );
}
