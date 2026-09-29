"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Badge, Select } from "@/components/ui";
import { parseApiDate } from "@/lib/dates";
import { EmployeeAvatar } from "./EmployeeAvatar";
import { Composer } from "./Composer";
import { ChannelMembersModal } from "./ChannelMembersModal";
import {
  UserMessage, EmployeeMessage, EmployeeResult, ApprovalCard, HandoffCard, SystemLine, TaskStartedLine,
} from "./messageShapes";
import type { LocalChatMessage } from "./types";
import type {
  SelectableAgent, ChannelItem, ChannelMemberAgent, ChannelMemberUser, ChatContext, TeamMember,
} from "@/lib/api";

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
  hideHeader,
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
  // fully-resolved history message can. Absent/undefined on the buffered
  // path (sendChatMessage) — this prop only exists so a caller wired to
  // sendChatMessageStream() can surface it.
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
  // Shape E (§7.3.E) actions -- undefined on a host with no supervisor
  // approval flow wired up (e.g. the direct AXIOM chat page never emits
  // approvalCard-shaped messages, so these are simply never called there).
  onApproveTask?: (approvalRequestId: string) => void;
  onRejectTask?: (approvalRequestId: string) => void;
  busyApprovalId?: string | null;
  busyApprovalAction?: "approving" | "rejecting" | null;
  // Blueprint chrome pass (feature/blueprint-workspace-chrome): the project
  // route (§7.2) renders its own full-width ProjectHeader above BOTH panes
  // instead of this component's internal per-thread header -- undefined/
  // false leaves /chat's own header exactly as it was. The Members modal
  // stays real either way (ChannelMembersModal, shared with ProjectHeader's
  // own "Manage members" menu item) -- only the always-visible header
  // button that opened it moves, on the project route only.
  hideHeader?: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const [membersModalOpen, setMembersModalOpen] = useState(false);

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

  // Fix (item 4a, screenshot review): render in real creation-time order
  // rather than trusting array-append order -- a stable sort (guaranteed
  // by the spec since ES2019, so ties keep their original relative
  // position). The real bug this caught live: task-card entries
  // (GET .../history's _task_card_entries) carry a bare `str(datetime)`
  // backend timestamp with no timezone marker ("2026-09-28 19:58:32...");
  // plain `new Date()` on that string is parsed as the BROWSER's local
  // time, not UTC, while every client-built message uses a proper
  // `.toISOString()` ("...Z") timestamp -- comparing the two directly put
  // backend-sourced entries hours off from client-sourced ones (a 5:30
  // shift on this box), which is exactly why they rendered above the user
  // message that triggered them. lib/dates.ts's parseApiDate() already
  // exists for precisely this (three documented raw shapes, see its own
  // comment) -- reused here rather than a second, local timestamp parser.
  const sortedMessages = [...messages].sort((a, b) => {
    const at = parseApiDate(a.timestamp)?.getTime() ?? 0;
    const bt = parseApiDate(b.timestamp)?.getTime() ?? 0;
    return at - bt;
  });

  // Shape C (streaming) -- per-message m.streaming (LocalChatMessage's own
  // field, types.ts), never inferred from array position. Position-based
  // "whichever message is last" broke the instant a second concurrent
  // supervisor task bubble was appended after the first: the first
  // permanently stopped being "last" and so permanently stopped showing as
  // streaming even while its own tokens kept arriving -- see types.ts's own
  // comment on `streaming` for the full history. `anyStreaming` drives the
  // fallback ThinkingIndicator below: shown only when `sending` is true but
  // nothing in the array has its own live bubble yet (before the first SSE
  // event arrives, or on the buffered non-streaming path, which never sets
  // `streaming` on anything at all).
  const anyStreaming = messages.some((m) => m.streaming);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  return (
    <div className="chat-main">
      {!hideHeader && (
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
      )}

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

        {sortedMessages.map((m, i) => {
          if (m.taskCard) {
            // Not one of the nine spec shapes -- keeps its own pre-
            // existing rendering (a button doesn't fit shape I's
            // centred/ruled treatment) rather than being forced into A/B/C/I.
            return <TaskStartedLine key={i} goal={m.taskCard.goal} onView={() => router.push(`/tasks/${m.taskCard!.id}`)} />;
          }
          if (m.role === "user") {
            return <UserMessage key={i} content={m.content} timestamp={m.timestamp} roster={channelAgents} />;
          }
          // Shape F -- a real Handoff row, live (the `handoff` SSE event)
          // or after reload (GET .../history, extended to carry these same
          // structured fields). Checked before the generic system_notice
          // branch below since a handoff IS one, just a richer-shaped one.
          if (m.from_agent_id !== undefined && m.from_agent_id !== null) {
            return (
              <HandoffCard
                key={i}
                fromAgentId={m.from_agent_id}
                fromAgentName={m.from_agent_name ?? "Unknown"}
                toAgentId={m.to_agent_id}
                toAgentName={m.to_agent_name ?? "Unknown"}
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
          const streamingThis = !!m.streaming;

          // Shape E -- rendered the moment this turn's own
          // paused_needs_approval event arrives (live) or is still pending
          // on reload (the page merges a live-only approvalCard back after
          // every history refetch -- see this pass's own report for the
          // bug that merge fixed).
          if (m.approvalCard) {
            return (
              <ApprovalCard
                key={i}
                riskLevel={m.approvalCard.risk_level}
                reason={m.approvalCard.reason}
                unblocks={m.approvalCard.unblocks}
                onApprove={() => onApproveTask?.(m.approvalCard!.approval_request_id)}
                onReject={() => onRejectTask?.(m.approvalCard!.approval_request_id)}
                busy={busyApprovalId === m.approvalCard.approval_request_id ? busyApprovalAction : null}
              />
            );
          }

          // Shape D once a turn is finished and didn't fail -- streaming
          // and mid-flight messages stay B/C (EmployeeMessage); a failed
          // terminal turn also stays B/C rather than claiming a `done`
          // badge on something that didn't actually succeed.
          if (!streamingThis && !m.taskFailed) {
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
              streaming={streamingThis}
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
        {sending && !anyStreaming && <ThinkingIndicator />}
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

      <Composer
        draft={draft}
        onDraftChange={onDraftChange}
        onSend={onSend}
        sending={sending}
        sendError={sendError}
        channel={channel}
        channelAgents={channelAgents}
        attachedContext={attachedContext}
        onClearContext={onClearContext}
        uploading={uploading}
        uploadError={uploadError}
        onUploadFile={onUploadFile}
        onTagUnhiredType={onTagUnhiredType}
      />

      {channel && (
        <ChannelMembersModal
          open={membersModalOpen}
          onClose={() => setMembersModalOpen(false)}
          channel={channel}
          channelAgents={channelAgents}
          channelUsers={channelUsers}
          availableAgents={availableAgents}
          availablePeople={availablePeople}
          currentUserId={currentUserId}
          onAddAgent={onAddAgent}
          onRemoveAgent={onRemoveAgent}
          onAddPerson={onAddPerson}
          onRemovePerson={onRemovePerson}
        />
      )}
    </div>
  );
}
