"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Badge, Modal, Input, Select,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getSources, createSource, deleteSource, syncSource, profileSource,
  uploadAndRegisterSource, testSourceConnection, type DataSourceItem, type ConnectionTestResult,
} from "@/lib/api";

// "structured" types (postgres/mysql) get real per-field inputs and a real
// Test Connection check (slice 5) -- the only two types where a wrong
// credential or Hard Rule 4's localhost trap is both likely and expensive
// to discover later. api_rest/google_sheets keep the raw JSON textarea;
// testing those is a known, explicit gap, not an assumed capability (see
// GOTCHAS.md).
const SOURCE_TYPES = [
  { value: "csv", label: "CSV file", placeholder: '{"file_path": "sales.csv"}', upload: true, structured: false, accept: ".csv", defaultPort: "" },
  { value: "excel", label: "Excel file", placeholder: '{"file_path": "report.xlsx"}', upload: true, structured: false, accept: ".xlsx,.xls", defaultPort: "" },
  { value: "postgres", label: "Postgres", placeholder: "{}", upload: false, structured: true, accept: "", defaultPort: "5432" },
  { value: "mysql", label: "MySQL", placeholder: "{}", upload: false, structured: true, accept: "", defaultPort: "3306" },
  { value: "api_rest", label: "REST API", placeholder: '{"url": "https://api.example.com/data"}', upload: false, structured: false, accept: "", defaultPort: "" },
  { value: "google_sheets", label: "Google Sheets", placeholder: '{"sheet_id": "..."}', upload: false, structured: false, accept: "", defaultPort: "" },
];

const EMPTY_DB_FIELDS = { host: "", port: "", database: "", user: "", password: "" };

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
  const [config, setConfig] = useState(SOURCE_TYPES[0].placeholder ?? "{}");
  const [dbFields, setDbFields] = useState(EMPTY_DB_FIELDS);
  const [file, setFile] = useState<File | null>(null);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  const activeType = SOURCE_TYPES.find((t) => t.value === sourceType) ?? SOURCE_TYPES[0];
  const isUploadType = activeType.upload;
  const isStructuredType = activeType.structured;

  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["sources"] });

  const resetModal = () => {
    setModalOpen(false);
    setName("");
    setFile(null);
    setDbFields(EMPTY_DB_FIELDS);
    setTestResult(null);
  };

  const dbConnectionConfig = () => {
    const cfg: Record<string, unknown> = {
      host: dbFields.host.trim(), database: dbFields.database.trim(),
      user: dbFields.user.trim(), password: dbFields.password,
    };
    if (dbFields.port.trim()) cfg.port = Number(dbFields.port.trim());
    return cfg;
  };

  const setDbField = (field: keyof typeof EMPTY_DB_FIELDS) => (value: string) => {
    setDbFields((prev) => ({ ...prev, [field]: value }));
    setTestResult(null); // editing after a test invalidates whatever was just proven
  };

  const testMut = useMutation({
    mutationFn: () => testSourceConnection(token, { source_type: sourceType, connection_config: dbConnectionConfig() }),
    onSuccess: (result) => setTestResult(result),
    onError: () => setTestResult({ ok: false, message: "Could not reach the test-connection endpoint." }),
  });

  const createMut = useMutation({
    mutationFn: async () => {
      let result;
      if (isStructuredType) {
        result = await createSource(token, { name, source_type: sourceType, connection_config: dbConnectionConfig() });
      } else {
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(config);
        } catch {
          throw new Error("Connection config must be valid JSON");
        }
        result = await createSource(token, { name, source_type: sourceType, connection_config: parsed });
      }
      // register_source() (backend) reports a refusal as {"error": ...} on
      // a 200 response, not an HTTP error status -- a 200 alone does not
      // mean the source was created. Found live: the app-database guard
      // refused a real test source, and this mutation still showed
      // "created" and closed the modal until this check was added.
      if (result.error) throw new Error(result.error);
      return result;
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
                      <div className="row-actions">
                        <Button
                          variant="ghost" icon title="Sync" aria-label={`Sync ${s.name}`}
                          disabled={syncMut.isPending} onClick={() => syncMut.mutate(s.id)}
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="23 4 23 10 17 10" />
                            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                          </svg>
                        </Button>
                        <Button
                          variant="ghost" icon title="Profile" aria-label={`Profile ${s.name}`}
                          disabled={profileMut.isPending} onClick={() => profileMut.mutate(s.id)}
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="11" cy="11" r="8" />
                            <path d="m21 21-4.35-4.35" />
                          </svg>
                        </Button>
                        <RowActionsMenu
                          actions={[
                            { label: "Delete", disabled: deleteMut.isPending, onClick: () => deleteMut.mutate(s.id) },
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
              <Button
                disabled={
                  !name || createMut.isPending ||
                  (isStructuredType && (!dbFields.host || !dbFields.database || !dbFields.user || !dbFields.password))
                }
                onClick={() => createMut.mutate()}
              >
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
              const nextType = SOURCE_TYPES.find((s) => s.value === t);
              setSourceType(t);
              setConfig(nextType?.placeholder || "{}");
              setFile(null);
              setDbFields({ ...EMPTY_DB_FIELDS, port: nextType?.defaultPort ?? "" });
              setTestResult(null);
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
          ) : isStructuredType ? (
            <>
              <Input id="source-name" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
              <Input
                id="source-host" label="Host" value={dbFields.host} onChange={(e) => setDbField("host")(e.target.value)}
                placeholder='"postgres" for a source in this same Docker stack, or a real hostname'
                hint='Never "localhost" -- inside Docker that means this backend container itself, not the database.'
                required
              />
              <div className="grid grid-2" style={{ gap: 12 }}>
                <Input
                  id="source-port" label="Port" value={dbFields.port} onChange={(e) => setDbField("port")(e.target.value)}
                  placeholder={activeType.defaultPort}
                />
                <Input
                  id="source-database" label="Database" value={dbFields.database}
                  onChange={(e) => setDbField("database")(e.target.value)} required
                />
              </div>
              <div className="grid grid-2" style={{ gap: 12 }}>
                <Input
                  id="source-user" label="User" value={dbFields.user} onChange={(e) => setDbField("user")(e.target.value)} required
                />
                <Input
                  id="source-password" label="Password" type="password" value={dbFields.password}
                  onChange={(e) => setDbField("password")(e.target.value)} required
                />
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="secondary" size="sm" disabled={!dbFields.host || !dbFields.database || testMut.isPending}
                  onClick={() => testMut.mutate()}
                >
                  {testMut.isPending ? "Testing…" : "Test Connection"}
                </Button>
                {testResult && (
                  <span className={testResult.ok ? "text-success text-sm" : "text-danger text-sm"}>
                    {testResult.ok
                      ? `Connected — ${testResult.tables_found} table${testResult.tables_found === 1 ? "" : "s"} found.`
                      : testResult.message}
                  </span>
                )}
              </div>
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
                <p className="text-muted text-xs" style={{ marginTop: 4 }}>
                  Not test-checked before saving today — only Postgres and MySQL connections are verified at
                  registration.
                </p>
              </div>
            </>
          )}
        </div>
      </Modal>
    </div>
  );
}
