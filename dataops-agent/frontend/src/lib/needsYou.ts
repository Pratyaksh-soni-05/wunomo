"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getActiveTasks, getMergedApprovals,
  type ActiveTaskRailItem, type MergedApproval,
} from "./api";

const APPROVALS_POLL_MS = 60000;

/**
 * The single "what's waiting on me" derivation (Wunomo UI-rebuild slice
 * 9, 2026-09-15) -- used by both the Sidebar's "Needs you" badge and the
 * Needs You screen itself, so the two can never disagree about how many
 * things need a decision the way they did before this slice (the Sidebar
 * counted getMergedApprovals().count only; the Topbar's separate task
 * rail counted task needs_attention only; neither ever saw the other).
 *
 * Four urgency tiers, not three -- splitting "approval" once dedup is
 * accounted for:
 *   0 - PAUSED_NEEDS_APPROVAL tasks: a real clock (APPROVAL_PAUSE_TIMEOUT_HOURS),
 *       soonest-to-expire first. Ignoring this costs an outcome you don't
 *       get to choose.
 *   1 - Standalone approvals (a chat-originated PolicyEngine request with
 *       no task, or a CI/CD deployment gate): a live, blocking decision
 *       with no clock anywhere in the code -- outranks an already-dead
 *       task because speed still helps here, unlike tier 2. Oldest first
 *       (longest-blocked).
 *   2 - PAUSED_FAILED_STEP / PAUSED_PLAN_INVALID tasks: already dead, no
 *       resume path exists (findings item 76) -- speed doesn't help,
 *       but still worth surfacing over a draft that was never started.
 *       Most-recently-died first.
 *   3 - DRAFT_PLAN tasks: sits forever, no decay. Oldest first (longest
 *       waiting).
 *
 * Dedup: a task's own PAUSED_NEEDS_APPROVAL and a `policy_engine`-sourced
 * MergedApproval can be the exact same ApprovalRequest row (task_executor.py
 * creates it via the same PolicyEngine.create_request() an ad-hoc chat
 * approval uses) -- findings item 98 documents why resolving it through
 * the generic approve/reject endpoint (rather than the task's own
 * resume/reject-step) leaves the task permanently stuck even though the
 * action ran. This hook excludes any MergedApproval whose id matches a
 * tier-0 task's current_step.approval_request_id, so it's never shown
 * twice and never resolved through the unsafe path.
 */
export type NeedsYouItem =
  | { kind: "task"; tier: 0 | 2 | 3; task: ActiveTaskRailItem }
  | { kind: "approval"; tier: 1; approval: MergedApproval };

// Mirrors api/v1/tasks.py's own _sort_key exactly -- same tiers (by
// task.attention_tier, the backend's original 0/1/2, not this hook's
// remapped 0/2/3), same fallback-sorts-last behavior for a missing
// timestamp (FAR_FUTURE for ascending fields, epoch for the one
// negated/descending field).
const FAR_FUTURE = 8640000000000000; // JS's max representable date, mirrors Python's datetime.max
const EPOCH_MS = 0;

function taskSortKey(task: ActiveTaskRailItem): number {
  if (task.attention_tier === 0) {
    // oldest paused_at first (soonest to expire)
    return task.paused_at ? new Date(task.paused_at).getTime() : FAR_FUTURE;
  }
  if (task.attention_tier === 1) {
    // most-recently-updated first (most recently died) -- ascending sort
    // of the negated timestamp puts the largest real timestamp first
    return -(task.updated_at ? new Date(task.updated_at).getTime() : EPOCH_MS);
  }
  // tier 2 (draft plan): oldest created_at first (longest waiting)
  return task.created_at ? new Date(task.created_at).getTime() : FAR_FUTURE;
}

export function useNeedsYou(token: string) {
  const activeTasksQuery = useQuery({
    queryKey: ["active-tasks"],
    queryFn: () => getActiveTasks(token),
    enabled: !!token,
  });
  const approvalsQuery = useQuery({
    queryKey: ["merged-approvals"],
    queryFn: () => getMergedApprovals(token),
    enabled: !!token,
    refetchInterval: APPROVALS_POLL_MS,
  });

  const tasks = activeTasksQuery.data ?? [];
  const attentionTasks = tasks.filter((t) => t.needs_attention);

  const linkedApprovalIds = new Set(
    attentionTasks
      .filter((t) => t.attention_tier === 0)
      .map((t) => t.current_step?.approval_request_id)
      .filter((id): id is string => !!id)
  );
  const standaloneApprovals = (approvalsQuery.data?.approvals ?? []).filter((a) => !linkedApprovalIds.has(a.id));

  const items: NeedsYouItem[] = [
    ...attentionTasks
      .filter((t) => t.attention_tier === 0)
      .map((task): NeedsYouItem => ({ kind: "task", tier: 0, task })),
    ...standaloneApprovals.map((approval): NeedsYouItem => ({ kind: "approval", tier: 1, approval })),
    ...attentionTasks
      .filter((t) => t.attention_tier === 1)
      .map((task): NeedsYouItem => ({ kind: "task", tier: 2, task })),
    ...attentionTasks
      .filter((t) => t.attention_tier === 2)
      .map((task): NeedsYouItem => ({ kind: "task", tier: 3, task })),
  ];

  items.sort((a, b) => {
    if (a.tier !== b.tier) return a.tier - b.tier;
    if (a.kind === "task" && b.kind === "task") return taskSortKey(a.task) - taskSortKey(b.task);
    if (a.kind === "approval" && b.kind === "approval") {
      // oldest first (longest-blocked), same reasoning as DRAFT_PLAN's own tier
      const aTime = a.approval.created_at ? new Date(a.approval.created_at).getTime() : FAR_FUTURE;
      const bTime = b.approval.created_at ? new Date(b.approval.created_at).getTime() : FAR_FUTURE;
      return aTime - bTime;
    }
    return 0;
  });

  return {
    items,
    count: items.length,
    loading: activeTasksQuery.isLoading || approvalsQuery.isLoading,
  };
}
