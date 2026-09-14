"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Badge, Table, Thead, Tbody, Tr, Th, Td, Skeleton } from "@/components/ui";
import { getToken, getTasks, getProjectAgents, type TaskSummary } from "@/lib/api";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import { RerunButton } from "@/components/tasks/RerunButton";
import { taskStatusVariant, taskStatusLabel, shapeLabel } from "@/components/tasks/taskDisplay";
import { formatApiDate } from "@/lib/dates";

const TASK_COUNTS_POLL_MS = 20000;

// Real, not a stub (Wunomo UI-rebuild slice 5, 2026-09-14) -- pulled
// forward from what was originally slice 8's job, since it's built
// entirely from things that already exist: Task.agent_id (added to the
// list serializer in this same slice, it existed on the column already
// but the list endpoint never surfaced it) and this project's own agent
// set (getProjectAgents, already real). A project's tasks are exactly the
// tenant's tasks whose agent_id is one of this project's agents -- no
// project-scoped tasks endpoint exists, so this filters the same list the
// global Tasks page fetches, client-side.
export default function ProjectTasksTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const router = useRouter();
  const [modalOpen, setModalOpen] = useState(false);

  const agentsQuery = useQuery({
    queryKey: ["project-agents", projectId],
    queryFn: () => getProjectAgents(token, projectId),
  });
  const agentIds = new Set((agentsQuery.data?.agents ?? []).map((a) => a.id));

  const tasksQuery = useQuery({
    queryKey: ["tasks"],
    queryFn: () => getTasks(token),
    refetchInterval: TASK_COUNTS_POLL_MS,
  });
  const list = (tasksQuery.data ?? []).filter((t) => t.agent_id && agentIds.has(t.agent_id));

  const loading = agentsQuery.isLoading || tasksQuery.isLoading;

  return (
    <div style={{ padding: "20px 24px" }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
        <span className="text-muted text-sm">Tasks run by this project's agents.</span>
        <Button
          size="sm"
          disabled={agentIds.size === 0}
          title={agentIds.size === 0 ? "Hire an agent first" : undefined}
          onClick={() => setModalOpen(true)}
        >
          + New Task
        </Button>
      </div>

      {loading ? (
        <Skeleton style={{ height: 300, borderRadius: 12 }} />
      ) : list.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">No tasks yet</h2>
          <p className="text-muted text-sm" style={{ maxWidth: 420 }}>
            {agentIds.size === 0
              ? "Hire an agent for this project, then give it a goal to work from here."
              : "Give this project's agents a goal and they'll generate a real, reviewable multi-step plan — nothing runs until you approve it."}
          </p>
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
                  <Td>{t.goal.length > 80 ? `${t.goal.slice(0, 80)}…` : t.goal}</Td>
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

      <TaskCreateModal
        token={token}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        channelAgentIds={Array.from(agentIds)}
        onCreated={(task) => router.push(`/tasks/${task.id}`)}
      />
    </div>
  );
}
