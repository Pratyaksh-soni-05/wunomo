// Extracted from the project container layout (app/(app)/projects/[id]/
// layout.tsx, blueprint chrome pass) once a second real consumer (Command
// Center's project-cards strip, blueprint §05) needed the exact same
// precedence -- "same precedence as ProjectHeader" is the literal
// requirement, so this makes disagreement structurally impossible instead
// of relying on two hand-kept copies staying in sync.
import type { BadgeVariant } from "@/components/ui";
import { ISSUE_STATUSES, RUNNING_STATUSES } from "./activeTaskDisplay";

export interface ProjectStatusBadge {
  variant: BadgeVariant;
  label: string;
}

// Precedence exactly as specified: approval pending outranks running
// outranks a real failure/block outranks the "nothing active" default --
// first match wins, checked top to bottom.
export function computeProjectStatusBadge(tasks: { status: string }[]): ProjectStatusBadge {
  const issueCount = tasks.filter((t) => ISSUE_STATUSES.has(t.status)).length;
  if (tasks.some((t) => t.status === "paused_needs_approval")) return { variant: "hold", label: "needs you" };
  if (tasks.some((t) => RUNNING_STATUSES.has(t.status))) return { variant: "info", label: "working" };
  if (issueCount > 0) return { variant: "warning", label: issueCount === 1 ? "1 issue" : `${issueCount} issues` };
  return { variant: "success", label: "all clear" };
}
