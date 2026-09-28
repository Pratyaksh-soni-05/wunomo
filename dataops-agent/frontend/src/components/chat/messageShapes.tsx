"use client";

// DESIGN_SPEC.md §7.3 -- shapes A (user), B (employee acknowledgement),
// C (streaming assistant), D (employee result), E (approval card),
// F (handoff card), I (system line). Seven of the spec's nine message
// shapes; G/H (clarification, refusal) are still not built -- the
// supervisor's needs_clarification/error outcomes are logged, not
// rendered (see the project chat page's own onNeedsClarification/onError
// handlers), so there is deliberately no eighth/ninth "unbuilt shape"
// branch here that renders anything for them yet.
//
// B and C are the same component: "Same as B, but the body fills from
// token deltas" (§7.3.C) is a `streaming` flag, not a second component --
// the header/avatar/card structure is identical, only the working badge,
// avatar pulse, and trailing caret depend on it.
import { useState } from "react";
import { Card, Badge, Button } from "@/components/ui";
import { EmployeeAvatar, employeeHueClass } from "./EmployeeAvatar";
import { ToolCallBlock } from "./ToolCallBlock";
import type { ChannelMemberAgent, ChatToolCall, PendingApproval } from "@/lib/api";

export function formatTime(timestamp: string): string {
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function formatAssistantText(text: string) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

// Shape J -- §7.3.J. Only a REAL, resolvable mention (an exact,
// case-insensitive name match against the channel's own current roster)
// renders as a chip -- an "@word" that doesn't match anyone (a typo, or a
// plain "@" used as punctuation) renders as plain text, same principle as
// the picker itself never offering a name guaranteed to fail. `--c` comes
// from the SAME employee-identity classes the avatar uses -- never a
// second, independent color source.
function renderWithMentionChips(text: string, roster: ChannelMemberAgent[] | undefined): React.ReactNode {
  if (!roster || roster.length === 0) return text;
  const byName = new Map(roster.map((a) => [a.name.toLowerCase(), a]));
  const re = /@(\w+)/g;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(text)) !== null) {
    const agent = byName.get(match[1].toLowerCase());
    if (!agent) continue;
    nodes.push(text.slice(lastIndex, match.index));
    nodes.push(
      <span key={key++} className={["mention-chip", employeeHueClass(agent.employee_type)].join(" ")}>
        @{agent.name}
      </span>
    );
    lastIndex = re.lastIndex;
  }
  nodes.push(text.slice(lastIndex));
  return nodes;
}

// Shape A -- §7.3.A.
export function UserMessage({
  content, timestamp, roster,
}: {
  content: string;
  timestamp: string;
  // The sending channel's current agent roster, for resolving mentions
  // into chips (§7.3.J) -- undefined outside a channel (mentions don't
  // exist there), matching resolveIdentity's own channel-only scoping.
  roster?: ChannelMemberAgent[];
}) {
  return (
    <div className="chat-bubble-user msg-enter">
      <div>
        <div className="chat-bubble-user-inner">{renderWithMentionChips(content, roster)}</div>
        <div className="msg-user-meta">You · {formatTime(timestamp)}</div>
      </div>
    </div>
  );
}

// Shapes B/C -- §7.3.B-C. `streaming` drives the only three differences
// spec calls out: the avatar's .is-working pulse, a "working" badge in
// the header, and a trailing caret (the only permitted "thinking"
// indicator -- D6, no spinner ever). Once streaming ends, the message
// renders as a plain, finished B -- there is no "success" badge here
// (that's shape D's own addition, not built yet); showing one on a
// bare acknowledgement/answer would claim more than this pass built.
export function EmployeeMessage({
  name,
  employeeType,
  timestamp,
  content,
  toolCalls,
  streaming,
  approvals,
  onGoToApprovals,
  currentUserRole,
}: {
  name: string;
  employeeType?: string | null;
  timestamp: string;
  content: string;
  toolCalls: ChatToolCall[];
  streaming: boolean;
  approvals?: PendingApproval[];
  onGoToApprovals?: () => void;
  currentUserRole?: string | null;
}) {
  return (
    <div className="chat-bubble-assistant msg-enter">
      <EmployeeAvatar name={name} employeeType={employeeType} isWorking={streaming} />
      <div className="chat-bubble-assistant-inner">
        <div className="msg-employee-header">
          <span className="msg-employee-name">{name}</span>
          {streaming && <Badge variant="info">working</Badge>}
          <span className="msg-employee-time">{formatTime(timestamp)}</span>
        </div>
        <Card className="chat-bubble-assistant-text">
          <span dangerouslySetInnerHTML={{ __html: formatAssistantText(content) }} />
          {streaming && <span className="msg-caret" aria-hidden="true" />}
        </Card>
        {toolCalls.map((call, ci) => (
          <ToolCallBlock
            key={ci}
            call={call}
            approval={approvals?.find((a) => a.name === call.tool)}
            onGoToApprovals={onGoToApprovals}
            currentUserRole={currentUserRole}
          />
        ))}
      </div>
    </div>
  );
}

// Shape D -- §7.3.D. Splits `content` into a one-or-two-sentence lead
// (shown as the bare answer, matching B/C's plain text treatment) and
// whatever follows, which -- only when there IS a real "whatever
// follows", or a real tool produced a result -- moves into the output
// card instead of running on inline. A short answer with nothing past
// its own lead sentence has nothing worth a second, redundant copy of
// itself in a card below it, so it renders with no card at all: same
// plain body as B, just with the `done` badge D adds.
function splitLeadAndRest(content: string): { lead: string; rest: string | null } {
  // First sentence end (. ! ?) followed by whitespace, or the first
  // paragraph break -- whichever comes first. No sentence boundary at all
  // (e.g. a bare list/table with no lead-in prose) means the whole thing
  // IS the lead; rest stays null rather than duplicating it below.
  const boundary = content.search(/[.!?](\s+)|\n\s*\n/);
  if (boundary === -1) return { lead: content, rest: null };
  const sentenceMatch = content.slice(0, boundary + 1).match(/[.!?]$/);
  const cut = sentenceMatch ? boundary + 1 : boundary;
  const lead = content.slice(0, cut).trim();
  const rest = content.slice(cut).trim();
  return rest ? { lead, rest } : { lead: content, rest: null };
}

// A card exists to hold content that would otherwise crowd out the lead
// sentence -- real prose past the lead, a markdown table/list, or a real
// tool result. Never lead with a table (§7.3.D's own words) is exactly
// what this keeps true: a table only ever appears inside the card.
function needsOutputCard(rest: string | null, toolCalls: ChatToolCall[]): boolean {
  if (rest && rest.length > 0) return true;
  return toolCalls.some((c) => c.status === "completed" && (c.result != null || !!c.result_summary));
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

// No real file-producing tool exists anywhere in this codebase today
// (confirmed by reading every agent/tools/*.py file -- export_dataset is
// an explicit, permanent stub: "there is no real export path in this
// system for any format or destination"). Rather than a Download button
// with nothing real behind it, this downloads the turn's own real content
// client-side -- a real file, genuinely produced from the real response
// text, never a fabricated filename pointing at nothing.
function downloadAsFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function titleCaseToolName(tool: string): string {
  return tool.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

export function EmployeeResult({
  name,
  employeeType,
  timestamp,
  content,
  toolCalls,
  approvals,
  onGoToApprovals,
  currentUserRole,
  caveat,
}: {
  name: string;
  employeeType?: string | null;
  timestamp: string;
  content: string;
  toolCalls: ChatToolCall[];
  approvals?: PendingApproval[];
  onGoToApprovals?: () => void;
  currentUserRole?: string | null;
  // Mandatory to render whenever it exists (§7.3.D), but nothing in this
  // codebase's real tool results carries a caveat/assumption/warning field
  // today (checked modules/reporting/report_generator.py directly) --
  // undefined on every real payload this pass could exercise live. Kept as
  // a real prop, not dropped, so the day a tool starts returning one this
  // has somewhere to go without another pass through this component.
  caveat?: string | null;
}) {
  const [showWork, setShowWork] = useState(false);
  const [showHowMade, setShowHowMade] = useState(false);
  const { lead, rest } = splitLeadAndRest(content);
  const showCard = needsOutputCard(rest, toolCalls);
  const completedTool = toolCalls.find((c) => c.status === "completed");
  const filename = completedTool ? `${titleCaseToolName(completedTool.tool)}.md` : "Response.md";

  return (
    <div className="chat-bubble-assistant msg-enter">
      <EmployeeAvatar name={name} employeeType={employeeType} />
      <div className="chat-bubble-assistant-inner">
        <div className="msg-employee-header">
          <span className="msg-employee-name">{name}</span>
          <Badge variant="success">done</Badge>
          <span className="msg-employee-time">{formatTime(timestamp)}</span>
        </div>
        <Card className="chat-bubble-assistant-text">
          <span dangerouslySetInnerHTML={{ __html: formatAssistantText(lead) }} />
        </Card>
        {showCard && (
          <div className="output-card">
            <div className="output-card-header">
              <div className="output-card-title-group">
                <span className="output-card-filename">{filename}</span>
                <span className="output-card-subline">{wordCount(content)} words · {name}</span>
              </div>
              <Badge variant="gray">AI-generated</Badge>
              <Button size="sm" className="btn-dense" onClick={() => downloadAsFile(filename, content)}>
                Download
              </Button>
            </div>
            {rest && (
              <div className="output-card-preview">
                <span dangerouslySetInnerHTML={{ __html: formatAssistantText(rest) }} />
              </div>
            )}
            <div className="output-card-footer">
              <button type="button" className="output-card-link" onClick={() => setShowWork((v) => !v)}>
                Show work
              </button>
              <button type="button" className="output-card-link" onClick={() => setShowHowMade((v) => !v)}>
                How this was made
              </button>
              {caveat && <span className="output-card-caveat">{caveat}</span>}
            </div>
            {showHowMade && (
              <div className="output-card-detail">
                Generated by {name}
                {completedTool
                  ? ` using ${toolCalls.filter((c) => c.status === "completed").map((c) => c.tool).join(", ")}.`
                  : " from its own reasoning, with no tool call."}
              </div>
            )}
            {showWork && toolCalls.map((call, ci) => (
              <ToolCallBlock
                key={ci}
                call={call}
                approval={approvals?.find((a) => a.name === call.tool)}
                onGoToApprovals={onGoToApprovals}
                currentUserRole={currentUserRole}
                defaultOpen
              />
            ))}
          </div>
        )}
        {!showCard && toolCalls.map((call, ci) => (
          <ToolCallBlock
            key={ci}
            call={call}
            approval={approvals?.find((a) => a.name === call.tool)}
            onGoToApprovals={onGoToApprovals}
            currentUserRole={currentUserRole}
          />
        ))}
      </div>
    </div>
  );
}

// Shape E -- §7.3.E. Rendered the moment a task's own "paused_needs_
// approval" supervisor_task event arrives (modules/orchestration/
// supervisor.py's _run_one_task relays approval_request_id/risk_level/
// reason/unblocks alongside the status itself now -- see this pass's own
// report for why that relay didn't already exist). approveRequest()/
// rejectRequest() (already-shipped Approvals-screen actions, reused here
// rather than a second implementation) both resolve synchronously all the
// way through resolve_task_approval()'s wave-drain before returning, so
// by the time either promise settles the real outcome (this task AND any
// dependent it released) is already fully persisted -- the caller's job
// is just to refetch history once it does.
//
// "scoped-approve" (the spec's secondary action) is deliberately omitted:
// no backend action exists anywhere in this codebase for it (checked
// modules/governance/policy_engine.py directly) -- a button with no real
// action behind it is worse than one fewer button. See this pass's own
// report.
export function ApprovalCard({
  riskLevel,
  reason,
  unblocks,
  onApprove,
  onReject,
  busy,
}: {
  riskLevel: string;
  reason: string;
  unblocks?: string | null;
  onApprove: () => void;
  onReject: () => void;
  busy?: "approving" | "rejecting" | null;
}) {
  const riskBadge = riskLevel === "high" ? "danger" : riskLevel === "medium" ? "warning" : "gray";
  return (
    <div className="approval-card msg-enter">
      <div className="approval-card-header">
        <span className="approval-card-dot" aria-hidden="true" />
        <span className="approval-card-title">Approval needed</span>
        <Badge variant={riskBadge}>{riskLevel} risk</Badge>
      </div>
      <div className="approval-card-body">
        <div className="approval-card-row">
          <span className="approval-card-label">Reason</span>
          <span className="approval-card-value">{reason}</span>
        </div>
        {unblocks && (
          <div className="approval-card-row">
            <span className="approval-card-label">Unblocks</span>
            <span className="approval-card-value">{unblocks}</span>
          </div>
        )}
      </div>
      <div className="approval-card-actions">
        <Button size="sm" variant="success" className="btn-dense" onClick={onApprove} disabled={!!busy}>
          {busy === "approving" ? "Approving…" : "Approve"}
        </Button>
        <Button size="sm" variant="danger" className="btn-dense" onClick={onReject} disabled={!!busy}>
          {busy === "rejecting" ? "Rejecting…" : "Reject"}
        </Button>
        <span className="approval-card-status">Task is paused</span>
      </div>
    </div>
  );
}

// Shape F -- §7.3.F. Built from the real Handoff row -- live, via the
// `handoff` SSE event (api/v1/chat.py's _run_supervisor_and_stream), or
// after a reload via GET .../history (_handoff_entries, which this pass
// extended to carry these same structured fields instead of only a
// pre-flattened sentence -- see this pass's own report). Not a message
// from either agent -- no avatar-pulse, no working badge, a distinct
// single-row layout matching neither B/C nor a plain system line.
export function HandoffCard({
  fromAgentId,
  fromAgentName,
  toAgentId,
  toAgentName,
  payloadSummary,
  withheld,
  timestamp,
  roster,
}: {
  fromAgentId?: string | null;
  fromAgentName: string;
  toAgentId?: string | null;
  toAgentName: string;
  payloadSummary: string;
  withheld: string[];
  timestamp: string;
  roster?: ChannelMemberAgent[];
}) {
  const fromType = roster?.find((a) => a.id === fromAgentId)?.employee_type;
  const toType = roster?.find((a) => a.id === toAgentId)?.employee_type;
  return (
    <div className="handoff-card msg-enter">
      <div className="handoff-card-row">
        <EmployeeAvatar name={fromAgentName} employeeType={fromType} size="sm" />
        <span className="handoff-card-name">{fromAgentName}</span>
        <span className="handoff-card-verb">handed over to</span>
        <EmployeeAvatar name={toAgentName} employeeType={toType} size="sm" />
        <span className="handoff-card-name">{toAgentName}</span>
        <span className="handoff-card-time">{formatTime(timestamp)} · logged</span>
      </div>
      <div className="handoff-card-summary">{payloadSummary}</div>
      {withheld.length > 0 && (
        // A privacy feature, not decoration (§7.3.F's own words) -- render
        // whenever `withheld` is non-empty, full stop. No pronoun guessed
        // for the receiving agent; the spec's own example phrasing ("he
        // doesn't need them") isn't reused for exactly that reason.
        <div className="handoff-card-withheld">
          {toAgentName} did not receive {withheld.join(", ")} — not needed for this task.
        </div>
      )}
    </div>
  );
}

// Shape I -- §7.3.I. Used today for: a channel-routing failure notice
// (unknown/non-member @mention -- the closest existing real event to
// spec's "hires, approvals granted, inferred-edge notices, date
// separators" list) and the legacy "Started task" card's replacement...
// actually the taskCard shape keeps its own distinct rendering (it has a
// button, which this centred/ruled treatment has no room for) -- see
// MessageThread's dispatcher.
export function SystemLine({ text }: { text: string }) {
  return <div className="msg-system-line msg-enter">{text}</div>;
}

export function TaskStartedLine({
  goal,
  onView,
}: {
  goal: string;
  onView: () => void;
}) {
  return (
    <div className="chat-bubble-assistant msg-enter">
      <div className="chat-bubble-assistant-inner">
        <Card className="chat-bubble-assistant-text flex items-center justify-between" style={{ gap: 12 }}>
          <span>Started task: <strong>{goal}</strong></span>
          <Button size="sm" onClick={onView}>View progress</Button>
        </Card>
      </div>
    </div>
  );
}
