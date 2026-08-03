"use client";

import { useState } from "react";
import { Badge } from "@/components/ui";
import type { ChatToolCall, PendingApproval } from "@/lib/api";

function prettyResult(result: unknown): string {
  if (result == null) return "";
  if (typeof result !== "string") return JSON.stringify(result, null, 2);
  try {
    return JSON.stringify(JSON.parse(result), null, 2);
  } catch {
    return result;
  }
}

// A blocked call's status is resolved against the real ApprovalRequest at
// session-history read time (see api/v1/chat.py's _resolve_blocked_call_
// statuses) -- these outcomes must render distinctly from each other and
// from "Completed" (a real direct tool execution), since a rejected or
// failed action showing as "Completed" would say the opposite of what
// actually happened.
const STATUS_BADGE: Record<string, { label: string; variant: "success" | "warning" | "danger" }> = {
  blocked_pending_approval: { label: "Needs approval", variant: "warning" },
  approval_approved: { label: "Approved — pending execution", variant: "warning" },
  approval_rejected: { label: "Rejected", variant: "danger" },
  approval_executed: { label: "Approved & executed", variant: "success" },
  approval_failed: { label: "Approved — execution failed", variant: "danger" },
  denied_insufficient_role: { label: "Denied (role)", variant: "danger" },
};

export function ToolCallBlock({
  call,
  approval,
  onGoToApprovals,
  defaultOpen = false,
}: {
  call: ChatToolCall;
  approval?: PendingApproval;
  onGoToApprovals?: () => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const blocked = call.status === "blocked_pending_approval";
  const badge = STATUS_BADGE[call.status] ?? { label: "Completed", variant: "success" as const };

  return (
    <div className="chat-tool-block">
      <div className="chat-tool-block-header" onClick={() => setOpen((v) => !v)}>
        <span className="chat-tool-name">{call.tool}</span>
        <div className="flex items-center gap-2">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <span className="text-muted" style={{ fontSize: 10 }}>{open ? "▲" : "▼"}</span>
        </div>
      </div>
      {open && (
        <div className="chat-tool-block-body">
          <div className="chat-tool-label">Arguments</div>
          <pre>{JSON.stringify(call.args, null, 2)}</pre>
          {call.result != null && (
            <>
              <div className="chat-tool-label">Result</div>
              <pre>{prettyResult(call.result)}</pre>
            </>
          )}
        </div>
      )}
      {blocked && (
        <div className="chat-approval-notice">
          <span>⚠</span>
          <span>
            AXIOM paused this action for approval{approval?.risk_level ? ` (${approval.risk_level} risk)` : ""} instead
            of running it.
            {approval?.reason ? ` ${approval.reason}` : ""} Review and approve or reject it on the{" "}
            <button className="link-btn" onClick={onGoToApprovals}>Approvals screen</button>.
          </span>
        </div>
      )}
    </div>
  );
}
