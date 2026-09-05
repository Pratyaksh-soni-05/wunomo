"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  Button, Card, CardHeader, CardBody, CardFooter, Badge, Table, Thead, Tbody, Tr, Th, Td,
  Skeleton, Input, useToast,
} from "@/components/ui";
import {
  getToken, decodeUserFromToken, getTask, approveTaskPlan, rejectTaskPlan, editTaskSteps,
  advanceTask, resumeTask, rejectTaskStep, cancelTask,
  TASK_SHAPES, type TaskItem, type TaskStepItem, type TaskStepEditInput,
} from "@/lib/api";
import {
  taskStatusVariant, taskStatusLabel, taskReasonText, stepStatusVariant,
  provenanceVariant, provenanceLabel, TERMINAL_TASK_STATUSES,
} from "@/components/tasks/taskDisplay";

const ACTIVE_POLL_MS = 4000;
const AUTO_ADVANCE_DELAY_MS = 600;
const AUTO_ADVANCE_MAX_STEPS = 50;

// Wunomo Projects Phase 2 frontend, slice 9: paused_source_locked was
// missing here even though the backend's own RUNNABLE_TASK_STATUSES
// (models/all_models.py) already includes it and the beat tick auto-
// retries it -- the manual "Advance" button was disappearing for a task
// that the system was actively retrying in the background.
const ADVANCEABLE_STATUSES = new Set(["queued", "running", "paused_quota_exceeded", "paused_source_locked"]);

function shapeLabel(shape: string): string {
  return TASK_SHAPES.find((s) => s.value === shape)?.label ?? shape;
}

function StepsTable({ steps, editing, onEditStep }: {
  steps: TaskStepItem[];
  editing: boolean;
  onEditStep?: (index: number, patch: Partial<TaskStepEditInput>) => void;
}) {
  const sorted = [...steps].sort((a, b) => a.step_index - b.step_index);
  return (
    <Table>
      <Thead>
        <Tr>
          <Th>#</Th>
          <Th>Step</Th>
          <Th>Tool call</Th>
          <Th>Origin</Th>
          <Th>Status</Th>
          <Th>Outcome</Th>
        </Tr>
      </Thead>
      <Tbody>
        {sorted.map((s, i) => (
          <Tr key={s.id}>
            <Td>{s.step_index}</Td>
            <Td style={{ maxWidth: 340 }}>
              {editing ? (
                <textarea
                  className="input" style={{ minHeight: 72, fontSize: 13, width: "100%", resize: "vertical" }}
                  value={s.description}
                  onChange={(e) => onEditStep?.(i, { description: e.target.value })}
                />
              ) : (
                <span className="text-sm">{s.description}</span>
              )}
              {s.depends_on_step_index !== null && (
                <div className="text-xs text-muted">depends on step {s.depends_on_step_index}</div>
              )}
            </Td>
            <Td style={{ maxWidth: 420 }}>
              {editing ? (
                <div className="flex flex-col gap-1">
                  <Input
                    value={s.tool_name}
                    onChange={(e) => onEditStep?.(i, { tool_name: e.target.value })}
                  />
                  <textarea
                    className="code-block" style={{ minHeight: 160, fontSize: 12, width: "100%", resize: "vertical" }}
                    spellCheck={false}
                    value={JSON.stringify(s.tool_args, null, 2)}
                    onChange={(e) => {
                      try {
                        onEditStep?.(i, { tool_args: JSON.parse(e.target.value || "{}") });
                      } catch {
                        // Leave the last-valid tool_args in place until the JSON is valid again.
                      }
                    }}
                  />
                </div>
              ) : (
                <div>
                  <div className="text-sm font-mono">{s.tool_name}</div>
                  <div className="code-block" style={{ fontSize: 11, marginTop: 4, whiteSpace: "pre-wrap" }}>
                    {JSON.stringify(s.tool_args, null, 2)}
                  </div>
                </div>
              )}
            </Td>
            <Td>
              <Badge variant={provenanceVariant(s.source)}>{provenanceLabel(s.source)}</Badge>
            </Td>
            <Td>
              <Badge variant={stepStatusVariant(s.status)}>{s.status.replace(/_/g, " ")}</Badge>
              {s.attempt_count > 0 && <div className="text-xs text-muted">attempt {s.attempt_count}</div>}
            </Td>
            <Td style={{ maxWidth: 260 }}>
              {s.error_message ? (
                <span className="text-xs" style={{ color: "var(--danger)" }}>{s.error_message}</span>
              ) : s.outcome_summary ? (
                <span className="text-xs text-muted">{s.outcome_summary}</span>
              ) : (
                <span className="text-xs text-muted">—</span>
              )}
            </Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

export default function TaskDetailPage() {
  const token = getToken() as string;
  const user = useMemo(() => decodeUserFromToken(token), [token]);
  const canManageApprovals = user?.role === "owner" || user?.role === "admin";
  const params = useParams();
  const taskId = params.id as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();

  const [editing, setEditing] = useState(false);
  const [editedSteps, setEditedSteps] = useState<TaskStepEditInput[] | null>(null);
  const [resolveNotes, setResolveNotes] = useState("");
  const [autoRunning, setAutoRunning] = useState(false);

  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => getTask(token, taskId),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && !TERMINAL_TASK_STATUSES.has(status) ? ACTIVE_POLL_MS : false;
    },
  });

  const task = taskQuery.data;
  const isCreator = !!task && !!user && task.user_id === user.sub;

  const invalidate = (updated?: TaskItem) => {
    if (updated) qc.setQueryData(["task", taskId], updated);
    qc.invalidateQueries({ queryKey: ["task", taskId] });
    qc.invalidateQueries({ queryKey: ["tasks"] });
    qc.invalidateQueries({ queryKey: ["task-counts"] });
  };

  const approveMut = useMutation({
    mutationFn: () => approveTaskPlan(token, taskId),
    onSuccess: (t) => { toast.push("Plan approved — queued for execution.", "success"); invalidate(t); },
    onError: () => toast.push("Failed to approve plan.", "danger"),
  });

  const rejectPlanMut = useMutation({
    mutationFn: () => rejectTaskPlan(token, taskId),
    onSuccess: (t) => { toast.push(t.message, "default"); invalidate(t); },
    onError: () => toast.push("Failed to reject plan.", "danger"),
  });

  const saveEditMut = useMutation({
    mutationFn: () => editTaskSteps(token, taskId, editedSteps!),
    onSuccess: (t) => {
      toast.push("Plan updated.", "success");
      setEditing(false);
      setEditedSteps(null);
      invalidate(t);
    },
    onError: () => toast.push("Failed to save plan edits.", "danger"),
  });

  const advanceMut = useMutation({
    mutationFn: () => advanceTask(token, taskId),
    onSuccess: (t) => invalidate(t),
    onError: () => toast.push("Failed to advance task.", "danger"),
  });

  const resumeMut = useMutation({
    mutationFn: () => resumeTask(token, taskId, resolveNotes),
    onSuccess: (t) => { toast.push("Step approved — resuming.", "success"); setResolveNotes(""); invalidate(t); },
    onError: () => toast.push("Failed to resume task.", "danger"),
  });

  const rejectStepMut = useMutation({
    mutationFn: () => rejectTaskStep(token, taskId, resolveNotes),
    onSuccess: (t) => { toast.push("Step rejected.", "default"); setResolveNotes(""); invalidate(t); },
    onError: () => toast.push("Failed to reject step.", "danger"),
  });

  const cancelMut = useMutation({
    mutationFn: () => cancelTask(token, taskId),
    onSuccess: (t) => { toast.push("Task cancelled.", "default"); invalidate(t); },
    onError: () => toast.push("Failed to cancel task.", "danger"),
  });

  const startEditing = () => {
    if (!task) return;
    setEditedSteps(task.steps.map((s) => ({
      description: s.description, tool_name: s.tool_name,
      tool_args: s.tool_args, depends_on_step_index: s.depends_on_step_index,
    })));
    setEditing(true);
  };

  const runToCompletion = async () => {
    setAutoRunning(true);
    try {
      for (let i = 0; i < AUTO_ADVANCE_MAX_STEPS; i++) {
        const result = await advanceTask(token, taskId);
        invalidate(result);
        if (TERMINAL_TASK_STATUSES.has(result.status) || !ADVANCEABLE_STATUSES.has(result.status)) break;
        await new Promise((r) => setTimeout(r, AUTO_ADVANCE_DELAY_MS));
      }
    } catch {
      toast.push("Stopped — advance failed.", "danger");
    } finally {
      setAutoRunning(false);
    }
  };

  if (taskQuery.isError) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Task</h1></div>
        <div style={{ padding: "20px 24px" }}>
          <div className="empty-state">
            <h2 className="font-display text-xl">Can&apos;t open this task</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              It may not exist, or you may not have permission to view it — only the task&apos;s
              creator or a manager (Owner/Admin) can.
            </p>
            <Button size="sm" onClick={() => router.push("/tasks")}>← Back to Tasks</Button>
          </div>
        </div>
      </div>
    );
  }

  if (taskQuery.isLoading || !task) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Task</h1></div>
        <div style={{ padding: "20px 24px" }}><Skeleton style={{ height: 300, borderRadius: 12 }} /></div>
      </div>
    );
  }

  const reason = taskReasonText(task);
  const canCancel = !TERMINAL_TASK_STATUSES.has(task.status) && task.status !== "draft_plan" && (isCreator || canManageApprovals);
  const canAdvance = isCreator && ADVANCEABLE_STATUSES.has(task.status);

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <button className="auth-link-btn text-sm" onClick={() => router.push("/tasks")}>← All tasks</button>
            <h1 className="page-title" style={{ marginTop: 4 }}>{task.goal}</h1>
            <div className="flex items-center gap-2" style={{ marginTop: 6 }}>
              <Badge variant={taskStatusVariant(task.status)}>{taskStatusLabel(task.status)}</Badge>
              <span className="text-xs text-muted">{shapeLabel(task.task_shape)}</span>
              {task.plan_edited && <Badge variant="warning">Plan edited</Badge>}
              <span className="text-xs text-muted">
                {task.step_budget_used}/{task.step_budget_max} steps used
              </span>
              <span className="text-xs text-muted">
                · {task.cost.credits.toLocaleString()} AI Credits
              </span>
              {task.originating_session_id && (
                <button
                  className="auth-link-btn text-xs"
                  onClick={() => router.push(`/chat?session=${task.originating_session_id}`)}
                >
                  ← Back to conversation
                </button>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            {canAdvance && (
              <>
                <Button size="sm" variant="secondary" disabled={advanceMut.isPending || autoRunning} onClick={() => advanceMut.mutate()}>
                  {advanceMut.isPending ? "Advancing…" : "Advance one step"}
                </Button>
                <Button size="sm" disabled={advanceMut.isPending || autoRunning} onClick={runToCompletion}>
                  {autoRunning ? "Running…" : "Run to completion"}
                </Button>
              </>
            )}
            {canCancel && (
              <Button size="sm" variant="danger" disabled={cancelMut.isPending} onClick={() => cancelMut.mutate()}>
                Cancel Task
              </Button>
            )}
          </div>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {reason && (
          <Card style={{ marginBottom: 16, borderLeft: `3px solid var(--${reason.variant === "gray" ? "border" : reason.variant})` }}>
            <CardBody className={task.scope_denial ? "flex items-center justify-between" : undefined}>
              <div className="text-sm">{reason.text}</div>
              {/* Wunomo Projects Phase 2 frontend, slice 9: a real,
                  pre-scoped link, role-gated the same way the chat
                  version is -- the grant endpoint is Owner/Admin only
                  server-side, so a button someone can't use is worse
                  than none (explicit requirement). */}
              {task.scope_denial && (
                user?.role && ["owner", "admin"].includes(user.role.toLowerCase()) ? (
                  <Button
                    size="sm"
                    onClick={() => router.push(`/agents/${task.scope_denial!.agent_id}?highlight_source=${task.scope_denial!.source_id}`)}
                  >
                    Grant access
                  </Button>
                ) : (
                  <span className="text-xs text-muted">An Owner or Admin needs to grant this.</span>
                )
              )}
            </CardBody>
          </Card>
        )}

        {task.status === "draft_plan" ? (
          <Card>
            <CardHeader className="flex items-center justify-between">
              <span className="font-medium text-sm">Review the plan before approving</span>
              {isCreator && (
                <div className="flex gap-2">
                  {editing ? (
                    <>
                      <Button size="sm" variant="secondary" onClick={() => { setEditing(false); setEditedSteps(null); }}>
                        Discard edits
                      </Button>
                      <Button size="sm" disabled={saveEditMut.isPending} onClick={() => saveEditMut.mutate()}>
                        {saveEditMut.isPending ? "Saving…" : "Save Changes"}
                      </Button>
                    </>
                  ) : (
                    <Button size="sm" variant="secondary" onClick={startEditing}>Edit Plan</Button>
                  )}
                </div>
              )}
            </CardHeader>
            <StepsTable
              steps={editing && editedSteps
                ? editedSteps.map((s, i) => ({
                    id: task.steps[i]?.id ?? `new-${i}`, step_index: i, ...s,
                    status: "pending" as const, attempt_count: 0, error_message: null,
                    outcome_summary: null, approval_request_id: null,
                    source: task.steps[i]?.source ?? "human_edited",
                  }))
                : task.steps}
              editing={editing}
              onEditStep={(i, patch) => setEditedSteps((prev) => {
                if (!prev) return prev;
                const next = [...prev];
                next[i] = { ...next[i], ...patch };
                return next;
              })}
            />
            {isCreator && !editing && (
              <CardFooter className="flex gap-2 justify-end">
                <Button variant="danger" disabled={rejectPlanMut.isPending} onClick={() => rejectPlanMut.mutate()}>
                  Reject Plan
                </Button>
                <Button disabled={approveMut.isPending} onClick={() => approveMut.mutate()}>
                  {approveMut.isPending ? "Approving…" : "Approve Plan"}
                </Button>
              </CardFooter>
            )}
            {!isCreator && (
              <CardFooter>
                <span className="text-xs text-muted">Only the task&apos;s creator can edit, approve, or reject this plan.</span>
              </CardFooter>
            )}
          </Card>
        ) : (
          <>
            {task.status === "paused_needs_approval" && canManageApprovals && (
              <Card style={{ marginBottom: 16 }}>
                <CardHeader><span className="font-medium text-sm">Approve or reject this step</span></CardHeader>
                <CardBody className="flex flex-col gap-3">
                  <Input
                    placeholder="Optional notes"
                    value={resolveNotes}
                    onChange={(e) => setResolveNotes(e.target.value)}
                  />
                  <div className="flex gap-2 justify-end">
                    <Button variant="danger" disabled={rejectStepMut.isPending} onClick={() => rejectStepMut.mutate()}>
                      Reject Step
                    </Button>
                    <Button disabled={resumeMut.isPending} onClick={() => resumeMut.mutate()}>
                      {resumeMut.isPending ? "Resuming…" : "Approve & Resume"}
                    </Button>
                  </div>
                </CardBody>
              </Card>
            )}
            {task.status === "paused_needs_approval" && !canManageApprovals && (
              <p className="text-xs text-muted" style={{ marginBottom: 12 }}>
                This step needs approval from an Owner or Admin before the task can continue.
              </p>
            )}
            <Card style={{ marginBottom: 16 }}>
              <CardHeader><span className="font-medium text-sm">Cost</span></CardHeader>
              <CardBody>
                {task.cost.llm_calls === 0 ? (
                  <span className="text-sm text-muted">No LLM calls yet — nothing spent.</span>
                ) : (
                  <div className="flex items-center gap-4 flex-wrap">
                    <span className="text-sm">
                      <strong>{task.cost.credits.toLocaleString()}</strong> AI Credits
                    </span>
                    <span className="text-xs text-muted">{task.cost.llm_calls} LLM call{task.cost.llm_calls === 1 ? "" : "s"}</span>
                    <span className="text-xs text-muted">{task.cost.input_tokens.toLocaleString()} input tokens</span>
                    <span className="text-xs text-muted">{task.cost.output_tokens.toLocaleString()} output tokens</span>
                    {task.cost.reasoning_tokens > 0 && (
                      <span className="text-xs text-muted">{task.cost.reasoning_tokens.toLocaleString()} reasoning tokens</span>
                    )}
                  </div>
                )}
              </CardBody>
            </Card>
            <Card>
              <CardHeader><span className="font-medium text-sm">Step timeline</span></CardHeader>
              <StepsTable steps={task.steps} editing={false} />
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
