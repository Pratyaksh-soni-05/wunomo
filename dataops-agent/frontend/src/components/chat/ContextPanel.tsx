"use client";

import { Select } from "@/components/ui";
import { ToolCallBlock } from "./ToolCallBlock";
import type { LocalChatMessage } from "./types";
import type { ChatContext, DataSourceItem, PendingApproval } from "@/lib/api";

export function ContextPanel({
  messages,
  sources,
  attachedContext,
  onAttach,
  onClear,
  onGoToApprovals,
  currentUserRole,
}: {
  messages: LocalChatMessage[];
  sources: DataSourceItem[];
  attachedContext: ChatContext | null;
  onAttach: (ctx: ChatContext) => void;
  onClear: () => void;
  onGoToApprovals: () => void;
  currentUserRole?: string | null;
}) {
  const toolLog = messages.flatMap((m) =>
    (m.tool_calls || []).map((call) => ({ call, approval: m.approvals?.find((a: PendingApproval) => a.name === call.tool) }))
  );

  return (
    <div className="chat-sidebar-right">
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
