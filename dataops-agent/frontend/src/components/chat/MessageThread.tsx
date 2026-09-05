"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, Button, Modal, Select } from "@/components/ui";
import { ToolCallBlock } from "./ToolCallBlock";
import type { LocalChatMessage } from "./types";
import type {
  AgentListItem, ChannelItem, ChannelMemberAgent, ChannelMemberUser, ChatContext, TeamMember,
} from "@/lib/api";

const QUICK_PROMPTS = [
  "List my data sources",
  "Show failed pipeline runs",
  "Run quality checks on a pipeline",
  "List open incidents",
  "Generate a status report",
];

const PERSONALITY_OPTIONS = ["engineer", "founder", "analyst", "auditor"] as const;
const OPERATION_OPTIONS = ["advisory", "assisted", "autonomous", "audit"] as const;

function formatAssistantText(text: string) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function ThinkingIndicator() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="chat-thinking">
      <span className="status-dot info pulse" />
      {elapsed < 5 ? "AXIOM is thinking…" : `AXIOM is still thinking… (${elapsed}s)`}
    </div>
  );
}

export function MessageThread({
  messages,
  sending,
  sendError,
  provider,
  personalityMode,
  operationMode,
  onPersonalityChange,
  onOperationChange,
  attachedContext,
  onClearContext,
  draft,
  onDraftChange,
  onSend,
  onGoToApprovals,
  onStartTask,
  channel,
  channelAgents,
  channelUsers,
  availableAgents,
  availablePeople,
  currentUserId,
  onAddAgent,
  onRemoveAgent,
  onAddPerson,
  onRemovePerson,
}: {
  messages: LocalChatMessage[];
  sending: boolean;
  sendError: string | null;
  provider: string | null;
  personalityMode: string;
  operationMode: string;
  onPersonalityChange: (v: string) => void;
  onOperationChange: (v: string) => void;
  attachedContext: ChatContext | null;
  onClearContext: () => void;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  onGoToApprovals: () => void;
  onStartTask: () => void;
  channel?: ChannelItem | null;
  channelAgents?: ChannelMemberAgent[];
  channelUsers?: ChannelMemberUser[];
  availableAgents?: AgentListItem[];
  availablePeople?: TeamMember[];
  currentUserId?: string | null;
  onAddAgent?: (agentId: string) => void;
  onRemoveAgent?: (agentId: string, agentName: string) => void;
  onAddPerson?: (userId: string) => void;
  onRemovePerson?: (userId: string) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const [membersModalOpen, setMembersModalOpen] = useState(false);

  const channelAgentIds = new Set((channelAgents ?? []).map((a) => a.id));
  const addableAgents = (availableAgents ?? []).filter((a) => !channelAgentIds.has(a.id));
  const channelUserIds = new Set((channelUsers ?? []).map((u) => u.id));
  const addablePeople = (availablePeople ?? []).filter((p) => p.is_active && !channelUserIds.has(p.id));

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "40px";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [draft]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (draft.trim() && !sending) onSend();
    }
  };

  return (
    <div className="chat-main">
      <div className="chat-header">
        <div className="chat-header-identity">
          <div className="chat-avatar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
            </svg>
          </div>
          <div>
            <div className="font-semibold" style={{ fontSize: 13 }}>
              {channel ? `# ${channel.name}` : "AXIOM DataOps Agent"}
            </div>
            <div className="flex items-center gap-2" style={{ gap: 6 }}>
              <span className={["status-dot", sending ? "warning pulse" : "success"].join(" ")} />
              <span className="text-xs text-muted">
                {channel
                  ? `${channelAgents?.length ?? 0} agent${(channelAgents?.length ?? 0) === 1 ? "" : "s"}`
                  : sending ? "Working…" : provider ? `Ready · last reply via ${provider}` : "Ready"}
              </span>
            </div>
          </div>
        </div>
        <div className="chat-header-controls">
          {channel && (
            <Button size="sm" variant="secondary" onClick={() => setMembersModalOpen(true)}>Members</Button>
          )}
          <Button size="sm" variant="secondary" onClick={onStartTask}>+ Start a Task</Button>
          <Select
            aria-label="Personality mode"
            value={personalityMode}
            onChange={(e) => onPersonalityChange(e.target.value)}
            style={{ width: "auto", fontSize: 11, padding: "4px 24px 4px 8px" }}
          >
            {PERSONALITY_OPTIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
          </Select>
          <Select
            aria-label="Operation mode"
            value={operationMode}
            onChange={(e) => onOperationChange(e.target.value)}
            style={{ width: "auto", fontSize: 11, padding: "4px 24px 4px 8px" }}
          >
            {OPERATION_OPTIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
          </Select>
        </div>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && !sending && (
          <div className="empty-state" style={{ minHeight: "auto", padding: "40px 20px" }}>
            <h2 className="font-display text-xl">
              {channel ? `Start the conversation in #${channel.name}` : "Ask AXIOM anything"}
            </h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              {channel
                ? (channelAgents?.length ?? 0) === 0
                  ? "No agents are in this channel yet — use \"Members\" above to add one before sending a message."
                  : (channelAgents?.length ?? 0) > 1
                    ? "Multiple agents are in this channel — @mention who you're talking to."
                    : `Message ${channelAgents?.[0]?.name} directly, no @mention needed.`
                : "Query your data, check pipeline health, run quality checks, or investigate an incident — " +
                  "AXIOM has real tool access to your tenant's data."}
            </p>
          </div>
        )}

        {messages.map((m, i) =>
          m.taskCard ? (
            <div className="chat-bubble-assistant" key={i}>
              <div className="chat-avatar" style={{ marginTop: 2 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="4" width="18" height="18" rx="2" />
                  <line x1="16" y1="2" x2="16" y2="6" />
                  <line x1="8" y1="2" x2="8" y2="6" />
                  <line x1="3" y1="10" x2="21" y2="10" />
                </svg>
              </div>
              <div className="chat-bubble-assistant-inner">
                <Card className="chat-bubble-assistant-text flex items-center justify-between" style={{ gap: 12 }}>
                  <span>Started task: <strong>{m.taskCard.goal}</strong></span>
                  <Button size="sm" onClick={() => router.push(`/tasks/${m.taskCard!.id}`)}>View progress</Button>
                </Card>
              </div>
            </div>
          ) : m.role === "user" ? (
            <div className="chat-bubble-user" key={i}>
              <div className="chat-bubble-user-inner">{m.content}</div>
            </div>
          ) : m.isSystemNotice ? (
            // A channel routing failure (unknown @mention, not a channel
            // member, ambiguous/no mention) -- rendered distinctly from a
            // real agent reply so it never reads as if an agent said it.
            <div className="chat-bubble-assistant" key={i}>
              <div className="chat-bubble-assistant-inner">
                <Card className="chat-bubble-assistant-text text-muted text-sm" style={{ fontStyle: "italic" }}>
                  {m.content}
                </Card>
              </div>
            </div>
          ) : (
            <div className="chat-bubble-assistant" key={i}>
              <div className="chat-avatar" style={{ marginTop: 2 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
                </svg>
              </div>
              <div className="chat-bubble-assistant-inner">
                <Card className="chat-bubble-assistant-text">
                  <span dangerouslySetInnerHTML={{ __html: formatAssistantText(m.content) }} />
                </Card>
                {m.tool_calls.map((call, ci) => (
                  <ToolCallBlock
                    key={ci}
                    call={call}
                    approval={m.approvals?.find((a) => a.name === call.tool)}
                    onGoToApprovals={onGoToApprovals}
                  />
                ))}
              </div>
            </div>
          )
        )}

        {sending && <ThinkingIndicator />}
        <div ref={bottomRef} />
      </div>

      <div className="chat-composer">
        {attachedContext && (
          <div className="chat-context-chip">
            <span>📎 {attachedContext.source_name}</span>
            <button onClick={onClearContext} title="Remove context">✕</button>
          </div>
        )}
        {sendError && (
          <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 6 }}>{sendError}</div>
        )}
        <div className="chat-composer-box">
          <textarea
            ref={textareaRef}
            placeholder={
              channel
                ? (channelAgents?.length ?? 0) > 1
                  ? "@mention who you're talking to... (↵ to send, Shift+↵ for newline)"
                  : `Message #${channel.name}... (↵ to send, Shift+↵ for newline)`
                : "Ask AXIOM anything about your data... (↵ to send, Shift+↵ for newline)"
            }
            rows={1}
            value={draft}
            disabled={sending}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <div className="chat-composer-actions">
            <span className="text-xs text-muted">Enter to send</span>
            <button
              className="btn btn-primary btn-anchored btn-sm"
              disabled={!draft.trim() || sending}
              onClick={onSend}
            >
              Send
            </button>
          </div>
        </div>
        <div className="chat-quick-prompts">
          {QUICK_PROMPTS.map((p) => (
            <button key={p} className="btn btn-secondary btn-sm" style={{ fontSize: 11 }} onClick={() => onDraftChange(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {channel && (
        <Modal
          open={membersModalOpen}
          onClose={() => setMembersModalOpen(false)}
          title={`#${channel.name} members`}
        >
          <div className="flex flex-col gap-4">
            <div>
              <div className="font-medium text-sm" style={{ marginBottom: 6 }}>Agents</div>
              {(channelAgents ?? []).length === 0 ? (
                <p className="text-muted text-sm">No agents yet.</p>
              ) : (
                <div className="flex flex-col gap-1">
                  {(channelAgents ?? []).map((a) => (
                    <div key={a.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                      <span>{a.name}</span>
                      <Button size="sm" variant="secondary" onClick={() => onRemoveAgent?.(a.id, a.name)}>Remove</Button>
                    </div>
                  ))}
                </div>
              )}
              {addableAgents.length > 0 && (
                <div className="flex flex-col gap-1" style={{ marginTop: 8 }}>
                  {addableAgents.map((a) => (
                    <div key={a.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                      <span className="text-muted">{a.name}</span>
                      <Button size="sm" onClick={() => onAddAgent?.(a.id)}>Add</Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="font-medium text-sm" style={{ marginBottom: 6 }}>People</div>
              {(channelUsers ?? []).length === 0 ? (
                <p className="text-muted text-sm">No one else here yet.</p>
              ) : (
                <div className="flex flex-col gap-1">
                  {(channelUsers ?? []).map((u) => (
                    <div key={u.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                      <span>{u.email}{u.id === currentUserId ? " (you)" : ""}</span>
                      <Button size="sm" variant="secondary" onClick={() => onRemovePerson?.(u.id)}>
                        {u.id === currentUserId ? "Leave" : "Remove"}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {addablePeople.length > 0 && (
                <div className="flex flex-col gap-1" style={{ marginTop: 8 }}>
                  {addablePeople.map((p) => (
                    <div key={p.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                      <span className="text-muted">{p.email}</span>
                      <Button size="sm" onClick={() => onAddPerson?.(p.id)}>Add</Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
