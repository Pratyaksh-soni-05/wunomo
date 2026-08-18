"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Badge, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast } from "@/components/ui";
import { getToken, getTasks, createTask, TASK_SHAPES, ApiError, type TaskSummary, type TaskShapeValue } from "@/lib/api";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import { taskStatusVariant, taskStatusLabel } from "@/components/tasks/taskDisplay";
import { formatApiDate } from "@/lib/dates";

const TASK_COUNTS_POLL_MS = 20000;

function shapeLabel(shape: string): string {
  return TASK_SHAPES.find((s) => s.value === shape)?.label ?? shape;
}

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

function RerunButton({ token, task }: { token: string; task: TaskSummary }) {
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

export default function TasksPage() {
  const token = getToken() as string;
  const router = useRouter();
  const [modalOpen, setModalOpen] = useState(false);

  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => getTasks(token),
    refetchInterval: TASK_COUNTS_POLL_MS,
  });

  const list = tasks.data ?? [];

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Tasks</h1>
          <Button size="sm" onClick={() => setModalOpen(true)}>+ New Task</Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {tasks.isLoading ? (
          <Skeleton style={{ height: 300, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No tasks yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 420 }}>
              Give AXIOM a goal and it will generate a real, reviewable multi-step plan — nothing
              runs until you approve it.
            </p>
            <Button size="sm" onClick={() => setModalOpen(true)}>+ New Task</Button>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Goal</Th>
                  <Th>Type</Th>
                  <Th>Status</Th>
                  <Th>Plan</Th>
                  <Th>Created</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((t: TaskSummary) => (
                  <Tr key={t.id} style={{ cursor: "pointer" }} onClick={() => router.push(`/tasks/${t.id}`)}>
                    <Td>
                      <button className="auth-link-btn" onClick={() => router.push(`/tasks/${t.id}`)}>
                        {t.goal.length > 80 ? `${t.goal.slice(0, 80)}…` : t.goal}
                      </button>
                    </Td>
                    <Td><span className="text-sm text-muted">{shapeLabel(t.task_shape)}</span></Td>
                    <Td><Badge variant={taskStatusVariant(t.status)}>{taskStatusLabel(t.status)}</Badge></Td>
                    <Td>{t.plan_edited ? <Badge variant="warning">Edited</Badge> : <span className="text-muted text-sm">Original</span>}</Td>
                    <Td><span className="text-sm text-muted">{formatApiDate(t.created_at)}</span></Td>
                    <Td><RerunButton token={token} task={t} /></Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}
      </div>

      <TaskCreateModal
        token={token}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(task) => router.push(`/tasks/${task.id}`)}
      />
    </div>
  );
}
