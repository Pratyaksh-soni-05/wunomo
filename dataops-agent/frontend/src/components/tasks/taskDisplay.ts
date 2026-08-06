// Shared display helpers for Task/TaskStep -- one source of truth for
// status/provenance -> Badge variant + label, used by the Tasks list page,
// the Task detail page, and the chat inline "Started task" card, so the
// three surfaces can never silently drift apart on what a status means.
import type { TaskStepProvenance } from "@/lib/api";

type BadgeVariant = "success" | "danger" | "warning" | "info" | "gray" | "midnight";

export function taskStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "draft_plan": return "info";
    case "queued": return "gray";
    case "running": return "info";
    case "paused_needs_approval":
    case "paused_failed_step":
    case "paused_plan_invalid":
    case "paused_quota_exceeded":
      return "warning";
    case "completed": return "success";
    case "completed_with_unconfirmed_steps": return "warning";
    case "failed": return "danger";
    case "cancelled": return "gray";
    case "expired": return "gray";
    case "plan_rejected": return "gray";
    default: return "gray";
  }
}

export function taskStatusLabel(status: string): string {
  return status
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

// Every reason field a terminal/attention status can carry (stage 6/7
// requirement: surfaced legibly, not a bare status badge). At most one is
// ever non-null for a given task, per _serialize_task()'s own logic.
export function taskReasonText(task: {
  status: string;
  pause_reason: string | null;
  completion_note: string | null;
  approval_pending_reason: string | null;
  expiry_reason: string | null;
  quota_paused_reason: string | null;
  termination_reason: string | null;
}): { text: string; variant: BadgeVariant } | null {
  if (task.approval_pending_reason) return { text: task.approval_pending_reason, variant: "warning" };
  if (task.quota_paused_reason) return { text: task.quota_paused_reason, variant: "warning" };
  if (task.pause_reason) return { text: task.pause_reason, variant: "warning" };
  if (task.completion_note) return { text: task.completion_note, variant: "warning" };
  if (task.expiry_reason) return { text: task.expiry_reason, variant: "gray" };
  // termination_reason is real/persisted (cancel, or a stage-6 cap) --
  // shown last since the computed reasons above are more specific when
  // both happen to be present.
  if (task.termination_reason) return { text: task.termination_reason, variant: "danger" };
  return null;
}

export function stepStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "pending": return "gray";
    case "running": return "info";
    case "verifying": return "info";
    case "succeeded": return "success";
    case "failed": return "danger";
    case "skipped": return "gray";
    case "blocked_approval": return "warning";
    default: return "gray";
  }
}

export function provenanceVariant(source: TaskStepProvenance): BadgeVariant {
  switch (source) {
    case "llm_planned": return "gray";
    case "human_edited": return "warning";
    case "system_inserted": return "midnight";
    default: return "gray";
  }
}

export function provenanceLabel(source: TaskStepProvenance): string {
  switch (source) {
    case "llm_planned": return "AXIOM planned";
    case "human_edited": return "Human edited";
    case "system_inserted": return "System inserted";
    default: return source;
  }
}

export const TERMINAL_TASK_STATUSES = new Set([
  "plan_rejected", "completed", "completed_with_unconfirmed_steps", "failed", "cancelled", "expired",
]);
