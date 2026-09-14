"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Badge, Modal, Input, Select,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu,
} from "@/components/ui";
import { useProjectScope } from "@/lib/projectScope";
import { NoSourcesGrantedEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import {
  getToken, getQualityRules, createQualityRule, deleteQualityRule, runQualityChecks,
  getPipelines, type QualityRuleItem,
} from "@/lib/api";

const RULE_TYPES = ["not_null", "unique", "accepted_values", "range", "freshness", "regex", "row_count", "custom_sql"];
const SEVERITIES = ["low", "medium", "high", "critical"];

function severityVariant(sev: string): "success" | "warning" | "danger" | "gray" {
  switch (sev) {
    case "critical": case "high": return "danger";
    case "medium": return "warning";
    default: return "gray";
  }
}

// Filtered copy of /quality (slice 6a) -- a rule belongs to a pipeline,
// not a source directly, so this filters on pipelineIds (already derived
// by the resolver: a pipeline whose own source_id is in this project's
// resolved source set), not sourceIds. QualityRule.pipeline_id is
// required at creation (the audit's own finding: nullable in the column,
// never actually null in practice), so this resolves cleanly with no
// "unscoped rule" case to handle -- unlike Pipelines/Incidents/Transforms.
export default function ProjectQualityTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [pipelineId, setPipelineId] = useState("");
  const [ruleType, setRuleType] = useState(RULE_TYPES[0]);
  const [columnName, setColumnName] = useState("");
  const [severity, setSeverity] = useState("high");

  const { sourceIds, pipelineIds, loading: scopeLoading } = useProjectScope(token, projectId);
  const pipelines = useQuery({ queryKey: ["pipelines"], queryFn: () => getPipelines(token) });
  const rules = useQuery({ queryKey: ["quality-rules"], queryFn: () => getQualityRules(token) });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["quality-rules"] });

  const createMut = useMutation({
    mutationFn: () => createQualityRule(token, {
      pipeline_id: pipelineId, name, rule_type: ruleType,
      column_name: columnName || undefined, severity,
    }),
    onSuccess: () => {
      toast.push(`Rule "${name}" created.`, "success");
      setModalOpen(false);
      setName(""); setColumnName("");
      invalidate();
    },
    onError: () => toast.push("Failed to create rule — check a pipeline is selected.", "danger"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteQualityRule(token, id),
    onSuccess: () => { toast.push("Rule deleted.", "default"); invalidate(); },
    onError: () => toast.push("Failed to delete rule.", "danger"),
  });

  const runMut = useMutation({
    mutationFn: (pipelineIdToRun: string) => runQualityChecks(token, pipelineIdToRun),
    onSuccess: (result: unknown) => {
      const r = result as { score?: number; passed?: number; failed?: number };
      toast.push(`Checks ran — score ${r.score ?? "—"}, ${r.passed ?? 0} passed / ${r.failed ?? 0} failed.`, "success");
      invalidate();
    },
    onError: () => toast.push("Failed to run checks.", "danger"),
  });

  const allPipelines = pipelines.data?.pipelines ?? [];
  // Only this project's own pipelines are offered when creating a rule --
  // otherwise viewing a scoped list while being able to attach a new rule
  // to an out-of-scope pipeline would be its own quiet inconsistency.
  const projectPipelines = allPipelines.filter((p) => pipelineIds.has(p.id));
  const pipelineName = (id: string) => allPipelines.find((p) => p.id === id)?.name || id;

  const list = (rules.data?.rules ?? []).filter((r) => pipelineIds.has(r.pipeline_id));
  const loading = rules.isLoading || pipelines.isLoading || scopeLoading;

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
        <span className="text-muted text-sm">Quality rules on this project&apos;s pipelines.</span>
        <Button size="sm" onClick={() => setModalOpen(true)} disabled={projectPipelines.length === 0}>+ New Rule</Button>
      </div>

      {loading ? (
        <Skeleton style={{ height: 300, borderRadius: 12 }} />
      ) : sourceIds.size === 0 ? (
        <NoSourcesGrantedEmptyState projectId={projectId} surface="quality rules" />
      ) : list.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">No quality rules yet</h2>
          <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
            {projectPipelines.length === 0
              ? "This project has no pipelines to attach rules to yet."
              : "Attach rules to a pipeline to catch bad data before it spreads."}
          </p>
          {projectPipelines.length > 0 && <Button size="sm" onClick={() => setModalOpen(true)}>+ New Rule</Button>}
        </div>
      ) : (
        <Card>
          <Table>
            <Thead>
              <Tr>
                <Th>Name</Th>
                <Th>Pipeline</Th>
                <Th>Type</Th>
                <Th>Column</Th>
                <Th>Severity</Th>
                <Th>Pass / Fail</Th>
                <Th>Actions</Th>
              </Tr>
            </Thead>
            <Tbody>
              {list.map((r: QualityRuleItem) => (
                <Tr key={r.id}>
                  <Td>{r.name}</Td>
                  <Td>{pipelineName(r.pipeline_id)}</Td>
                  <Td><Badge variant="info">{r.rule_type}</Badge></Td>
                  <Td>{r.column_name || "—"}</Td>
                  <Td><Badge variant={severityVariant(r.severity)}>{r.severity}</Badge></Td>
                  <Td className="tabular-nums">{r.pass_count ?? 0} / {r.fail_count ?? 0}</Td>
                  <Td>
                    <div className="row-actions">
                      <Button
                        variant="ghost" icon title="Run Checks" aria-label={`Run checks for ${r.name}`}
                        disabled={runMut.isPending} onClick={() => runMut.mutate(r.pipeline_id)}
                      >
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      </Button>
                      <RowActionsMenu
                        actions={[
                          { label: "Delete", disabled: deleteMut.isPending, onClick: () => deleteMut.mutate(r.id) },
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

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="New Quality Rule"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button disabled={!name || !pipelineId || createMut.isPending} onClick={() => createMut.mutate()}>
              {createMut.isPending ? "Creating..." : "Create"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input id="rule-name" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          <Select id="rule-pipeline" label="Pipeline" value={pipelineId} onChange={(e) => setPipelineId(e.target.value)} required>
            <option value="">Select a pipeline</option>
            {projectPipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
          <Select id="rule-type" label="Rule type" value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
            {RULE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
          <Input id="rule-column" label="Column (optional)" value={columnName} onChange={(e) => setColumnName(e.target.value)} />
          <Select id="rule-severity" label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </div>
      </Modal>
    </div>
  );
}
