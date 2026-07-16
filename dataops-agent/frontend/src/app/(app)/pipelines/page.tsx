"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Badge, Modal, Input, Select,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
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
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" disabled={triggerMut.isPending} onClick={() => triggerMut.mutate(p.id)}>Trigger</Button>
                        {p.status === "paused" ? (
                          <Button size="sm" variant="secondary" disabled={activateMut.isPending} onClick={() => activateMut.mutate(p.id)}>Activate</Button>
                        ) : (
                          <Button size="sm" variant="secondary" disabled={pauseMut.isPending} onClick={() => pauseMut.mutate(p.id)}>Pause</Button>
                        )}
                        <Button size="sm" variant="danger" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate(p.id)}>Delete</Button>
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
                  <Td>{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Modal>
    </div>
  );
}
