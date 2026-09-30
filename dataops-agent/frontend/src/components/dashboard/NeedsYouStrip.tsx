"use client";

// Command Center (blueprint §05) -- "'Needs you' is always the top strip...
// full-width, violet-bordered, with the money and the wait time visible
// before you click. It is the only element allowed above the fold when it
// exists. If nothing is pending, the strip is simply absent -- no
// '0 approvals' card." Rendered only when `tasks` is non-empty -- the
// caller (home/page.tsx) already filters to status === "paused_needs_
// approval" before this component ever sees a row.
//
// No money amount: blueprint's own mock example ("₹4,82,300 to 14
// vendors") is a payment-run scenario this product doesn't have -- no
// agent tool call here carries a currency amount. Shown instead: the real
// step description awaiting approval (current_step.description), falling
// back to action_text's own "Review to approve or reject — expires in
// Nh." -- NOT pause_reason, which api/v1/tasks.py's _pause_reason() only
// ever populates for PAUSED_FAILED_STEP, never for this status (confirmed
// by direct read; it's null here 100% of the time). Wait time (paused_at)
// is the other thing blueprint's own note calls out as required before
// any click.
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, useToast } from "@/components/ui";
import { EmployeeAvatar } from "@/components/chat/EmployeeAvatar";
import { timeAgo } from "@/lib/dates";
import { getToken, resumeTask, type ActiveTaskRailItem } from "@/lib/api";
import { resumeActuallyHappened, describeNoOpOutcome } from "@/lib/resumeOutcome";

// Two actions, matching §05's "Review detail"/"Approve" pair -- reusing
// the exact same resumeTask() mutation /approvals's own Needs You screen
// already wires to POST /tasks/{id}/resume, so a one-click approve here
// and a full review there can never disagree about what "approve" does.
export function NeedsYouStrip({ tasks }: { tasks: ActiveTaskRailItem[] }) {
  const router = useRouter();
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();

  // resume_task() returns a 200 even when nothing happened (e.g. the step
  // was already resolved) -- resumeActuallyHappened() checks the real
  // outcome before this button is allowed to claim success. See
  // lib/resumeOutcome.ts for why this exists (caught live on this exact
  // button, first seed).
  const resumeMut = useMutation({
    mutationFn: (id: string) => resumeTask(token, id),
    onSuccess: (result) => {
      if (resumeActuallyHappened(result.resume_outcome?.outcome)) {
        toast.push("Approved — resuming.", "success");
      } else {
        toast.push(describeNoOpOutcome(result.resume_outcome?.outcome), "danger");
      }
      qc.invalidateQueries({ queryKey: ["active-tasks"] });
    },
    onError: () => toast.push("Failed to approve.", "danger"),
  });

  if (tasks.length === 0) return null;

  return (
    <div className="needs-you-strip">
      {tasks.map((t) => (
        <div key={t.id} className="needs-you-row">
          <span className="needs-you-dot" aria-hidden="true" />
          <EmployeeAvatar name={t.agent_name ?? "AXIOM"} employeeType={null} size="sm" />
          <div className="needs-you-body">
            <div className="needs-you-title">
              {t.agent_name ?? "An employee"} is waiting on your approval to {t.goal}
            </div>
            <div className="needs-you-meta">
              {t.current_step?.description ?? t.action_text ?? "A risk-gated action needs sign-off."}
              {t.project_name ? ` · ${t.project_name}` : ""} · waiting since {timeAgo(t.paused_at ?? t.created_at)}
            </div>
          </div>
          <div className="needs-you-actions">
            <Button size="sm" variant="secondary" className="btn-dense" onClick={() => router.push(`/tasks/${t.id}`)}>
              Review
            </Button>
            <Button
              size="sm" variant="primary" className="btn-dense"
              disabled={resumeMut.isPending} onClick={() => resumeMut.mutate(t.id)}
            >
              Approve
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
