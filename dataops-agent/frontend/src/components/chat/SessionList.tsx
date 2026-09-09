"use client";

import { useState } from "react";
import { Badge, Button, Input, Modal, Skeleton } from "@/components/ui";
import type { SelectableAgent, ChannelItem, ChatSessionSummary } from "@/lib/api";
import { useSavedPrompts } from "./useSavedPrompts";
import { parseApiDate } from "@/lib/dates";

function timeAgo(iso: string): string {
  const d = parseApiDate(iso);
  const diffMs = Date.now() - (d ? d.getTime() : 0);
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
  channels,
  channelsLoading,
  availableAgents,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onCreateChannel,
  onInsertPrompt,
  onDeleteSession,
  draft,
}: {
  tenantId: string | null;
  sessions: ChatSessionSummary[];
  loading: boolean;
  channels: ChannelItem[];
  channelsLoading: boolean;
  availableAgents: SelectableAgent[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onCreateChannel: (name: string, agentIds: string[]) => void;
  onInsertPrompt: (text: string) => void;
  onDeleteSession: (id: string) => void;
  draft: string;
}) {
  const { prompts, addPrompt, removePrompt } = useSavedPrompts(tenantId);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [channelName, setChannelName] = useState("");
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);

  const resetChannelModal = () => {
    setChannelModalOpen(false);
    setChannelName("");
    setSelectedAgentIds([]);
  };

  const toggleAgent = (id: string) => {
    setSelectedAgentIds((prev) => (prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]));
  };

  return (
    <div className="chat-sidebar-left">
      <div className="chat-new-btn-wrap">
        <Button size="sm" style={{ width: "100%" }} onClick={onNewChat}>
          + New Chat
        </Button>
      </div>

      <div className="chat-section-label">AXIOM Direct</div>
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
              <div className="chat-session-row">
                <div className="chat-session-title">{s.title || "New conversation"}</div>
                <button
                  className="chat-session-delete"
                  title="Delete conversation"
                  onClick={(e) => { e.stopPropagation(); onDeleteSession(s.session_id); }}
                >
                  ✕
                </button>
              </div>
              <div className="chat-session-meta">{timeAgo(s.last_activity)} · {s.message_count} msgs</div>
            </div>
          ))
        )}
      </div>

      <div className="chat-section-label flex items-center justify-between" style={{ paddingRight: 8 }}>
        <span>Channels</span>
        <button className="chat-session-delete" title="New channel" onClick={() => setChannelModalOpen(true)}>+</button>
      </div>
      <div className="chat-session-list">
        {channelsLoading ? (
          <div style={{ padding: "0 12px" }}>
            <Skeleton height={40} style={{ borderRadius: 6 }} />
          </div>
        ) : channels.length === 0 ? (
          <div className="chat-empty-note" style={{ padding: "8px 12px" }}>
            No channels yet. Channels let multiple agents (and people) share one conversation.
          </div>
        ) : (
          channels.map((c) => (
            <div
              key={c.id}
              className={["chat-session-item", c.id === activeSessionId ? "active" : ""].join(" ")}
              onClick={() => onSelectSession(c.id)}
            >
              <div className="chat-session-row">
                <div className="chat-session-title">
                  # {c.name}
                  {c.agent_count === 0 && (
                    <Badge variant="warning" style={{ marginLeft: 6 }}>needs an agent</Badge>
                  )}
                </div>
              </div>
              <div className="chat-session-meta">
                {c.agent_count} agent{c.agent_count === 1 ? "" : "s"}
              </div>
            </div>
          ))
        )}
      </div>

      <Modal
        open={channelModalOpen}
        onClose={resetChannelModal}
        title="New Channel"
        footer={
          <>
            <Button variant="secondary" onClick={resetChannelModal}>Cancel</Button>
            <Button
              disabled={!channelName.trim() || selectedAgentIds.length === 0}
              onClick={() => {
                onCreateChannel(channelName.trim(), selectedAgentIds);
                resetChannelModal();
              }}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input
            id="channel-name" label="Name" value={channelName}
            onChange={(e) => setChannelName(e.target.value)}
            placeholder="e.g. pipeline-incidents"
            required
          />
          <div className="input-group">
            <label className="input-label">Agents (at least one required)</label>
            {availableAgents.length === 0 ? (
              <p className="text-muted text-sm">No active agents to add yet — hire one first.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {availableAgents.map((a) => (
                  <label key={a.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedAgentIds.includes(a.id)}
                      onChange={() => toggleAgent(a.id)}
                    />
                    {a.name}
                  </label>
                ))}
              </div>
            )}
            <p className="text-muted text-xs" style={{ marginTop: 4 }}>
              A channel with no agents can&apos;t be talked to — pick at least one now; more can be added later.
            </p>
          </div>
        </div>
      </Modal>

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
