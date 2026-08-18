"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Badge, Modal, Input, Select,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getSources, createSource, deleteSource, syncSource, profileSource,
  uploadAndRegisterSource, type DataSourceItem,
} from "@/lib/api";

const SOURCE_TYPES = [
  { value: "csv", label: "CSV file", placeholder: '{"file_path": "sales.csv"}', upload: true, accept: ".csv" },
  { value: "excel", label: "Excel file", placeholder: '{"file_path": "report.xlsx"}', upload: true, accept: ".xlsx,.xls" },
  { value: "postgres", label: "Postgres", placeholder: '{"host": "db.example.com", "port": 5432, "database": "app", "user": "reader", "password": "***"}', upload: false },
  { value: "mysql", label: "MySQL", placeholder: '{"host": "db.example.com", "port": 3306, "database": "app", "user": "reader", "password": "***"}', upload: false },
  { value: "api_rest", label: "REST API", placeholder: '{"url": "https://api.example.com/data"}', upload: false },
  { value: "google_sheets", label: "Google Sheets", placeholder: '{"sheet_id": "..."}', upload: false },
];

function statusBadge(active: boolean) {
  return active ? <Badge variant="success">Active</Badge> : <Badge variant="gray">Inactive</Badge>;
}

export default function SourcesPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("csv");
  const [config, setConfig] = useState(SOURCE_TYPES[0].placeholder);
  const [file, setFile] = useState<File | null>(null);

  const activeType = SOURCE_TYPES.find((t) => t.value === sourceType) ?? SOURCE_TYPES[0];
  const isUploadType = activeType.upload;

  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["sources"] });

  const resetModal = () => {
    setModalOpen(false);
    setName("");
    setFile(null);
  };

  const createMut = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(config);
      } catch {
        throw new Error("Connection config must be valid JSON");
      }
      return createSource(token, { name, source_type: sourceType, connection_config: parsed });
    },
    onSuccess: () => {
      toast.push(`Source "${name}" created.`, "success");
      resetModal();
      invalidate();
    },
    onError: (e: Error) => toast.push(e.message || "Failed to create source.", "danger"),
  });

  const uploadMut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a file to upload.");
      return uploadAndRegisterSource(token, file, name || undefined);
    },
    onSuccess: (result) => {
      toast.push(`Uploaded and registered "${result.filename}".`, "success");
      resetModal();
      invalidate();
    },
    onError: (e: Error) => toast.push(e.message || "Upload failed.", "danger"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSource(token, id),
    onSuccess: () => { toast.push("Source deleted.", "default"); invalidate(); },
    onError: () => toast.push("Failed to delete source.", "danger"),
  });

  const syncMut = useMutation({
    mutationFn: (id: string) => syncSource(token, id),
    onSuccess: () => { toast.push("Sync started.", "success"); invalidate(); },
    onError: () => toast.push("Sync failed.", "danger"),
  });

  const profileMut = useMutation({
    mutationFn: (id: string) => profileSource(token, id),
    onSuccess: () => { toast.push("Source profiled.", "success"); invalidate(); },
    onError: () => toast.push("Profiling failed.", "danger"),
  });

  const list = sources.data?.sources ?? [];

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Data Sources</h1>
          <Button size="sm" onClick={() => setModalOpen(true)}>+ Add Source</Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {sources.isLoading ? (
          <Skeleton style={{ height: 300, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No data sources yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              Connect a CSV, database, or API to start building pipelines.
            </p>
            <Button size="sm" onClick={() => setModalOpen(true)}>+ Add Source</Button>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Name</Th>
                  <Th>Type</Th>
                  <Th>Status</Th>
                  <Th>Owner</Th>
                  <Th>Last Profiled</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((s: DataSourceItem) => (
                  <Tr key={s.id}>
                    <Td>{s.name}</Td>
                    <Td><Badge variant="info">{s.source_type}</Badge></Td>
                    <Td>{statusBadge(s.is_active)}</Td>
                    <Td>{s.owner || "—"}</Td>
                    <Td>{formatApiDate(s.last_profiled_at, "Never")}</Td>
                    <Td>
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" disabled={syncMut.isPending} onClick={() => syncMut.mutate(s.id)}>Sync</Button>
                        <Button size="sm" variant="secondary" disabled={profileMut.isPending} onClick={() => profileMut.mutate(s.id)}>Profile</Button>
                        <Button size="sm" variant="danger" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate(s.id)}>Delete</Button>
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
        onClose={resetModal}
        title="Add Data Source"
        footer={
          <>
            <Button variant="secondary" onClick={resetModal}>Cancel</Button>
            {isUploadType ? (
              <Button disabled={!file || uploadMut.isPending} onClick={() => uploadMut.mutate()}>
                {uploadMut.isPending ? "Uploading..." : "Upload & Create"}
              </Button>
            ) : (
              <Button disabled={!name || createMut.isPending} onClick={() => createMut.mutate()}>
                {createMut.isPending ? "Creating..." : "Create"}
              </Button>
            )}
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Select
            id="source-type"
            label="Type"
            value={sourceType}
            onChange={(e) => {
              const t = e.target.value;
              setSourceType(t);
              setConfig(SOURCE_TYPES.find((s) => s.value === t)?.placeholder || "{}");
              setFile(null);
            }}
          >
            {SOURCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>

          {isUploadType ? (
            <>
              <div className="input-group">
                <label className="input-label" htmlFor="source-file">File</label>
                <input
                  id="source-file"
                  type="file"
                  className="input"
                  accept={activeType.accept}
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    setFile(f);
                    if (f && !name) setName(f.name);
                  }}
                />
                <p className="text-muted text-xs" style={{ marginTop: 4 }}>
                  {activeType.value === "csv" ? "CSV file" : "Excel file (.xlsx or .xls)"} — uploaded to the server and
                  registered as a data source in one step.
                </p>
              </div>
              <Input
                id="source-name"
                label="Name (optional — defaults to the filename)"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </>
          ) : (
            <>
              <Input id="source-name" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
              <div className="input-group">
                <label className="input-label" htmlFor="source-config">Connection config (JSON)</label>
                <textarea
                  id="source-config"
                  className="input"
                  rows={4}
                  value={config}
                  onChange={(e) => setConfig(e.target.value)}
                  style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
                />
              </div>
            </>
          )}
        </div>
      </Modal>
    </div>
  );
}
