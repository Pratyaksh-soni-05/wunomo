"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Modal, Button, Select, useToast } from "@/components/ui";
import { createTask, ApiError, TASK_SHAPES, type TaskItem, type TaskShapeValue } from "@/lib/api";

// Shared between the Tasks list page's "+ New Task" and the chat page's
// "Start a Task" trigger, so the two entry points can never end up with
// different validation/creation logic.
export function TaskCreateModal({
  token,
  open,
  onClose,
  onCreated,
  sessionId,
}: {
  token: string;
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskItem) => void;
  // Item 46: only the chat entry point has a real session to attribute -
  // the bare Tasks list's "+ New Task" has none, and omitting it there is
  // correct, not a gap (see Task.originating_session_id's own comment).
  sessionId?: string;
}) {
  const toast = useToast();
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [taskShape, setTaskShape] = useState<TaskShapeValue>(TASK_SHAPES[0].value);

  const reset = () => {
    setGoal("");
    setTaskShape(TASK_SHAPES[0].value);
  };

  const createMut = useMutation({
    mutationFn: () => createTask(token, { goal, task_shape: taskShape, originating_session_id: sessionId }),
    onSuccess: (task) => {
      toast.push("Plan generated — review it before approving.", "success");
      reset();
      onClose();
      onCreated(task);
    },
    onError: (err: unknown) => {
      // Wunomo Projects Phase 2 frontend, slice 9: a 402 detail is a dict
      // ({"error": "quota_exceeded"|"agent_budget_exceeded", ...}), not a
      // string -- ApiError's own constructor collapses that to the literal
      // "Request failed", so err.message alone used to show that exact
      // unhelpful string for the most common real-world denial.
      if (err instanceof ApiError && err.status === 402 && err.detail && typeof err.detail === "object") {
        const detail = err.detail as { error?: string; agent_id?: string; used?: number; limit?: number };
        if (detail.error === "quota_exceeded") {
          toast.push("Your workspace's AI-credit quota is exhausted for this billing period.", "danger", {
            label: "Go to Billing", onClick: () => router.push("/billing"),
          });
          return;
        }
        if (detail.error === "agent_budget_exceeded") {
          const usage = detail.used != null && detail.limit != null ? ` (${detail.used}/${detail.limit} tokens)` : "";
          toast.push(`This agent's own monthly token budget${usage} is exhausted.`, "danger", {
            label: "Go to agent", onClick: () => { if (detail.agent_id) router.push(`/agents/${detail.agent_id}`); },
          });
          return;
        }
      }
      const detail = err instanceof Error ? err.message : "Failed to generate a plan.";
      toast.push(detail, "danger");
    },
  });

  return (
    <Modal
      open={open}
      onClose={() => { reset(); onClose(); }}
      title="Start a Task"
      footer={
        <>
          <Button variant="secondary" onClick={() => { reset(); onClose(); }}>Cancel</Button>
          <Button disabled={!goal.trim() || createMut.isPending} onClick={() => createMut.mutate()}>
            {createMut.isPending ? "Generating plan…" : "Generate Plan"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="input-group">
          <label className="input-label" htmlFor="task-goal">What should AXIOM do?</label>
          <textarea
            id="task-goal"
            className="input"
            style={{ width: "100%", minHeight: 80, resize: "vertical" }}
            placeholder="e.g. Figure out why the nightly sales pipeline has been failing"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <span className="input-hint">
            AXIOM will generate a real, reviewable multi-step plan — nothing runs until you approve it.
          </span>
        </div>
        <Select
          id="task-shape" label="Task type" value={taskShape}
          onChange={(e) => setTaskShape(e.target.value as TaskShapeValue)}
        >
          {TASK_SHAPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
      </div>
    </Modal>
  );
}
