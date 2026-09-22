"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, useToast } from "@/components/ui";
import { createTask, ApiError, type TaskSummary, type TaskShapeValue } from "@/lib/api";

// Extracted from the Tasks list page (Wunomo UI-rebuild slice 5, 2026-09-14)
// so the project container's Tasks tab can reuse it rather than duplicate
// it -- same component, two call sites, matching TaskCreateModal's own
// shared-between-entry-points precedent.
//
// Item 13: re-run a completed/failed task with the same goal, generating a
// fresh plan (a real generate_plan() call - same cost as any new task,
// normally 1 LLM call, up to 2 if the model's first response needs the
// existing one-shot corrective retry - see task_planner.py). Confirmed
// with the user before building that this button must not be one click
// away from spending that quota with no warning, hence the inline
// click-to-arm-then-confirm pattern below instead of firing immediately
// (no other destructive/costly action in this app uses a confirm dialog,
// but none of them spend real AI credits either - this one does).
const RERUNNABLE_STATUSES = new Set(["completed", "completed_with_unconfirmed_steps", "failed"]);
const CONFIRM_ARM_MS = 4000;

export function RerunButton({ token, task }: { token: string; task: TaskSummary }) {
  const toast = useToast();
  const router = useRouter();
  const qc = useQueryClient();
  const [armed, setArmed] = useState(false);
  const armTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (armTimer.current) clearTimeout(armTimer.current); }, []);

  const rerunMut = useMutation({
    mutationFn: () => createTask(token, { goal: task.goal, task_shape: task.task_shape as TaskShapeValue }),
    onSuccess: (newTask) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      toast.push("Fresh plan generated — review it before approving.", "success");
      router.push(`/tasks/${newTask.id}`);
    },
    onError: (err: unknown) => {
      const detail = err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Failed to generate a plan.";
      toast.push(detail, "danger");
    },
  });

  if (!RERUNNABLE_STATUSES.has(task.status)) return null;

  if (!armed) {
    return (
      <Button
        size="sm" variant="secondary"
        onClick={(e) => {
          e.stopPropagation();
          setArmed(true);
          armTimer.current = setTimeout(() => setArmed(false), CONFIRM_ARM_MS);
        }}
      >
        Re-run
      </Button>
    );
  }

  return (
    <Button
      size="sm" variant="primary"
      disabled={rerunMut.isPending}
      onClick={(e) => {
        e.stopPropagation();
        if (armTimer.current) clearTimeout(armTimer.current);
        setArmed(false);
        rerunMut.mutate();
      }}
    >
      {rerunMut.isPending ? "Generating…" : "Confirm — 1 AI call"}
    </Button>
  );
}
