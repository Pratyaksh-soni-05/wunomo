"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, Badge, Button, Skeleton, useToast } from "@/components/ui";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import { timeAgo } from "@/lib/dates";
import { useNeedsYou, type NeedsYouItem } from "@/lib/needsYou";
import {
  getToken, resumeTask, rejectTaskStep, cancelTask,
  approveRequest, rejectRequest, approveCommit, rejectCommit,
  type TaskItem, type ActiveTaskRailItem, type MergedApproval,
} from "@/lib/api";

/**
 * Needs You (Wunomo UI-rebuild slice 9, 2026-09-15) -- the real screen
 * this route's rail label always implied: everything waiting on a human
 * decision across every project, one list, tier-sorted by real cost of
 * ignoring it (lib/needsYou.ts). Replaces the old flat "every pending
 * approval, uniform rows" page.
 *
 * Task-linked approvals (tier 0) resolve through the task's own
 * resume/reject-step endpoints, never the generic approve/reject ones --
 * findings item 98 documents why: the generic path executes the action
 * but never touches the Task row, leaving it stuck in
 * PAUSED_NEEDS_APPROVAL forever even though the approval itself
 * resolved. useNeedsYou's own dedup means a task-linked approval only
 * ever renders as a task row here, so this isn't a choice made per-row --
 * a MergedApproval only reaches this page's rendering at all once it's
 * confirmed standalone.
 */
function contextLine(item: NeedsYouItem): string {
  if (item.kind === "task") {
    const t = item.task;
    const when = timeAgo(t.paused_at ?? t.updated_at ?? t.created_at);
    return [t.project_name ?? "No project", t.agent_name ?? "Unassigned", when].join(" · ");
  }
  const a = item.approval;
  const sourceLabel = a.source === "cicd_deployment" ? "CI/CD Deployment" : "Agent Action";
  return `${sourceLabel} · ${timeAgo(a.created_at)}`;
}

function pillLabel(item: NeedsYouItem): string {
  if (item.kind === "approval") return "approval";
  return item.tier === 0 ? "approval" : item.tier === 2 ? "blocked" : "draft";
}

function pillVariant(item: NeedsYouItem): "warning" | "danger" | "gray" {
  if (item.kind === "approval") return "warning";
  if (item.tier === 2) return "danger";
  if (item.tier === 3) return "gray";
  return "warning";
}

function reasonText(task: ActiveTaskRailItem): string | null {
  return task.pause_reason ?? task.plan_invalid_reason ?? task.action_text;
}

export default function NeedsYouPage() {
  const token = getToken() as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [taskModalOpen, setTaskModalOpen] = useState(false);

  const needsYou = useNeedsYou(token);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["active-tasks"] });
    qc.invalidateQueries({ queryKey: ["merged-approvals"] });
  };

  const resumeMut = useMutation({
    mutationFn: (id: string) => resumeTask(token, id),
    onSuccess: () => { toast.push("Approved — resuming.", "success"); invalidate(); },
    onError: () => toast.push("Failed to approve.", "danger"),
  });
  const rejectStepMut = useMutation({
    mutationFn: (id: string) => rejectTaskStep(token, id),
    onSuccess: () => { toast.push("Rejected.", "default"); invalidate(); },
    onError: () => toast.push("Failed to reject.", "danger"),
  });
  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelTask(token, id),
    onSuccess: () => { toast.push("Discarded.", "default"); invalidate(); },
    onError: () => toast.push("Failed to discard.", "danger"),
  });
  const approveApprovalMut = useMutation({
    mutationFn: (item: MergedApproval) =>
      item.source === "cicd_deployment" ? approveCommit(token, item.id) : approveRequest(token, item.id),
    onSuccess: () => { toast.push("Approved.", "success"); invalidate(); },
    onError: () => toast.push("Failed to approve.", "danger"),
  });
  const rejectApprovalMut = useMutation({
    mutationFn: (item: MergedApproval) =>
      item.source === "cicd_deployment" ? rejectCommit(token, item.id) : rejectRequest(token, item.id),
    onSuccess: () => { toast.push("Rejected.", "default"); invalidate(); },
    onError: () => toast.push("Failed to reject.", "danger"),
  });

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Needs You</h1>
          {!needsYou.loading && needsYou.count > 0 && (
            <span className="text-muted text-sm">{needsYou.count} item{needsYou.count === 1 ? "" : "s"}</span>
          )}
        </div>
      </div>

      <div style={{ padding: "20px 24px", maxWidth: 720 }}>
        {needsYou.loading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : needsYou.count === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">Nothing needs you right now</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              Approvals, blocked tasks, and anything paused waiting on a decision — across every
              project — will show up here.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {needsYou.items.map((item) => {
              const key = item.kind === "task" ? `task-${item.task.id}` : `approval-${item.approval.id}`;

              if (item.kind === "task" && item.tier === 0) {
                const t = item.task;
                return (
                  <Card key={key} style={{ padding: 16 }}>
                    <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
                      <Badge variant={pillVariant(item)}>{pillLabel(item)}</Badge>
                      <span className="text-muted text-xs">{contextLine(item)}</span>
                    </div>
                    <div className="text-sm" style={{ marginBottom: 3 }}>{t.goal}</div>
                    {t.action_text && <p className="text-muted text-xs" style={{ margin: "0 0 11px" }}>{t.action_text}</p>}
                    <div className="flex gap-2">
                      <Button size="sm" disabled={resumeMut.isPending} onClick={() => resumeMut.mutate(t.id)}>Approve</Button>
                      <Button size="sm" variant="secondary" disabled={rejectStepMut.isPending} onClick={() => rejectStepMut.mutate(t.id)}>Reject</Button>
                      <Button size="sm" variant="ghost" onClick={() => router.push(`/tasks/${t.id}`)}>Open task</Button>
                    </div>
                  </Card>
                );
              }

              if (item.kind === "approval") {
                const a = item.approval;
                return (
                  <Card key={key} style={{ padding: 16 }}>
                    <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
                      <Badge variant={pillVariant(item)}>{pillLabel(item)}</Badge>
                      <span className="text-muted text-xs">{contextLine(item)}</span>
                    </div>
                    <div className="text-sm" style={{ marginBottom: 3 }}>{a.title}</div>
                    <p className="text-muted text-xs" style={{ margin: "0 0 11px" }}>
                      {a.description} · <Badge variant={a.risk_level === "high" ? "danger" : a.risk_level === "medium" ? "warning" : "success"}>{a.risk_level} risk</Badge>
                    </p>
                    <div className="flex gap-2">
                      <Button size="sm" disabled={approveApprovalMut.isPending} onClick={() => approveApprovalMut.mutate(a)}>Approve</Button>
                      <Button size="sm" variant="secondary" disabled={rejectApprovalMut.isPending} onClick={() => rejectApprovalMut.mutate(a)}>Reject</Button>
                    </div>
                  </Card>
                );
              }

              // tier 2 (blocked, dead) and tier 3 (draft plan)
              const t = (item as Extract<NeedsYouItem, { kind: "task" }>).task;
              const isDraft = item.tier === 3;
              return (
                <Card key={key} style={{ padding: 16 }}>
                  <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
                    <Badge variant={pillVariant(item)}>{pillLabel(item)}</Badge>
                    <span className="text-muted text-xs">{contextLine(item)}</span>
                  </div>
                  <div className="text-sm" style={{ marginBottom: 3 }}>{t.goal}</div>
                  <p className="text-muted text-xs" style={{ margin: "0 0 11px" }}>{reasonText(t)}</p>
                  {isDraft ? (
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => router.push(`/tasks/${t.id}`)}>Review Plan</Button>
                      <Button size="sm" variant="secondary" disabled={cancelMut.isPending} onClick={() => cancelMut.mutate(t.id)}>Discard</Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button size="sm" variant="secondary" onClick={() => router.push(`/tasks/${t.id}`)}>Open task</Button>
                      <Button size="sm" onClick={() => setTaskModalOpen(true)}>Start a new task</Button>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </div>

      <TaskCreateModal
        token={token}
        open={taskModalOpen}
        onClose={() => setTaskModalOpen(false)}
        onCreated={(task: TaskItem) => {
          setTaskModalOpen(false);
          toast.push(`Task "${task.goal}" created.`, "success");
          router.push(`/tasks/${task.id}`);
        }}
      />
    </div>
  );
}
