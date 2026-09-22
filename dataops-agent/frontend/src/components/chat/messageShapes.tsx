"use client";

// DESIGN_SPEC.md §7.3 -- shapes A (user), B (employee acknowledgement),
// C (streaming assistant), I (system line). Four of the spec's nine
// message shapes; D-H (output, approval, handoff, clarification,
// refusal) are not built yet -- nothing in real data produces them today
// (the supervisor that would is headless, not wired into any route), so
// there is deliberately no fifth "unbuilt shape" branch here that
// renders anything. When one of those ships, it plugs in as a sibling to
// these three, dispatched on real data (an outcome field, a Handoff row,
// a task's risk_level) the same way these are.
//
// B and C are the same component: "Same as B, but the body fills from
// token deltas" (§7.3.C) is a `streaming` flag, not a second component --
// the header/avatar/card structure is identical, only the working badge,
// avatar pulse, and trailing caret depend on it.
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
