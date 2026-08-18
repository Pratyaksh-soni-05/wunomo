"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Badge, Button, Input, Select, Tabs, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast } from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getSources, getTransformRuns,
  generateSqlTransform, generatePandasTransform,
  runSqlTransform, dryRunSqlTransform, runPandasTransform, previewPandasTransform, explainCode,
  ApiError,
  type GenerateResult, type RunResult, type DryRunResult, type TransformRunItem,
} from "@/lib/api";

function errMsg(e: unknown): string {
  return e instanceof ApiError ? (typeof e.detail === "string" ? e.detail : e.message) : "Something went wrong.";
}

function ResultTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <div className="text-muted text-sm">No rows returned.</div>;
  return (
    <Table>
      <Thead><Tr>{columns.map((c) => <Th key={c}>{c}</Th>)}</Tr></Thead>
      <Tbody>
        {rows.slice(0, 100).map((row, i) => (
          <Tr key={i}>{columns.map((c) => <Td key={c}>{String(row[c] ?? "")}</Td>)}</Tr>
        ))}
      </Tbody>
    </Table>
  );
}

export default function TransformsPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("nl");
  const [sourceId, setSourceId] = useState("");

  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });
  const sources = sourcesQuery.data?.sources ?? [];

  // ---- Natural Language tab ----
  const [nlGoal, setNlGoal] = useState("");
  const [nlLanguage, setNlLanguage] = useState<"auto" | "sql" | "pandas">("auto");
  const [nlResult, setNlResult] = useState<GenerateResult | null>(null);
  const [nlGenerating, setNlGenerating] = useState(false);
  const [nlError, setNlError] = useState<string | null>(null);

  const generateNL = async () => {
    if (!nlGoal.trim()) return;
    setNlGenerating(true); setNlError(null); setNlResult(null);
    try {
      const fn = nlLanguage === "pandas" ? generatePandasTransform : generateSqlTransform;
      const res = await fn(token, { request: nlGoal, source_id: sourceId || undefined });
      setNlResult(res);
    } catch (e) {
      setNlError(errMsg(e));
    } finally {
      setNlGenerating(false);
    }
  };

  const sendToEditor = () => {
    if (!nlResult) return;
    if (nlResult.type === "pandas") {
      setPyCode(nlResult.code);
      setTab("python");
    } else {
      setSqlCode(nlResult.code);
      setTab("sql");
    }
  };

  // ---- SQL Editor tab ----
  const [sqlCode, setSqlCode] = useState("SELECT 1;");
  const [sqlResult, setSqlResult] = useState<RunResult | null>(null);
  const [sqlPlan, setSqlPlan] = useState<DryRunResult | null>(null);
  const [sqlRunning, setSqlRunning] = useState(false);
  const [sqlError, setSqlError] = useState<string | null>(null);

  const runSql = async (dryRun: boolean) => {
    if (!sourceId) { toast.push("Select a data source first.", "danger"); return; }
    setSqlRunning(true); setSqlError(null); setSqlResult(null); setSqlPlan(null);
    try {
      if (dryRun) {
        setSqlPlan(await dryRunSqlTransform(token, { source_id: sourceId, sql: sqlCode }));
      } else {
        setSqlResult(await runSqlTransform(token, { source_id: sourceId, sql: sqlCode }));
        qc.invalidateQueries({ queryKey: ["transform-runs"] });
      }
    } catch (e) {
      setSqlError(errMsg(e));
    } finally {
      setSqlRunning(false);
    }
  };

  // ---- Python Editor tab ----
  const [pyCode, setPyCode] = useState("result_df = df.head(10)");
  const [pyResult, setPyResult] = useState<RunResult | null>(null);
  const [pyRunning, setPyRunning] = useState(false);
  const [pyError, setPyError] = useState<string | null>(null);
  const [pyExplanation, setPyExplanation] = useState<string | null>(null);
  const [pyExplaining, setPyExplaining] = useState(false);

  const runPython = async (previewOnly: boolean) => {
    if (!sourceId) { toast.push("Select a data source first.", "danger"); return; }
    setPyRunning(true); setPyError(null); setPyResult(null);
    try {
      const fn = previewOnly ? previewPandasTransform : runPandasTransform;
      const res = await fn(token, { source_id: sourceId, code: pyCode });
      setPyResult(res);
      if (!previewOnly) qc.invalidateQueries({ queryKey: ["transform-runs"] });
    } catch (e) {
      setPyError(errMsg(e));
    } finally {
      setPyRunning(false);
    }
  };

  const explainPython = async () => {
    setPyExplaining(true);
    try {
      const res = await explainCode(token, { code: pyCode, language: "pandas" });
      setPyExplanation(res.explanation);
    } catch (e) {
      toast.push(errMsg(e), "danger");
    } finally {
      setPyExplaining(false);
    }
  };

  // ---- History tab ----
  const runsQuery = useQuery({ queryKey: ["transform-runs"], queryFn: () => getTransformRuns(token, { limit: 50 }) });
  const runs = runsQuery.data?.runs ?? [];

  const replay = (run: TransformRunItem) => {
    setSourceId(run.source_id);
    if (run.transform_type === "pandas") {
      setPyCode(run.code);
      setTab("python");
    } else {
      setSqlCode(run.code);
      setTab("sql");
    }
    toast.push("Loaded into editor — review and run.", "default");
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Transforms</h1>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ maxWidth: 320 }}>
          <Select
            id="transform-source" label="Data source" value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
          >
            <option value="">Select a source</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </div>

        <Tabs
          items={[
            { id: "nl", label: "Natural Language" },
            { id: "sql", label: "SQL Editor" },
            { id: "python", label: "Python Editor" },
            { id: "history", label: "History" },
          ]}
          activeId={tab}
          onChange={setTab}
        />

        {tab === "nl" && (
          <Card>
            <div className="card-body">
              <div className="input-group" style={{ marginBottom: 12 }}>
                <label className="input-label">Describe your transformation in plain English</label>
                <div className="flex gap-2">
                  <Input
                    id="nl-goal" value={nlGoal} onChange={(e) => setNlGoal(e.target.value)}
                    placeholder="e.g. Filter rows where widget_count is greater than 15" style={{ flex: 1 }}
                  />
                  <Select
                    id="nl-language" value={nlLanguage} style={{ width: "auto" }}
                    onChange={(e) => setNlLanguage(e.target.value as "auto" | "sql" | "pandas")}
                  >
                    <option value="auto">Auto</option>
                    <option value="sql">SQL</option>
                    <option value="pandas">Pandas</option>
                  </Select>
                  <Button onClick={generateNL} disabled={!nlGoal.trim() || nlGenerating}>
                    {nlGenerating ? "Generating…" : "Generate"}
                  </Button>
                </div>
              </div>
              {nlError && <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 8 }}>{nlError}</div>}
              <div className="code-block" style={{ minHeight: 80, whiteSpace: "pre-wrap" }}>
                {nlResult ? nlResult.code : <span className="code-comment">-- Generated code will appear here</span>}
              </div>
              {nlResult && (
                <div className="flex items-center justify-between" style={{ marginTop: 8 }}>
                  <div className="flex items-center gap-2">
                    <Badge variant={nlResult.schema_used ? "success" : "warning"}>
                      {nlResult.schema_used ? "Grounded in real schema" : "No schema available"}
                    </Badge>
                    {nlResult.warnings.length > 0 && (
                      <Badge variant="warning">{nlResult.warnings.length} warning(s)</Badge>
                    )}
                  </div>
                  <Button size="sm" variant="secondary" onClick={sendToEditor}>
                    Send to {nlResult.type === "pandas" ? "Python" : "SQL"} Editor
                  </Button>
                </div>
              )}
            </div>
          </Card>
        )}

        {tab === "sql" && (
          <Card>
            <div className="card-body">
              <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
                <span className="text-sm text-muted">
                  {sources.find((s) => s.id === sourceId)?.name ?? "No source selected"}
                </span>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" disabled={sqlRunning} onClick={() => runSql(true)}>Dry Run</Button>
                  <Button size="sm" disabled={sqlRunning} onClick={() => runSql(false)}>Execute</Button>
                </div>
              </div>
              <textarea
                className="code-block" style={{ width: "100%", minHeight: 160, resize: "vertical" }}
                spellCheck={false} value={sqlCode} onChange={(e) => setSqlCode(e.target.value)}
              />
              {sqlError && <div className="text-xs" style={{ color: "var(--danger)", marginTop: 8 }}>{sqlError}</div>}
              {sqlPlan && (
                <div style={{ marginTop: 12 }}>
                  <div className="font-medium text-sm" style={{ marginBottom: 6 }}>Query Plan</div>
                  <ResultTable columns={sqlPlan.columns} rows={sqlPlan.plan} />
                </div>
              )}
              {sqlResult && (
                <div style={{ marginTop: 12 }}>
                  <div className="flex items-center justify-between" style={{ marginBottom: 6 }}>
                    <div className="font-medium text-sm">Result Preview</div>
                    <span className="text-xs text-muted">
                      {sqlResult.row_count} rows · {sqlResult.duration_ms}ms{sqlResult.truncated ? " · truncated" : ""}
                    </span>
                  </div>
                  <ResultTable columns={sqlResult.columns} rows={sqlResult.rows} />
                </div>
              )}
            </div>
          </Card>
        )}

        {tab === "python" && (
          <Card>
            <div className="card-body">
              <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
                <span className="text-sm text-muted">
                  {sources.find((s) => s.id === sourceId)?.name ?? "No source selected"}
                </span>
              </div>
              <textarea
                className="code-block" style={{ width: "100%", minHeight: 180, resize: "vertical" }}
                spellCheck={false} value={pyCode} onChange={(e) => setPyCode(e.target.value)}
              />
              <div className="flex gap-2" style={{ marginTop: 8 }}>
                <Button size="sm" variant="secondary" disabled={pyRunning} onClick={() => runPython(true)}>Preview (100 rows)</Button>
                <Button size="sm" disabled={pyRunning} onClick={() => runPython(false)}>Execute</Button>
                <Button size="sm" variant="ghost" disabled={pyExplaining} onClick={explainPython}>
                  {pyExplaining ? "Explaining…" : "✨ Explain"}
                </Button>
              </div>
              {pyError && <div className="text-xs" style={{ color: "var(--danger)", marginTop: 8 }}>{pyError}</div>}
              {pyExplanation && (
                <Card style={{ marginTop: 12, background: "var(--surface-hover)" }}>
                  <div className="card-body text-sm">{pyExplanation}</div>
                </Card>
              )}
              {pyResult && (
                <div style={{ marginTop: 12 }}>
                  <div className="flex items-center justify-between" style={{ marginBottom: 6 }}>
                    <div className="font-medium text-sm">{pyResult.preview ? "Preview" : "Result"}</div>
                    <span className="text-xs text-muted">
                      {pyResult.row_count} rows · {pyResult.duration_ms}ms{pyResult.truncated ? " · truncated" : ""}
                    </span>
                  </div>
                  <ResultTable columns={pyResult.columns} rows={pyResult.rows} />
                </div>
              )}
            </div>
          </Card>
        )}

        {tab === "history" && (
          runsQuery.isLoading ? (
            <Skeleton style={{ height: 200, borderRadius: 12 }} />
          ) : runs.length === 0 ? (
            <div className="empty-state">
              <h2 className="font-display text-xl">No transforms run yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
                Real SQL and Python transforms you run from this screen — or AXIOM runs on your
                behalf in chat — appear here.
              </p>
            </div>
          ) : (
            <Card style={{ overflow: "hidden" }}>
              <Table>
                <Thead>
                  <Tr><Th>Code</Th><Th>Type</Th><Th>Origin</Th><Th>Status</Th><Th>Rows</Th><Th>Created</Th><Th></Th></Tr>
                </Thead>
                <Tbody>
                  {runs.map((r) => (
                    <Tr key={r.id}>
                      <Td className="mono text-xs text-secondary" style={{ maxWidth: 320 }}>
                        {r.code.length > 60 ? `${r.code.slice(0, 60)}…` : r.code}
                      </Td>
                      <Td><Badge variant="midnight">{r.transform_type.toUpperCase()}</Badge></Td>
                      <Td><span className="text-xs text-muted">{r.origin === "chat_agent" ? "AXIOM" : "Manual"}</span></Td>
                      <Td>
                        {r.status === "success"
                          ? <Badge variant="success">Success</Badge>
                          : <Badge variant="danger" title={r.error_message ?? undefined}>Failed</Badge>}
                      </Td>
                      <Td className="text-sm text-secondary">{r.row_count ?? "—"}</Td>
                      <Td className="text-sm text-muted">{formatApiDate(r.created_at)}</Td>
                      <Td><Button size="sm" variant="ghost" onClick={() => replay(r)}>Replay</Button></Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Card>
          )
        )}
      </div>
    </div>
  );
}
