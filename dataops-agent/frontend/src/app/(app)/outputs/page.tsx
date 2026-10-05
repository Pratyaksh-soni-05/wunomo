"use client";

// Outputs (blueprint §11.1) -- the real empty surface, not a mocked-up
// library. Confirmed before building (see backend's Output model
// docstring, services/output_service.py): no tool in this codebase
// produces a real file yet, so the honest primary state of this screen
// is empty. Built that way -- a correct empty state with real,
// functioning components ready for the first real row, not fixtures.
//
// Honesty gaps versus §11's own mock, each investigated against the
// real data this page actually has, not assumed:
//   - §11 shows an amber "assumed, not verified" line alongside green
//     checks. OutputTrustCheck (services/output_service.py's
//     compute_trust_score(), reading QualityRuleEngine.run_checks()'s
//     real result shape) is binary pass/fail -- there is no "assumed
//     rather than verified" concept anywhere in the quality-rule engine
//     to surface. A failed check renders red (a real failure), never
//     amber (a different claim this data can't back). The amber
//     treatment is scaffolded in CSS (.trust-check-assumed) ready for
//     the day trust_checks carries a real third state, not wired to
//     anything today.
//   - §11's "show the SQL" is rendered only when a story entry's own
//     `sql` field is present (api/v1/outputs.py's provenance join reads
//     it straight off the real producing TaskStep.tool_args) -- never a
//     placeholder link for a step that has none.
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Card, Input, Select, Skeleton, useToast } from "@/components/ui";
import { EmployeeAvatar } from "@/components/chat/EmployeeAvatar";
import { timeAgo, formatApiDate } from "@/lib/dates";
import {
  getToken, getOutputs, getOutput, getOutputProvenance, downloadOutput,
  type OutputItem, type ProvenanceEntry,
} from "@/lib/api";

function trustVariant(score: number): "success" | "warning" | "danger" {
  if (score >= 90) return "success";
  if (score >= 70) return "warning";
  return "danger";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileSubline(o: OutputItem): string {
  const parts = [o.version > 1 ? `v${o.version} · supersedes v${o.version - 1}` : null, formatSize(o.size_bytes)];
  return parts.filter(Boolean).join(" · ");
}

const PROVENANCE_DOT: Record<string, string> = {
  task_created: "info", task_completed: "info",
  handoff_received: "gray", approval: "hold",
  step_executed: "success", output_created: "accent", audit_event: "gray",
};

function ProvenanceStory({ story }: { story: ProvenanceEntry[] }) {
  if (story.length === 0) {
    return <p className="text-muted text-sm">No real lineage recorded yet.</p>;
  }
  return (
    <div className="provenance-story">
      {story.map((entry, i) => (
        <div key={i} className="provenance-entry">
          <span className={`provenance-dot provenance-dot-${PROVENANCE_DOT[entry.type] ?? "gray"}`} aria-hidden="true" />
          <div className="provenance-entry-body">
            <div className="provenance-entry-desc">{entry.description}</div>
            <div className="provenance-entry-meta">
              {entry.at ? formatApiDate(entry.at) : "—"}
              {entry.sql && (
                <details className="provenance-sql">
                  <summary>Show the SQL</summary>
                  <pre><code>{entry.sql}</code></pre>
                </details>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TrustScoreCard({ output }: { output: OutputItem }) {
  // §11 requires nothing render when there's nothing to show -- no
  // badge, no "N/A" placeholder standing in for a real number.
  if (output.trust_score === null || !output.trust_checks) return null;
  return (
    <div className="trust-score-card">
      <div className="trust-score-header">
        <span className="trust-score-label">Trust score</span>
        <Badge variant={trustVariant(output.trust_score)}>{Math.round(output.trust_score)}</Badge>
      </div>
      {output.trust_checks.map((c, i) => (
        <div key={i} className={`trust-check-row ${c.passed ? "trust-check-passed" : "trust-check-failed"}`}>
          <span className="trust-check-icon" aria-hidden="true">{c.passed ? "✓" : "✗"}</span>
          <span>
            <strong>{c.check}</strong> — {c.message}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function OutputsPage() {
  const token = getToken() as string;
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [downloading, setDownloading] = useState(false);

  // Pre-select from a deep link, e.g. LiveWorkPanel's Files tab rows
  // (/outputs?output=<id>) -- window.location.search directly, not
  // useSearchParams(), matching this codebase's own established reason
  // (agents/[id]/page.tsx's highlight_source, chat/page.tsx): this app's
  // shell has no <Suspense> boundary for useSearchParams(), and this only
  // ever runs client-side anyway ("use client" at the top of this file).
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("output");
    if (id) setSelectedId(id);
  }, []);

  const outputsQuery = useQuery({ queryKey: ["outputs"], queryFn: () => getOutputs(token) });
  const detailQuery = useQuery({
    queryKey: ["output", selectedId],
    queryFn: () => getOutput(token, selectedId as string),
    enabled: !!selectedId,
  });
  const provenanceQuery = useQuery({
    queryKey: ["output-provenance", selectedId],
    queryFn: () => getOutputProvenance(token, selectedId as string),
    enabled: !!selectedId,
  });

  // useMemo (not a bare ?? []) so this is referentially stable across
  // renders where the query data itself hasn't changed -- otherwise a
  // fresh [] literal on every render with no data yet would invalidate
  // projectOptions' own memoization below on every render, pointlessly.
  const allOutputs = useMemo(() => outputsQuery.data?.outputs ?? [], [outputsQuery.data]);

  // Real distinct projects present in this tenant's own outputs -- never
  // a second, separately-fetched "all projects" list that could disagree
  // with what's actually shown.
  const projectOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const o of allOutputs) {
      if (o.project_id && o.project_name) seen.set(o.project_id, o.project_name);
    }
    return Array.from(seen.entries());
  }, [allOutputs]);

  const filtered = allOutputs.filter((o) => {
    if (projectFilter && o.project_id !== projectFilter) return false;
    if (search && !o.filename.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const selected = detailQuery.data;

  const handleDownload = async (o: OutputItem) => {
    setDownloading(true);
    try {
      await downloadOutput(token, o.id, o.filename);
    } catch {
      toast.push("Failed to download.", "danger");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Outputs</h1>
      </div>

      <div className="outputs-toolbar">
        <Input
          type="text" className="outputs-search" placeholder="Search by name..."
          value={search} onChange={(e) => setSearch(e.target.value)}
          aria-label="Search outputs by name"
        />
        <Select
          className="outputs-project-filter" value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
          aria-label="Filter by project"
        >
          <option value="">All projects</option>
          {projectOptions.map(([id, name]) => (
            <option key={id} value={id}>{name}</option>
          ))}
        </Select>
      </div>

      <div className={`outputs-body${selectedId ? " with-detail" : ""}`}>
        <div className="outputs-list-col">
          {outputsQuery.isLoading ? (
            <Skeleton style={{ height: 200, borderRadius: 12 }} />
          ) : allOutputs.length === 0 ? (
            <div className="empty-state">
              <h2 className="font-display text-xl">No files yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
                Anything your team produces lands here automatically.
              </p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <h2 className="font-display text-xl">No matches</h2>
              <p className="text-muted text-sm">Nothing matches this search or project filter.</p>
            </div>
          ) : (
            <Card className="outputs-table">
              <div className="outputs-table-header">
                <span>FILE</span>
                <span>MADE BY</span>
                <span>PROJECT</span>
                <span>TRUST</span>
                <span></span>
              </div>
              {filtered.map((o) => (
                <div
                  key={o.id}
                  role="button"
                  tabIndex={0}
                  className={`outputs-table-row${o.id === selectedId ? " selected" : ""}`}
                  onClick={() => setSelectedId(o.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(o.id); }
                  }}
                >
                  <span className="outputs-file-cell">
                    <span className="outputs-filename">{o.filename}</span>
                    <span className="outputs-file-subline">{fileSubline(o)}</span>
                  </span>
                  <span className="outputs-made-by-cell">
                    <EmployeeAvatar name={o.agent_name ?? "Unknown"} employeeType={o.employee_type} size="sm" />
                    <span>{o.agent_name ?? "Unknown"}</span>
                  </span>
                  <span className="text-muted text-sm">{o.project_name ?? "—"}</span>
                  <span>
                    {o.trust_score !== null && (
                      <Badge variant={trustVariant(o.trust_score)}>{Math.round(o.trust_score)}</Badge>
                    )}
                  </span>
                  <span>
                    <Button
                      size="sm" variant="secondary" disabled={downloading}
                      onClick={(e) => { e.stopPropagation(); handleDownload(o); }}
                    >
                      Download
                    </Button>
                  </span>
                </div>
              ))}
            </Card>
          )}
        </div>

        {selectedId && (
          <div className="outputs-detail-col">
            {detailQuery.isLoading || !selected ? (
              <Skeleton style={{ height: 300, borderRadius: 12 }} />
            ) : (
              <Card className="outputs-detail">
                <div className="outputs-detail-header">
                  <div className="outputs-detail-filename">{selected.filename}</div>
                  <div className="text-muted text-sm">
                    Made by {selected.agent_name ?? "Unknown"} · {timeAgo(selected.created_at)}
                  </div>
                </div>

                <TrustScoreCard output={selected} />

                {selected.supersedes_output_id && (
                  <button
                    type="button" className="outputs-supersedes-link"
                    onClick={() => setSelectedId(selected.supersedes_output_id)}
                  >
                    Supersedes v{selected.version - 1} — view that version →
                  </button>
                )}

                <div className="outputs-section-label">How this was made</div>
                {provenanceQuery.isLoading ? (
                  <Skeleton style={{ height: 120, borderRadius: 8 }} />
                ) : (
                  <ProvenanceStory story={provenanceQuery.data?.story ?? []} />
                )}

                <div className="outputs-detail-actions">
                  <Button size="sm" disabled={downloading} onClick={() => handleDownload(selected)}>Download</Button>
                </div>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
