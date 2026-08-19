"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Badge, Modal, Input, Select,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getPipelines, createPipeline, deletePipeline, triggerPipelineRun,
  pausePipeline, activatePipeline, getPipelineRuns, getSources,
  type PipelineItem, type PipelineRunItem,
} from "@/lib/api";

function statusVariant(status: string): "success" | "warning" | "gray" | "info" {
  switch (status) {
    case "active": return "success";
    case "paused": return "warning";
    case "archived": return "gray";
    default: return "info"; // draft
  }
}

function runStatusVariant(status: string): "success" | "danger" | "warning" | "info" | "gray" {
  switch (status) {
    case "success": return "success";
    case "failed": return "danger";
    case "running": return "info";
    case "retrying": return "warning";
    default: return "gray";
  }
}

export default function PipelinesPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [runsFor, setRunsFor] = useState<PipelineItem | null>(null);
  const [name, setName] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [description, setDescription] = useState("");
  const [scheduleCron, setScheduleCron] = useState("");

  const pipelines = useQuery({ queryKey: ["pipelines"], queryFn: () => getPipelines(token) });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });
  const runs = useQuery({
    queryKey: ["pipeline-runs", runsFor?.id],
    queryFn: () => getPipelineRuns(token, runsFor!.id),
    enabled: !!runsFor,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["pipelines"] });

  const createMut = useMutation({
    mutationFn: () => createPipeline(token, {
      name, source_id: sourceId || undefined, description: description || undefined,
      schedule_cron: scheduleCron || undefined,
    }),
    onSuccess: () => {
      toast.push(`Pipeline "${name}" created.`, "success");
      setModalOpen(false);
      setName(""); setSourceId(""); setDescription(""); setScheduleCron("");
      invalidate();
    },
    onError: () => toast.push("Failed to create pipeline.", "danger"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePipeline(token, id),
    onSuccess: () => { toast.push("Pipeline deleted.", "default"); invalidate(); },
    onError: () => toast.push("Failed to delete pipeline.", "danger"),
  });

  const triggerMut = useMutation({
    mutationFn: (id: string) => triggerPipelineRun(token, id),
    onSuccess: () => { toast.push("Run triggered.", "success"); invalidate(); },
    onError: () => toast.push("Failed to trigger run.", "danger"),
  });

  const pauseMut = useMutation({
    mutationFn: (id: string) => pausePipeline(token, id),
    onSuccess: () => { toast.push("Pipeline paused.", "default"); invalidate(); },
    onError: () => toast.push("Failed to pause pipeline.", "danger"),
  });

  const activateMut = useMutation({
    mutationFn: (id: string) => activatePipeline(token, id),
    onSuccess: () => { toast.push("Pipeline activated.", "success"); invalidate(); },
    onError: () => toast.push("Failed to activate pipeline.", "danger"),
  });

  const list = pipelines.data?.pipelines ?? [];
  const sourceList = sources.data?.sources ?? [];
  const sourceName = (id: string | null) => sourceList.find((s) => s.id === id)?.name || "—";

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Pipelines</h1>
          <Button size="sm" onClick={() => setModalOpen(true)}>+ New Pipeline</Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {pipelines.isLoading ? (
          <Skeleton style={{ height: 300, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No pipelines yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              Create a pipeline to sync a source and run quality checks on a schedule.
            </p>
            <Button size="sm" onClick={() => setModalOpen(true)}>+ New Pipeline</Button>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Name</Th>
                  <Th>Status</Th>
                  <Th>Source</Th>
                  <Th>Schedule</Th>
                  <Th>Next / Last Run</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((p: PipelineItem) => (
                  <Tr key={p.id}>
                    <Td>
                      <button className="auth-link-btn" onClick={() => setRunsFor(p)}>{p.name}</button>
                    </Td>
                    <Td><Badge variant={statusVariant(p.status)}>{p.status}</Badge></Td>
                    <Td>{sourceName(p.source_id)}</Td>
                    <Td>{p.schedule_cron || "Manual"}</Td>
                    <Td>
                      <div className="flex flex-col gap-1" style={{ fontSize: 12 }}>
                        {p.next_run_at ? (
                          <span className="text-muted">Next: {formatApiDate(p.next_run_at)}</span>
                        ) : p.schedule_cron ? (
                          <span className="text-muted">Not scheduled (paused)</span>
                        ) : null}
                        {p.last_run ? (
                          <span className="flex items-center gap-1">
                            Last:
                            <Badge variant={runStatusVariant(p.last_run.status)}>{p.last_run.status}</Badge>
                            <span className="text-muted">{formatApiDate(p.last_run.created_at)}</span>
                          </span>
                        ) : (
                          <span className="text-muted">Never run</span>
                        )}
                      </div>
                    </Td>
                    <Td>
                      <div className="row-actions">
                        <Button
                          variant="ghost" icon title="Trigger" aria-label={`Trigger ${p.name}`}
                          disabled={triggerMut.isPending} onClick={() => triggerMut.mutate(p.id)}
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                            <polygon points="5 3 19 12 5 21 5 3" />
                          </svg>
                        </Button>
                        {p.status === "paused" ? (
                          <Button
                            variant="ghost" icon title="Activate" aria-label={`Activate ${p.name}`}
                            disabled={activateMut.isPending} onClick={() => activateMut.mutate(p.id)}
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          </Button>
                        ) : (
                          <Button
                            variant="ghost" icon title="Pause" aria-label={`Pause ${p.name}`}
                            disabled={pauseMut.isPending} onClick={() => pauseMut.mutate(p.id)}
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                              <rect x="6" y="4" width="4" height="16" rx="1" />
                              <rect x="14" y="4" width="4" height="16" rx="1" />
                            </svg>
                          </Button>
                        )}
                        <RowActionsMenu
                          actions={[
                            { label: "Delete", disabled: deleteMut.isPending, onClick: () => deleteMut.mutate(p.id) },
                          ]}
                        />
                      </div>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="New Pipeline"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button disabled={!name || createMut.isPending} onClick={() => createMut.mutate()}>
              {createMut.isPending ? "Creating..." : "Create"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input id="pipeline-name" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          <Select id="pipeline-source" label="Source" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">No source (manual)</option>
            {sourceList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
          <Input id="pipeline-desc" label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
          <Input
            id="pipeline-cron" label="Schedule (cron, optional)" placeholder="0 */6 * * *"
            value={scheduleCron} onChange={(e) => setScheduleCron(e.target.value)}
          />
        </div>
      </Modal>

      <Modal open={!!runsFor} onClose={() => setRunsFor(null)} title={runsFor ? `Runs — ${runsFor.name}` : ""} size="lg">
        {runs.isLoading ? (
          <Skeleton style={{ height: 120, borderRadius: 8 }} />
        ) : (runs.data?.runs ?? []).length === 0 ? (
          <p className="text-muted text-sm">No runs yet.</p>
        ) : (
          <Table>
            <Thead>
              <Tr><Th>Status</Th><Th>Rows</Th><Th>Duration</Th><Th>When</Th></Tr>
            </Thead>
            <Tbody>
              {(runs.data?.runs ?? []).map((r: PipelineRunItem) => (
                <Tr key={r.id}>
                  <Td><Badge variant={runStatusVariant(r.status)}>{r.status}</Badge></Td>
                  <Td>{r.rows_processed ?? "—"}</Td>
                  <Td>{r.duration_seconds != null ? `${r.duration_seconds}s` : "—"}</Td>
                  <Td>{formatApiDate(r.created_at)}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Modal>
    </div>
  );
}
