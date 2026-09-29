"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Badge, Modal, Select } from "@/components/ui";
import { EmployeeAvatar } from "./EmployeeAvatar";
import { UserMessage, EmployeeMessage, EmployeeResult, ApprovalCard, HandoffCard, SystemLine, TaskStartedLine } from "./messageShapes";
import { KNOWN_EMPLOYEE_TYPES, EMPLOYEE_TYPE_LABEL } from "@/lib/employeeTypes";
import type { LocalChatMessage } from "./types";
import type {
  SelectableAgent, ChannelItem, ChannelMemberAgent, ChannelMemberUser, ChatContext, TeamMember,
} from "@/lib/api";

// One row the mention picker can navigate to with the keyboard. No
// "everyone" broadcast row here (removed -- see the mention-picker JSX
// below for why): there is no broadcast target to resolve one against.
type MentionNavigableRow =
  | { kind: "agent"; agent: ChannelMemberAgent }
  | { kind: "hire"; employeeType: string; label: string };

// Finds the @mention the cursor is currently inside of, anywhere in the
// text -- not just a mention at the very start of the message (the old
// implementation's `/^@(\S*)$/` only matched when the ENTIRE draft was a
// bare "@word", so a second mention later in a multi-agent message, e.g.
// "@Nova do X, then @Ra|", never opened the picker at all). Scans backward
// from the cursor through non-whitespace; an "@" only counts as a trigger
// if it starts a word (string start or preceded by whitespace) -- an "@"
// mid-word (an email address) is correctly ignored.
function findActiveMention(text: string, cursor: number): { start: number; query: string } | null {
  let i = cursor - 1;
  while (i >= 0) {
    const ch = text[i];
    if (/\s/.test(ch)) return null;
    if (ch === "@") {
      if (i === 0 || /\s/.test(text[i - 1])) return { start: i, query: text.slice(i + 1, cursor) };
      return null;
    }
    i--;
  }
  return null;
}

const QUICK_PROMPTS = [
  "List my data sources",
  "Show failed pipeline runs",
  "Run quality checks on a pipeline",
  "List open incidents",
  "Generate a status report",
];

const PERSONALITY_OPTIONS = ["engineer", "founder", "analyst", "auditor"] as const;
const OPERATION_OPTIONS = ["advisory", "assisted", "autonomous", "audit"] as const;

// The pre-agents/1:1 default identity -- always a dataops employee named
// AXIOM, it simply never had a tile before this pass (§7.4).
const AXIOM_IDENTITY = { name: "AXIOM", employeeType: "dataops" as string | null };

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
  currentUserRole,
  uploading,
  uploadError,
  onUploadFile,
  liveNotice,
  liveWorkToggle,
  onTagUnhiredType,
  onApproveTask,
  onRejectTask,
  busyApprovalId,
  busyApprovalAction,
}: {
  messages: LocalChatMessage[];
  sending: boolean;
  sendError: string | null;
  provider: string | null;
  // POST /chat/stream only (Stage 1) -- an `approval_required` SSE event
  // arrived for the in-flight turn. Reuses the same .chat-approval-notice
  // styling ToolCallBlock already uses for a blocked call, since the SSE
  // event carries only an approval id, not enough detail (risk_level,
  // reason, which tool) to attach to one specific ToolCallBlock the way a
  // fully-resolved history message can. Wired up by
  // projects/[id]/chat/page.tsx; app/(app)/chat/page.tsx doesn't pass it
  // (an approval still reaches its message once persisted, just without
  // this live pre-completion banner) -- always optional, never assumed
  // present by this component.
  liveNotice?: string | null;
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
  availableAgents?: SelectableAgent[];
  availablePeople?: TeamMember[];
  currentUserId?: string | null;
  onAddAgent?: (agentId: string) => void;
  onRemoveAgent?: (agentId: string, agentName: string) => void;
  onAddPerson?: (userId: string) => void;
  onRemovePerson?: (userId: string) => void;
  currentUserRole?: string | null;
  // Channels only in v1 (finding 80 -- bare 1:1 chat isn't covered yet).
  // Owned by the parent, same as sending/sendError, so an upload failure
  // (409 ambiguous target, 422 unsupported type, 400 bad extension, 403
  // permission) renders inline in the composer exactly like a send failure
  // does -- never a toast.
  uploading?: boolean;
  uploadError?: string | null;
  onUploadFile?: (file: File) => void;
  // §7.1 Responsive: the live work panel's own header toggle, visible only
  // below 1180px (.livework-toggle's own CSS) -- undefined on a host with
  // no live work panel at all (e.g. the direct AXIOM chat page).
  liveWorkToggle?: { count: number; open: boolean; onToggle: () => void };
  // §7.5 mention picker's "Not hired yet — tag to hire" row. MessageThread
  // stays prop-driven (no `token`, renders no HireAgentModal itself,
  // consistent with everything else here) -- the parent owns hiring +
  // adding the new agent to the channel + the resulting system line.
  onTagUnhiredType?: (employeeType: string) => void;
  // §7.3.E's inline action row -- approveRequest()/rejectRequest() (the
  // already-shipped Approvals-screen actions) called with the message's
  // own approvalCard.approval_request_id. Both resolve only once
  // resolve_task_approval()'s wave-drain is fully done server-side, so the
  // parent's job on success is just a history refetch, not a second
  // stream. Undefined on a host with no approval card ever rendered.
  onApproveTask?: (approvalRequestId: string) => void;
  onRejectTask?: (approvalRequestId: string) => void;
  // Which one card (if any) is mid-request right now, and which action --
  // a single pair, not a set, because only one inline approve/reject click
  // can be in flight at a time from this one composer.
  busyApprovalId?: string | null;
  busyApprovalAction?: "approving" | "rejecting" | null;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [membersModalOpen, setMembersModalOpen] = useState(false);
  const [mentionHighlight, setMentionHighlight] = useState(0);
  const [mentionDismissed, setMentionDismissed] = useState(false);
  const [cursorPos, setCursorPos] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [dropRefusedReason, setDropRefusedReason] = useState<string | null>(null);
  const pendingCursorRef = useRef<number | null>(null);

  const canUpload = !!channel && !!onUploadFile;

  const handleFile = (file: File) => {
    setDropRefusedReason(null);
    if (!canUpload) {
      setDropRefusedReason(
        channel
          ? "File uploads aren't available here."
          : "File uploads are only supported inside a channel right now — open or create one first."
      );
      return;
    }
    onUploadFile!(file);
  };

  const channelAgentIds = new Set((channelAgents ?? []).map((a) => a.id));
  const addableAgents = (availableAgents ?? []).filter((a) => !channelAgentIds.has(a.id));
  const channelUserIds = new Set((channelUsers ?? []).map((u) => u.id));
  const addablePeople = (availablePeople ?? []).filter((p) => p.is_active && !channelUserIds.has(p.id));

  // Mention picker (§7.5). resolve_mentioned_agent() requires an exact,
  // complete name match -- there's no partial/prefix matching server-side
  // -- so selecting a row always inserts the agent's FULL name, never
  // leaves a partial one for the parser to guess at. Agent rows are
  // scoped to this channel's own current members, never every tenant
  // agent -- mentioning one that isn't a member yet is exactly the dead
  // end an earlier pass already built a real error message for; the
  // picker shouldn't offer a name that's guaranteed to fail.
  const activeMention = channel ? findActiveMention(draft, cursorPos) : null;
  const mentionQuery = activeMention?.query ?? null;
  const queryLower = mentionQuery?.toLowerCase() ?? "";

  const agentRows = mentionQuery !== null
    ? (channelAgents ?? []).filter((a) => a.name.toLowerCase().startsWith(queryLower))
    : [];
  // "Not hired yet" (§7.5): a real employee TYPE with zero instances in
  // this channel yet -- AgentEmployeeType has exactly one real member
  // ("dataops") today, so this group shows at most one row, and none at
  // all once a dataops agent is already a member.
  const hiredTypes = new Set((channelAgents ?? []).map((a) => a.employee_type));
  const hireTypeRows = mentionQuery !== null
    ? KNOWN_EMPLOYEE_TYPES
        .filter((t) => !hiredTypes.has(t))
        .map((t) => ({ employeeType: t, label: EMPLOYEE_TYPE_LABEL[t] ?? t }))
        .filter((r) => r.label.toLowerCase().startsWith(queryLower))
    : [];
  // No "everyone" broadcast row: removed (a visible dead control teaches
  // users a feature exists that doesn't). Restoring it needs a real
  // broadcast target to resolve against first -- services/channel_
  // routing.py's resolve_channel_message_target() only ever returns a
  // single named agent or a channel's sole member today, nothing that
  // means "every member."

  const navigableRows: MentionNavigableRow[] = [
    ...agentRows.map((agent) => ({ kind: "agent" as const, agent })),
    ...hireTypeRows.map((r) => ({ kind: "hire" as const, ...r })),
  ];
  const showMentionPicker = activeMention !== null && !mentionDismissed && navigableRows.length > 0;

  const selectMentionRow = (row: MentionNavigableRow) => {
    if (row.kind === "hire") {
      onTagUnhiredType?.(row.employeeType);
      setMentionDismissed(true);
      return;
    }
    if (!activeMention) return;
    const before = draft.slice(0, activeMention.start);
    const after = draft.slice(cursorPos);
    const inserted = `@${row.agent.name} `;
    onDraftChange(before + inserted + after);
    pendingCursorRef.current = before.length + inserted.length;
  };

  // Inserted by the toolbar's "@ Tag" button (§7.5) -- at the cursor, with
  // a leading space only if not already preceded by whitespace/the start
  // of the message, so it never fuses onto an existing word. (A "/
  // Command" button used to call this too -- removed, see the toolbar
  // JSX below for why.)
  const insertAtCursor = (char: string) => {
    const before = draft.slice(0, cursorPos);
    const after = draft.slice(cursorPos);
    const insertion = (before.length > 0 && !/\s$/.test(before) ? " " : "") + char;
    onDraftChange(before + insertion + after);
    pendingCursorRef.current = before.length + insertion.length;
  };

  const updateCursor = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    setCursorPos(e.currentTarget.selectionStart ?? 0);
  };

  // Applies a cursor position set by selectMentionRow/insertAtCursor once
  // the just-inserted text has actually landed in the DOM -- setting
  // selectionRange before the value updates would place it against the
  // OLD text.
  useEffect(() => {
    if (pendingCursorRef.current !== null && textareaRef.current) {
      const pos = pendingCursorRef.current;
      textareaRef.current.setSelectionRange(pos, pos);
      textareaRef.current.focus();
      pendingCursorRef.current = null;
      setCursorPos(pos);
    }
  }, [draft]);

  useEffect(() => {
    setMentionHighlight(0);
  }, [mentionQuery]);

  // Dismissal belongs to ONE mention context (identified by where it
  // starts in the text), not to the whole session -- starting a new
  // mention (a different `start` position, including a second one later
  // in the same multi-agent message) must show the picker again even if
  // an earlier one was dismissed.
  useEffect(() => {
    setMentionDismissed(false);
  }, [activeMention?.start]);

  // Per-message identity resolution (§7.4/§7.3.B-C) -- agent_id is only
  // ever meaningful inside a channel (a 1:1 non-channel message has none,
  // by the model's own design); a channel member removed since the
  // message was sent, or a null agent_id, falls back to AXIOM rather than
  // guessing which of the channel's remaining agents it "probably" was.
  const agentsById = new Map((channelAgents ?? []).map((a) => [a.id, a]));
  const resolveIdentity = (agentId: string | null | undefined) => {
    if (!channel || !agentId) return AXIOM_IDENTITY;
    const agent = agentsById.get(agentId);
    return agent ? { name: agent.name, employeeType: agent.employee_type } : AXIOM_IDENTITY;
  };
  const headerIdentity = channel && (channelAgents ?? []).length === 1
    ? { name: channelAgents![0].name, employeeType: channelAgents![0].employee_type }
    : AXIOM_IDENTITY;

  // Shape C (streaming) applies to exactly one message: the trailing
  // assistant placeholder send() mutates in place while `sending` is
  // true. The buffered (non-streaming) chat page never has a trailing
  // placeholder during `sending` at all (it appends the real message only
  // once the request resolves) -- this is naturally false there.
  const lastMessage = messages[messages.length - 1];
  const isStreamingPlaceholder = sending && !!lastMessage
    && lastMessage.role === "assistant" && !lastMessage.taskCard && !lastMessage.isSystemNotice;

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
    if (showMentionPicker && navigableRows.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionHighlight((i) => (i + 1) % navigableRows.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionHighlight((i) => (i - 1 + navigableRows.length) % navigableRows.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectMentionRow(navigableRows[mentionHighlight]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionDismissed(true);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (draft.trim() && !sending) onSend();
    }
  };

  return (
    <div className="chat-main">
      <div className="chat-header">
        <div className="chat-header-identity">
          <EmployeeAvatar name={headerIdentity.name} employeeType={headerIdentity.employeeType} />
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
          {liveWorkToggle && (
            <button
              type="button"
              className="btn btn-secondary btn-dense livework-toggle"
              onClick={liveWorkToggle.onToggle}
              aria-expanded={liveWorkToggle.open}
            >
              Live work
              {liveWorkToggle.count > 0 && <Badge variant="info">{liveWorkToggle.count}</Badge>}
            </button>
          )}
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

        {messages.map((m, i) => {
          if (m.taskCard) {
            // Not one of the nine spec shapes -- keeps its own pre-
            // existing rendering (a button doesn't fit shape I's
            // centred/ruled treatment) rather than being forced into A/B/C/I.
            return <TaskStartedLine key={i} goal={m.taskCard.goal} onView={() => router.push(`/tasks/${m.taskCard!.id}`)} />;
          }
          if (m.role === "user") {
            return <UserMessage key={i} content={m.content} timestamp={m.timestamp} roster={channelAgents} />;
          }
          // Shape F -- checked before the generic system_notice branch
          // below: a persisted handoff row is ALSO role="system_notice"
          // (api/v1/chat.py's _handoff_entries), so `from_agent_id`
          // presence is what actually distinguishes "real Handoff row" from
          // "plain inferred-edge sentence" -- never role alone.
          if (m.from_agent_id) {
            return (
              <HandoffCard
                key={i}
                fromAgentId={m.from_agent_id}
                fromAgentName={m.from_agent_name ?? m.from_agent_id}
                toAgentId={m.to_agent_id}
                toAgentName={m.to_agent_name ?? m.to_agent_id ?? "?"}
                payloadSummary={m.payload_summary ?? ""}
                withheld={m.withheld ?? []}
                timestamp={m.timestamp}
                roster={channelAgents}
              />
            );
          }
          if (m.isSystemNotice || m.role === "system_notice") {
            // A channel routing failure (client-side-only isSystemNotice,
            // never persisted), or a persisted system_notice row (an
            // inferred-edge explanation) -- shape I either way, so neither
            // ever reads as if an agent said it.
            return <SystemLine key={i} text={m.content} />;
          }
          const identity = resolveIdentity(m.agent_id);
          // Shape E -- a task bubble the moment its own "paused_needs_
          // approval" event arrives (page.tsx's onSupervisorTask sets
          // approvalCard directly on that message). Checked before D/B/C:
          // a paused task is neither streaming nor a finished result.
          if (m.approvalCard) {
            const card = m.approvalCard;
            return (
              <ApprovalCard
                key={i}
                riskLevel={card.risk_level}
                reason={card.reason}
                unblocks={card.unblocks}
                onApprove={() => onApproveTask?.(card.approval_request_id)}
                onReject={() => onRejectTask?.(card.approval_request_id)}
                busy={busyApprovalId === card.approval_request_id ? busyApprovalAction : null}
              />
            );
          }
          // Shape D once a message is done streaming and didn't fail --
          // every history-loaded assistant row qualifies too (a persisted
          // ChatMessage only ever exists for a real completion in the
          // first place, so `streaming`/`taskFailed` are simply absent
          // there, not falsely true). Still streaming, or a genuine
          // failure, falls through to the plain B/C bubble below instead
          // -- D's unconditional "done" badge would misstate either case.
          if (!m.streaming && !m.taskFailed) {
            return (
              <EmployeeResult
                key={i}
                name={identity.name}
                employeeType={identity.employeeType}
                timestamp={m.timestamp}
                content={m.content}
                toolCalls={m.tool_calls}
                approvals={m.approvals}
                onGoToApprovals={onGoToApprovals}
                currentUserRole={currentUserRole}
              />
            );
          }
          return (
            <EmployeeMessage
              key={i}
              name={identity.name}
              employeeType={identity.employeeType}
              timestamp={m.timestamp}
              content={m.content}
              toolCalls={m.tool_calls}
              // Per-message, not "whichever bubble is last in the array"
              // -- with two+ concurrent supervisor tasks there is no
              // single "current" streaming message, and the array-
              // position check permanently stopped showing an earlier
              // bubble as streaming the moment a later one was appended
              // after it, even while its own tokens kept arriving.
              streaming={sending && !!m.streaming}
              approvals={m.approvals}
              onGoToApprovals={onGoToApprovals}
              currentUserRole={currentUserRole}
            />
          );
        })}

        {/* Shape C's caret is the trailing placeholder's own "thinking"
            indicator once it exists -- showing this too would be a second,
            redundant busy signal for the same wait (D6: one indicator,
            never a spinner). The buffered (non-streaming) chat page never
            has a trailing placeholder during `sending`, so this is its
            only indicator, unchanged. */}
        {sending && !isStreamingPlaceholder && <ThinkingIndicator />}
        {liveNotice && (
          <div className="chat-approval-notice">
            <span>⚠</span>
            <span>
              {liveNotice}{" "}
              <Button variant="text" onClick={onGoToApprovals}>Approvals screen</Button>.
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-composer">
        {sendError && (
          <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 6 }}>{sendError}</div>
        )}
        {uploadError && (
          <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 6 }}>{uploadError}</div>
        )}
        {dropRefusedReason && (
          <div className="text-xs text-muted" style={{ marginBottom: 6 }}>{dropRefusedReason}</div>
        )}
        {uploading && (
          <div className="text-xs text-muted" style={{ marginBottom: 6 }}>Uploading…</div>
        )}

        {/* §7.5 -- Card, three rows: attachments (hidden when empty), input,
            toolbar. */}
        <div
          className={["composer-card", dragOver ? "drag-over" : ""].join(" ")}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files?.[0];
            if (file) handleFile(file);
          }}
        >
          {attachedContext && (
            <div className="composer-row composer-row-attachments">
              <div className="chat-context-chip" style={{ marginBottom: 0 }}>
                <span>📎 {attachedContext.source_name}</span>
                <button onClick={onClearContext} title="Remove attachment">✕</button>
              </div>
            </div>
          )}

          <div className="composer-row composer-row-input">
            {showMentionPicker && (
              <div className="mention-picker" role="listbox" aria-label="Mention someone">
                {agentRows.length > 0 && (
                  <div className="mention-picker-group">
                    <div className="mention-picker-group-label">On this project</div>
                    {agentRows.map((agent) => {
                      const idx = navigableRows.findIndex((r) => r.kind === "agent" && r.agent.id === agent.id);
                      return (
                        <div
                          key={agent.id}
                          role="option"
                          aria-selected={idx === mentionHighlight}
                          className={["mention-row", idx === mentionHighlight ? "active" : ""].filter(Boolean).join(" ")}
                          onMouseEnter={() => setMentionHighlight(idx)}
                          onClick={() => selectMentionRow({ kind: "agent", agent })}
                        >
                          <EmployeeAvatar name={agent.name} employeeType={agent.employee_type} size="sm" />
                          <div className="mention-row-text">
                            <div className="mention-row-name">{agent.name}</div>
                            <div className="mention-row-meta">
                              {EMPLOYEE_TYPE_LABEL[agent.employee_type] ?? agent.employee_type} · {agent.operation_mode}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {hireTypeRows.length > 0 && (
                  <div className="mention-picker-group">
                    <div className="mention-picker-group-label">Not hired yet — tag to hire</div>
                    {hireTypeRows.map((r) => {
                      const idx = navigableRows.findIndex((row) => row.kind === "hire" && row.employeeType === r.employeeType);
                      return (
                        <div
                          key={r.employeeType}
                          role="option"
                          aria-selected={idx === mentionHighlight}
                          className={["mention-row", idx === mentionHighlight ? "active" : ""].filter(Boolean).join(" ")}
                          onMouseEnter={() => setMentionHighlight(idx)}
                          onClick={() => selectMentionRow({ kind: "hire", employeeType: r.employeeType, label: r.label })}
                        >
                          <span className="mention-row-name">{r.label}</span>
                          <Badge variant="info">+ hire</Badge>
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* No "everyone" broadcast row here -- removed, a visible
                    dead control teaches users a feature exists that
                    doesn't. Restoring it needs a real broadcast target
                    first: services/channel_routing.py's
                    resolve_channel_message_target() only ever resolves a
                    single named agent or a channel's sole member today,
                    nothing that means "every member." */}
              </div>
            )}
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
              onChange={(e) => { onDraftChange(e.target.value); setCursorPos(e.target.selectionStart ?? 0); }}
              onSelect={updateCursor}
              onClick={updateCursor}
              onKeyUp={updateCursor}
              onKeyDown={handleKeyDown}
            />
          </div>

          <div className="composer-row composer-row-toolbar">
            <div className="composer-toolbar-left">
              <input
                ref={fileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFile(file);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                className="btn btn-secondary btn-icon btn-dense"
                title={canUpload ? "Attach a file" : "File uploads are only supported inside a channel"}
                disabled={uploading || sending}
                onClick={() => fileInputRef.current?.click()}
              >
                📎
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-dense"
                disabled={sending}
                onClick={() => insertAtCursor("@")}
              >
                @ Tag
              </button>
              {/* No "/ Command" button here -- removed, a visible dead
                  control teaches users a feature exists that doesn't.
                  Restoring it needs a real slash-command parser
                  somewhere first; nothing in this codebase interprets a
                  leading "/" in a chat message today. */}
            </div>
            <div className="composer-toolbar-right">
              <span className="composer-hint">
                {channel ? "Everyone tagged runs in parallel" : "Enter to send"}
              </span>
              <button
                type="button"
                className="btn btn-primary btn-icon btn-dense"
                aria-label="Send message"
                disabled={!draft.trim() || sending}
                onClick={onSend}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        {canUpload && (
          <div className="composer-drop-hint">
            Drop any file here — CSV, PDF, Excel, a proposal doc. It attaches to this project automatically.
          </div>
        )}

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
