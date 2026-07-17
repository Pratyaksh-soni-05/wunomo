"use client";

import { Button } from "@/components/ui";
import { Skeleton } from "@/components/ui";
import type { ChatSessionSummary } from "@/lib/api";
import { useSavedPrompts } from "./useSavedPrompts";

function timeAgo(iso: string): string {
  const then = new Date(iso.replace(" ", "T") + (iso.endsWith("Z") ? "" : "Z")).getTime();
  const diffMs = Date.now() - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? "Yesterday" : `${days}d ago`;
}

export function SessionList({
  tenantId,
  sessions,
  loading,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onInsertPrompt,
  draft,
}: {
  tenantId: string | null;
  sessions: ChatSessionSummary[];
  loading: boolean;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onInsertPrompt: (text: string) => void;
  draft: string;
}) {
  const { prompts, addPrompt, removePrompt } = useSavedPrompts(tenantId);

  return (
    <div className="chat-sidebar-left">
      <div className="chat-new-btn-wrap">
        <Button size="sm" style={{ width: "100%" }} onClick={onNewChat}>
          + New Chat
        </Button>
      </div>

      <div className="chat-section-label">Recent</div>
      <div className="chat-session-list">
        {loading ? (
          <div style={{ padding: "0 12px" }}>
            <Skeleton height={40} style={{ marginBottom: 6, borderRadius: 6 }} />
            <Skeleton height={40} style={{ marginBottom: 6, borderRadius: 6 }} />
            <Skeleton height={40} style={{ borderRadius: 6 }} />
          </div>
        ) : sessions.length === 0 ? (
          <div className="chat-empty-note" style={{ padding: "8px 12px" }}>No conversations yet.</div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.session_id}
              className={["chat-session-item", s.session_id === activeSessionId ? "active" : ""].join(" ")}
              onClick={() => onSelectSession(s.session_id)}
            >
              <div className="chat-session-title">{s.title || "New conversation"}</div>
              <div className="chat-session-meta">{timeAgo(s.last_activity)} · {s.message_count} msgs</div>
            </div>
          ))
        )}
      </div>

      <div className="chat-saved-prompts">
        <div className="chat-section-label" style={{ padding: "0 0 6px" }}>Saved Prompts</div>
        {prompts.length === 0 ? (
          <div className="chat-empty-note">No saved prompts yet.</div>
        ) : (
          prompts.map((p) => (
            <div key={p.id} className="chat-saved-prompt-item" onClick={() => onInsertPrompt(p.text)}>
              <span className="truncate">{p.text}</span>
              <button
                className="chat-saved-prompt-remove"
                onClick={(e) => { e.stopPropagation(); removePrompt(p.id); }}
                title="Remove"
              >
                ✕
              </button>
            </div>
          ))
        )}
        <button
          className="chat-saved-prompt-item chat-save-prompt-btn"
          disabled={!draft.trim()}
          style={{ opacity: draft.trim() ? 1 : 0.4, cursor: draft.trim() ? "pointer" : "default" }}
          onClick={() => addPrompt(draft)}
        >
          + Save current draft
        </button>
      </div>
    </div>
  );
}
