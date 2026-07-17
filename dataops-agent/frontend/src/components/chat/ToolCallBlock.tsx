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

  return (
    <div className="chat-tool-block">
      <div className="chat-tool-block-header" onClick={() => setOpen((v) => !v)}>
        <span className="chat-tool-name">{call.tool}</span>
        <div className="flex items-center gap-2">
          <Badge variant={blocked ? "warning" : "success"}>{blocked ? "Needs approval" : "Completed"}</Badge>
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
