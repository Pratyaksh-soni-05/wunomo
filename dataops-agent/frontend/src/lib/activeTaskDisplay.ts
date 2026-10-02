// Shared "how do we describe an ActiveTaskRailItem" logic -- extracted from
// LiveWorkPanel.tsx (Command Center pass, blueprint §05) once a second real
// consumer (the Command Center's "Working now" hero) needed the exact same
// badge/step-line mapping. Duplicating it a second time risked exactly the
// drift this codebase's own conventions warn against (STAGE_OWNERSHIP.md:
// "never create a second hand-maintained list... derive from the single
// source") -- both LiveWorkPanel and Command Center now import from here.
//
// §7.6/§05 both assume fields this schema doesn't have: a numeric
// SUPERVISOR_RUNNING "{n}%" (no units_total/units_done anywhere on Task/
// TaskStep) and a BLOCKED_ON_DEPENDENCY line naming "{upstream agent}'s
// {task}" (ActiveTaskRailItem carries no depends_on_task_id or upstream
// identity at all). Mapped here against what's actually real.
import type { BadgeVariant } from "@/components/ui";
import type { ActiveTaskRailItem } from "./api";

// A task counts as "working" (Command Center's hero list) vs. "needs you"
// (paused_needs_approval, shown in its own strip) vs. "1 issue" (a real
// failure/block) -- same three-way split ProjectHeader's own status badge
// already uses (app/(app)/projects/[id]/layout.tsx), reused via
// lib/projectStatusBadge.ts, not redefined a second time here.
export const RUNNING_STATUSES = new Set([
  "running", "supervisor_running", "queued", "supervisor_queued",
  // Auto-retrying, not a failure -- the system is actively retrying these,
  // same register as queued/running, not stuck.
  "paused_quota_exceeded", "paused_source_locked",
]);
export const ISSUE_STATUSES = new Set(["failed", "blocked_on_dependency", "paused_failed_step", "paused_plan_invalid"]);

export function liveWorkBadge(status: string): { variant: BadgeVariant; label: string } {
  switch (status) {
    case "supervisor_queued": return { variant: "gray", label: "queued" };
    case "supervisor_running": return { variant: "info", label: "running" };
    case "blocked_on_dependency": return { variant: "warning", label: "blocked" };
    case "paused_needs_approval": return { variant: "hold", label: "needs you" };
    case "failed": return { variant: "danger", label: "failed" };
    case "queued": return { variant: "gray", label: "queued" };
    case "running": return { variant: "info", label: "running" };
    default: return { variant: "warning", label: "paused" };
  }
}

// "The step line always carries a real unit of work... where no count
// exists, name the step" -- every real task takes the "name the step"
// branch, never a numeric one. No progress bar/percentage/spinner anywhere
// this feeds -- there is nothing honest to animate.
export function liveWorkStepLine(t: ActiveTaskRailItem): string {
  if (t.current_step) return `Step ${t.current_step.step_index + 1}: ${t.current_step.description}`;
  if (t.status === "paused_needs_approval") return "Paused — waiting for your approval";
  if (t.status === "blocked_on_dependency") return t.pause_reason ?? "Blocked on an upstream task — retry it to release this.";
  if (t.action_text) return t.action_text;
  if (t.pause_reason) return t.pause_reason;
  return "Waiting to start";
}
