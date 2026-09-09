"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Modal, Button, Select, useToast } from "@/components/ui";
import {
  createTask, listSelectableAgents, ApiError, TASK_SHAPES,
  type TaskItem, type TaskShapeValue,
} from "@/lib/api";

// A picker option's scope summary -- names ("Sales Orders, Marketing
// Data") for a short list, a bare count for a long one, and an explicit
// "no sources" rather than a blank that could read as still loading.
// Showing this at the moment of choice is the whole point (explicit
// requirement): picking the wrong agent here is a scope denial that
// permanently kills the task (finding 76), not something to discover
// after the fact.
function scopeSummary(sources: { id: string; name: string }[]): string {
  if (sources.length === 0) return "no sources";
  if (sources.length <= 2) return sources.map((s) => s.name).join(", ");
  return `${sources.length} sources`;
}

// Shared between the Tasks list page's "+ New Task" and the chat page's
// "Start a Task" trigger, so the two entry points can never end up with
// different validation/creation logic.
export function TaskCreateModal({
  token,
  open,
  onClose,
  onCreated,
  sessionId,
  channelAgentIds,
}: {
  token: string;
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskItem) => void;
  // Item 46: only the chat entry point has a real session to attribute -
  // the bare Tasks list's "+ New Task" has none, and omitting it there is
  // correct, not a gap (see Task.originating_session_id's own comment).
  sessionId?: string;
  // Wunomo Projects Phase 4: this channel's own real member agent ids, if
  // opened from inside a channel -- narrows the picker to "this channel's
  // own team," matching the exact rule @mention routing already uses (a
  // solo member needs no disambiguation, several do). Omitted (bare
  // AXIOM chat, or the standalone Tasks list) shows every active agent.
  channelAgentIds?: string[];
}) {
  const toast = useToast();
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [taskShape, setTaskShape] = useState<TaskShapeValue>(TASK_SHAPES[0].value);
  const [manualAgentId, setManualAgentId] = useState<string | null>(null);

  const agentsQuery = useQuery({
    queryKey: ["selectable-agents"],
    queryFn: () => listSelectableAgents(token),
    enabled: open,
  });
  const allAgents = agentsQuery.data?.agents ?? [];
  // Already ordered oldest-first by the backend -- filtering to this
  // channel's own members (when there's channel context) and defaulting
  // to the first entry either way naturally reproduces "oldest active
  // agent" when nothing narrows it further, without two separate rules.
  const pickableAgents = channelAgentIds && channelAgentIds.length > 0
    ? allAgents.filter((a) => channelAgentIds.includes(a.id))
    : allAgents;
  const agentId = manualAgentId ?? pickableAgents[0]?.id ?? "";

  const reset = () => {
    setGoal("");
    setTaskShape(TASK_SHAPES[0].value);
    setManualAgentId(null);
  };

  const createMut = useMutation({
    mutationFn: () => createTask(token, {
      goal, task_shape: taskShape, originating_session_id: sessionId,
      agent_id: agentId || undefined,
    }),
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
          <Button disabled={!goal.trim() || !agentId || createMut.isPending} onClick={() => createMut.mutate()}>
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
        <Select
          id="task-agent" label="Agent" value={agentId}
          disabled={agentsQuery.isLoading || pickableAgents.length === 0}
          onChange={(e) => setManualAgentId(e.target.value)}
          hint="Who actually does the work — not just who you're talking to. A wrong pick here means a scope denial that can't be undone once it happens, only avoided."
        >
          {pickableAgents.length === 0 && <option value="">No active agents available</option>}
          {pickableAgents.map((a) => (
            <option key={a.id} value={a.id}>{a.name} — {scopeSummary(a.sources)}</option>
          ))}
        </Select>
      </div>
    </Modal>
  );
}
