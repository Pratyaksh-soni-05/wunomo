"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Modal, Button, Select, useToast } from "@/components/ui";
import { createTask, TASK_SHAPES, type TaskItem, type TaskShapeValue } from "@/lib/api";

// Shared between the Tasks list page's "+ New Task" and the chat page's
// "Start a Task" trigger, so the two entry points can never end up with
// different validation/creation logic.
export function TaskCreateModal({
  token,
  open,
  onClose,
  onCreated,
}: {
  token: string;
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskItem) => void;
}) {
  const toast = useToast();
  const [goal, setGoal] = useState("");
  const [taskShape, setTaskShape] = useState<TaskShapeValue>(TASK_SHAPES[0].value);

  const reset = () => {
    setGoal("");
    setTaskShape(TASK_SHAPES[0].value);
  };

  const createMut = useMutation({
    mutationFn: () => createTask(token, { goal, task_shape: taskShape }),
    onSuccess: (task) => {
      toast.push("Plan generated — review it before approving.", "success");
      reset();
      onClose();
      onCreated(task);
    },
    onError: (err: unknown) => {
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
