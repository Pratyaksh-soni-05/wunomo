"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Tabs, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getCommits, getDeployments, getCicdStatusSummary, approveCommit, rejectCommit,
  type CommitItem, type DeploymentItem,
} from "@/lib/api";

function ciStatusVariant(status: string): "success" | "danger" | "warning" | "info" | "gray" {
  switch (status) {
    case "passed": return "success";
    case "failed": return "danger";
    case "running": return "info";
    case "skipped": return "gray";
    default: return "warning"; // pending
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
    default: return "gray"; // queued
  }
}

export default function CicdPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("commits");

  const summary = useQuery({ queryKey: ["cicd-summary"], queryFn: () => getCicdStatusSummary(token) });
  const commits = useQuery({ queryKey: ["cicd-commits"], queryFn: () => getCommits(token) });
  const deployments = useQuery({ queryKey: ["cicd-deployments"], queryFn: () => getDeployments(token) });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["cicd-summary"] });
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

  const s = (summary.data ?? {}) as {
    health?: string; active_deployments?: number; total_rollbacks?: number; pending_approvals?: number;
  };
  const commitList = commits.data ?? [];
  const deploymentList = deployments.data ?? [];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">CI / CD</h1>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
        {summary.isLoading ? (
          <Skeleton style={{ height: 90, borderRadius: 12 }} />
        ) : (
          <div className="stats-grid">
            <Card className="metric-card">
              <div className="text-sm text-muted">Pipeline Health</div>
              <div className="metric-value" style={{ color: s.health === "healthy" ? "var(--success)" : "var(--danger)" }}>
                {s.health ?? "unknown"}
              </div>
            </Card>
            <Card className="metric-card">
              <div className="text-sm text-muted">Active Deployments</div>
              <div className="metric-value">{s.active_deployments ?? 0}</div>
            </Card>
            <Card className="metric-card">
              <div className="text-sm text-muted">Rollbacks</div>
              <div className="metric-value">{s.total_rollbacks ?? 0}</div>
            </Card>
            <Card className="metric-card">
              <div className="text-sm text-muted">Pending Approvals</div>
              <div className="metric-value">{s.pending_approvals ?? 0}</div>
            </Card>
          </div>
        )}

        <Tabs
          items={[{ id: "commits", label: "Commits" }, { id: "deployments", label: "Deployments" }]}
          activeId={tab}
          onChange={setTab}
        />

        {tab === "commits" ? (
          commits.isLoading ? (
            <Skeleton style={{ height: 200, borderRadius: 12 }} />
          ) : commitList.length === 0 ? (
            <div className="empty-state">
              <h2 className="font-display text-xl">No commits yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
                Commits arrive via the GitHub webhook when a pipeline definition file changes.
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
                      <Td>{Math.round(c.risk_score)}</Td>
                      <Td>{formatApiDate(c.trigger_time)}</Td>
                      <Td>
                        {c.gate_decision === "pending_approval" ? (
                          <div className="flex gap-2">
                            <Button size="sm" variant="success" disabled={approveMut.isPending} onClick={() => approveMut.mutate(c.id)}>Approve</Button>
                            <Button size="sm" variant="danger" disabled={rejectMut.isPending} onClick={() => rejectMut.mutate(c.id)}>Reject</Button>
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
        ) : deployments.isLoading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : deploymentList.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No deployments yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              Deployments appear here once a commit is approved and deployed.
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
                    <Td>{d.post_deploy_run_count}</Td>
                    <Td>{d.post_deploy_failure_count}</Td>
                    <Td>{formatApiDate(d.deployed_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}
