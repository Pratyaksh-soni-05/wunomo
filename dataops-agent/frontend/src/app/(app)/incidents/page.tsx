"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Badge, Modal, Input, Select,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getIncidents, createIncident, resolveIncident, getPipelines,
  type Incident,
} from "@/lib/api";

const SEVERITIES = ["low", "medium", "high", "critical"];

// Mirrors the backend's own default (backend/api/v1/incidents.py:list_incidents,
// `limit: int = 50`) - not fetched from anywhere, since the API exposes no
// endpoint to ask "what's your current default." getIncidents() never
// passes a limit, so this is what actually comes back. The API's own
// `count` field always equals len(returned) (finding 55, backend), so it
// can never be trusted to mean "how many exist" - this screen doesn't read
// it at all. If the returned page is exactly this size, more rows may
// exist that this screen has no way to fetch (no offset/cursor param
// exists yet) - say that plainly instead of pretending 50 is everything.
const INCIDENTS_DEFAULT_LIMIT = 50;

function severityVariant(sev: string): "success" | "warning" | "danger" | "gray" {
  switch (sev) {
    case "critical": case "high": return "danger";
    case "medium": return "warning";
    default: return "gray";
  }
}

function statusVariant(status: string): "danger" | "warning" | "success" | "gray" {
  switch (status) {
    case "open": return "danger";
    case "investigating": return "warning";
    case "resolved": return "success";
    default: return "gray";
  }
}

export default function IncidentsPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [pipelineId, setPipelineId] = useState("");
  const [resolutionNotes, setResolutionNotes] = useState("");

  // This screen needs the full history (it renders a Resolve button
  // conditionally per row, including already-resolved ones) - genuinely
  // different data from the Dashboard's open-only health banner query, not
  // a duplicate of it (finding 21). Unfiltered on purpose.
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: () => getIncidents(token) });
  const pipelines = useQuery({ queryKey: ["pipelines"], queryFn: () => getPipelines(token) });

  // Resolving/logging an incident here changes what the Dashboard's
  // open-incidents query should return too - invalidate both, not just
  // this screen's own key.
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["open-incidents"] });
  };

  const createMut = useMutation({
    mutationFn: () => createIncident(token, {
      title, description: description || undefined, severity, pipeline_id: pipelineId || undefined,
    }),
    onSuccess: () => {
      toast.push(`Incident "${title}" logged.`, "success");
      setModalOpen(false);
      setTitle(""); setDescription(""); setPipelineId("");
      invalidate();
    },
    onError: () => toast.push("Failed to create incident.", "danger"),
  });

  const resolveMut = useMutation({
    mutationFn: () => resolveIncident(token, resolvingId as string, resolutionNotes),
    onSuccess: () => {
      toast.push("Incident resolved.", "success");
      setResolvingId(null);
      setResolutionNotes("");
      invalidate();
    },
    onError: () => toast.push("Failed to resolve incident.", "danger"),
  });

  const list = incidents.data?.incidents ?? [];
  const pipelineList = pipelines.data?.pipelines ?? [];
  const pipelineName = (id: string | null) => pipelineList.find((p) => p.id === id)?.name || (id ? id : "—");

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Incidents</h1>
          <Button size="sm" onClick={() => setModalOpen(true)}>+ Log Incident</Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {incidents.isLoading ? (
          <Skeleton style={{ height: 300, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No incidents</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              Nothing&apos;s on fire. Incidents raised by AXIOM or logged manually will show up here.
            </p>
            <Button size="sm" onClick={() => setModalOpen(true)}>+ Log Incident</Button>
          </div>
        ) : (
          <Card>
            <p className="text-muted text-sm" style={{ padding: "14px 16px 0" }}>
              {list.length >= INCIDENTS_DEFAULT_LIMIT
                ? `Showing the ${list.length} most recent incidents. There may be more — this screen can't yet page past this limit or show a true total.`
                : `Showing all ${list.length} incident${list.length === 1 ? "" : "s"}.`}
            </p>
            <Table>
              <Thead>
                <Tr>
                  <Th>Title</Th>
                  <Th>Severity</Th>
                  <Th>Status</Th>
                  <Th>Pipeline</Th>
                  <Th>Detected</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((i: Incident) => (
                  <Tr key={i.id}>
                    <Td>{i.title}</Td>
                    <Td><Badge variant={severityVariant(i.severity)}>{i.severity}</Badge></Td>
                    <Td><Badge variant={statusVariant(i.status)}>{i.status}</Badge></Td>
                    <Td>{pipelineName(i.pipeline_id)}</Td>
                    <Td>{formatApiDate(i.detected_at)}</Td>
                    <Td>
                      {i.status !== "resolved" ? (
                        <div className="row-actions">
                          <Button
                            variant="ghost" icon title="Resolve" aria-label={`Resolve ${i.title}`}
                            onClick={() => setResolvingId(i.id)}
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          </Button>
                        </div>
                      ) : (
                        <span className="text-muted text-sm">—</span>
                      )}
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
        title="Log Incident"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button disabled={!title || createMut.isPending} onClick={() => createMut.mutate()}>
              {createMut.isPending ? "Logging..." : "Log Incident"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input id="incident-title" label="Title" value={title} onChange={(e) => setTitle(e.target.value)} required />
          <Input id="incident-desc" label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
          <Select id="incident-severity" label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Select id="incident-pipeline" label="Pipeline (optional)" value={pipelineId} onChange={(e) => setPipelineId(e.target.value)}>
            <option value="">None</option>
            {pipelineList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </div>
      </Modal>

      <Modal
        open={!!resolvingId}
        onClose={() => setResolvingId(null)}
        title="Resolve Incident"
        footer={
          <>
            <Button variant="secondary" onClick={() => setResolvingId(null)}>Cancel</Button>
            <Button variant="success" disabled={!resolutionNotes || resolveMut.isPending} onClick={() => resolveMut.mutate()}>
              {resolveMut.isPending ? "Resolving..." : "Mark Resolved"}
            </Button>
          </>
        }
      >
        <Input
          id="resolution-notes" label="Resolution notes" required
          value={resolutionNotes} onChange={(e) => setResolutionNotes(e.target.value)}
        />
      </Modal>
    </div>
  );
}
