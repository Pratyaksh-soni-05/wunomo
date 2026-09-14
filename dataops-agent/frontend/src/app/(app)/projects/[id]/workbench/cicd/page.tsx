"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Tabs, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import { useProjectScope } from "@/lib/projectScope";
import { NoSourcesGrantedEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import {
  getToken, getCommits, getDeployments, approveCommit, rejectCommit,
  type CommitItem, type DeploymentItem,
} from "@/lib/api";

function ciStatusVariant(status: string): "success" | "danger" | "warning" | "info" | "gray" {
  switch (status) {
    case "passed": return "success";
    case "failed": return "danger";
    case "running": return "info";
    case "skipped": return "gray";
    default: return "warning";
  }
}

function gateVariant(decision: string | null): "success" | "danger" | "warning" | "gray" {
  switch (decision) {
    case "auto_approved": case "approved": return "success";
    case "rejected": return "danger";
    case "pending_approval": return "warning";
    default: return "gray";
  }
}

function deployStatusVariant(status: string): "success" | "danger" | "warning" | "info" | "gray" {
  switch (status) {
    case "active": return "success";
    case "rolled_back": case "failed": return "danger";
    case "deploying": return "info";
    default: return "gray";
  }
}

// Filtered copy of /cicd (slice 6a). The tenant-wide KPI summary endpoint
// (getCicdStatusSummary) isn't used here -- showing tenant-wide numbers
// above a project-scoped table would be its own quiet inconsistency.
// Recomputed client-side from the same filtered commit/deployment lists
// the tables below render, using the identical formula the backend uses
// (services/cicd_service.py's get_status_summary): degraded if rollbacks
// or pending approvals > 0, healthy otherwise.
//
// Commits/deployments are tied to pipeline_id -- CommitItem.pipeline_id
// is nullable (a webhook commit can arrive before the pipeline mapping is
// known), so a commit with no resolvable pipeline simply doesn't appear
// in any project's view. Not one of the two designated unscoped-treatment
// surfaces (Pipelines/Incidents/Transforms) -- accepted as a minor,
// honest gap for this slice, not built out further here.
export default function ProjectCicdTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("commits");

  const { sourceIds, pipelineIds, loading: scopeLoading } = useProjectScope(token, projectId);
  const commits = useQuery({ queryKey: ["cicd-commits"], queryFn: () => getCommits(token) });
  const deployments = useQuery({ queryKey: ["cicd-deployments"], queryFn: () => getDeployments(token) });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["cicd-commits"] });
    qc.invalidateQueries({ queryKey: ["cicd-deployments"] });
  };

  const approveMut = useMutation({
    mutationFn: (id: string) => approveCommit(token, id),
    onSuccess: () => { toast.push("Deployment approved and queued.", "success"); invalidate(); },
    onError: () => toast.push("Failed to approve deployment.", "danger"),
  });

  const rejectMut = useMutation({
    mutationFn: (id: string) => rejectCommit(token, id),
    onSuccess: () => { toast.push("Deployment rejected.", "default"); invalidate(); },
    onError: () => toast.push("Failed to reject deployment.", "danger"),
  });

  const commitList = (commits.data ?? []).filter((c) => c.pipeline_id && pipelineIds.has(c.pipeline_id));
  const deploymentList = (deployments.data ?? []).filter((d) => pipelineIds.has(d.pipeline_id));
  const loading = commits.isLoading || deployments.isLoading || scopeLoading;

  const activeDeployments = deploymentList.filter((d) => d.status === "active").length;
  const totalRollbacks = deploymentList.filter((d) => d.status === "rolled_back").length;
  const pendingApprovals = commitList.filter((c) => c.gate_decision === "pending_approval").length;
  const health = totalRollbacks > 0 || pendingApprovals > 0 ? "degraded" : "healthy";

  if (!loading && sourceIds.size === 0) {
    return <NoSourcesGrantedEmptyState projectId={projectId} surface="CI/CD activity" />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {loading ? (
        <Skeleton style={{ height: 90, borderRadius: 12 }} />
      ) : (
        <div className="stats-grid">
          <Card className="metric-card">
            <div className="text-sm text-muted">Pipeline Health</div>
            <div className="metric-value" style={{ color: health === "healthy" ? "var(--success)" : "var(--danger)" }}>
              {health}
            </div>
          </Card>
          <Card className="metric-card">
            <div className="text-sm text-muted">Active Deployments</div>
            <div className="metric-value">{activeDeployments}</div>
          </Card>
          <Card className="metric-card">
            <div className="text-sm text-muted">Rollbacks</div>
            <div className="metric-value">{totalRollbacks}</div>
          </Card>
          <Card className="metric-card">
            <div className="text-sm text-muted">Pending Approvals</div>
            <div className="metric-value">{pendingApprovals}</div>
          </Card>
        </div>
      )}

      <Tabs
        items={[{ id: "commits", label: "Commits" }, { id: "deployments", label: "Deployments" }]}
        activeId={tab}
        onChange={setTab}
      />

      {tab === "commits" ? (
        loading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : commitList.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No commits yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              Commits arrive via the GitHub webhook when one of this project's pipeline definition
              files changes.
            </p>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Commit</Th><Th>Branch</Th><Th>Author</Th><Th>CI Status</Th>
                  <Th>Gate</Th><Th>Risk</Th><Th>When</Th><Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {commitList.map((c: CommitItem) => (
                  <Tr key={c.id}>
                    <Td><code>{c.commit_sha.slice(0, 8)}</code></Td>
                    <Td>{c.branch}</Td>
                    <Td>{c.author || "—"}</Td>
                    <Td><Badge variant={ciStatusVariant(c.ci_status)}>{c.ci_status}</Badge></Td>
                    <Td><Badge variant={gateVariant(c.gate_decision)}>{c.gate_decision || "—"}</Badge></Td>
                    <Td className="tabular-nums">{Math.round(c.risk_score)}</Td>
                    <Td>{formatApiDate(c.trigger_time)}</Td>
                    <Td>
                      {c.gate_decision === "pending_approval" ? (
                        <div className="row-actions">
                          <Button
                            variant="ghost" icon title="Approve" aria-label={`Approve ${c.commit_sha.slice(0, 8)}`}
                            disabled={approveMut.isPending} onClick={() => approveMut.mutate(c.id)}
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          </Button>
                          <RowActionsMenu
                            actions={[
                              { label: "Reject", disabled: rejectMut.isPending, onClick: () => rejectMut.mutate(c.id) },
                            ]}
                          />
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
        )
      ) : loading ? (
        <Skeleton style={{ height: 200, borderRadius: 12 }} />
      ) : deploymentList.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">No deployments yet</h2>
          <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
            Deployments appear here once a commit on one of this project's pipelines is approved and
            deployed.
          </p>
        </div>
      ) : (
        <Card>
          <Table>
            <Thead>
              <Tr>
                <Th>Commit</Th><Th>Status</Th><Th>Monitoring</Th>
                <Th>Runs</Th><Th>Failures</Th><Th>Deployed</Th>
              </Tr>
            </Thead>
            <Tbody>
              {deploymentList.map((d: DeploymentItem) => (
                <Tr key={d.id}>
                  <Td><code>{d.commit_sha.slice(0, 8)}</code></Td>
                  <Td><Badge variant={deployStatusVariant(d.status)}>{d.status}</Badge></Td>
                  <Td>{d.monitoring_active ? "Active" : "Closed"}</Td>
                  <Td className="tabular-nums">{d.post_deploy_run_count}</Td>
                  <Td className="tabular-nums">{d.post_deploy_failure_count}</Td>
                  <Td>{formatApiDate(d.deployed_at)}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
