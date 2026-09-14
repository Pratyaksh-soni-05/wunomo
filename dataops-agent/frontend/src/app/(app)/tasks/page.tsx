"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Badge, Table, Thead, Tbody, Tr, Th, Td, Skeleton } from "@/components/ui";
import { getToken, getTasks, type TaskSummary } from "@/lib/api";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import { RerunButton } from "@/components/tasks/RerunButton";
import { taskStatusVariant, taskStatusLabel, shapeLabel } from "@/components/tasks/taskDisplay";
import { formatApiDate } from "@/lib/dates";

const TASK_COUNTS_POLL_MS = 20000;

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
                      {t.goal.length > 80 ? `${t.goal.slice(0, 80)}…` : t.goal}
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
