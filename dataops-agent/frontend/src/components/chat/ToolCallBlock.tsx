"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button } from "@/components/ui";
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
// actually happened. denied_out_of_scope/denied_source_locked (Wunomo
// Projects Phase 2 frontend, slice 9) close a real bug: both used to fall
// through to the default "Completed" badge, indistinguishable from a
// genuine success.
const STATUS_BADGE: Record<string, { label: string; variant: "success" | "warning" | "danger" }> = {
  blocked_pending_approval: { label: "Needs approval", variant: "warning" },
  approval_approved: { label: "Approved — pending execution", variant: "warning" },
  approval_rejected: { label: "Rejected", variant: "danger" },
  approval_executed: { label: "Approved & executed", variant: "success" },
  approval_failed: { label: "Approved — execution failed", variant: "danger" },
  denied_insufficient_role: { label: "Denied (role)", variant: "danger" },
  denied_out_of_scope: { label: "Blocked — out of scope", variant: "danger" },
  denied_source_locked: { label: "Blocked — source in use", variant: "warning" },
};

// The real grant endpoint (POST /api/v1/agents/{id}/sources/{id}) is
// role-gated to Owner/Admin server-side -- this is UX politeness on top of
// that, not the enforcement itself. Showing a "Grant access" button a
// Data Analyst can't actually use is worse than a plain refusal (explicit
// requirement): they'd click it, land on a page they may not be able to
// act on, and learn nothing they couldn't already read in the message.
const CAN_GRANT_ROLES = new Set(["owner", "admin"]);

export function ToolCallBlock({
  call,
  approval,
  onGoToApprovals,
  currentUserRole,
  defaultOpen = false,
}: {
  call: ChatToolCall;
  approval?: PendingApproval;
  onGoToApprovals?: () => void;
  currentUserRole?: string | null;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const router = useRouter();
  const blocked = call.status === "blocked_pending_approval";
  const scopeDenied = call.status === "denied_out_of_scope";
  const sourceLocked = call.status === "denied_source_locked";
  const badge = STATUS_BADGE[call.status] ?? { label: "Completed", variant: "success" as const };
  const canGrant = !!currentUserRole && CAN_GRANT_ROLES.has(currentUserRole.toLowerCase());

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
      {scopeDenied && (
        <div className="chat-approval-notice">
          <span>⚠</span>
          <span>
            {call.reason}{" "}
            {canGrant && call.agent_id ? (
              <Button
                size="sm"
                onClick={() => router.push(`/agents/${call.agent_id}${call.source_id ? `?highlight_source=${call.source_id}` : ""}`)}
              >
                Grant access
              </Button>
            ) : (
              "An Owner or Admin needs to grant this — ask them, since your role can't."
            )}
          </span>
        </div>
      )}
      {sourceLocked && (
        <div className="chat-approval-notice">
          <span>⚠</span>
          <span>
            This call failed and won&apos;t retry automatically — unlike a paused task, a chat message fails fast.
            Try again in a moment once the source frees up.
          </span>
        </div>
      )}
    </div>
  );
}
