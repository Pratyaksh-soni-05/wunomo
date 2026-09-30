// resume_task()/reject_task_step() (modules/orchestration/task_executor.py)
// return a 200 with an "outcome" field even when nothing actually changed
// -- the endpoint only converts "not_resumable"/"expired" into a real HTTP
// 409 (see api/v1/tasks.py's resume_task_endpoint/reject_task_step_endpoint),
// so a caller whose step isn't BLOCKED_APPROVAL (already resolved by someone
// else, or never really blocked) gets outcome "no_blocked_step" back with a
// 200 -- indistinguishable from real success unless the outcome itself is
// checked. Caught live building the Command Center's Approve button: the
// first seed used the wrong step status, the mutation's onSuccess fired
// unconditionally, and the toast said "Approved — resuming" while the task
// row never moved. This is the single source of truth for "did this call
// actually do anything," shared by every caller of resumeTask/rejectTaskStep
// (NeedsYouStrip, the /approvals page) so neither can regress independently.
const NO_OP_OUTCOMES = new Set([
  "no_blocked_step", "task_not_found", "task_busy", "not_runnable", "not_resumable", "expired",
]);

export function resumeActuallyHappened(outcome: string | undefined | null): boolean {
  return !!outcome && !NO_OP_OUTCOMES.has(outcome);
}

export function describeNoOpOutcome(outcome: string | undefined | null): string {
  if (outcome === "task_busy") return "Another update is already in progress — try again in a moment.";
  return "Nothing to approve — this step may already be resolved. Refresh and check the task.";
}
