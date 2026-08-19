"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, Badge, Button, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu } from "@/components/ui";
import {
  getToken, getMergedApprovals, approveRequest, rejectRequest, approveCommit, rejectCommit,
  type MergedApproval,
} from "@/lib/api";
import { formatApiDate } from "@/lib/dates";

function riskVariant(level: string): "success" | "warning" | "danger" | "gray" {
  switch (level) {
    case "high": return "danger";
    case "medium": return "warning";
    case "low": return "success";
    default: return "gray";
  }
}

function sourceLabel(source: string): string {
  return source === "cicd_deployment" ? "CI/CD Deployment" : "Agent Action";
}

export default function ApprovalsPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();

  const approvals = useQuery({ queryKey: ["merged-approvals"], queryFn: () => getMergedApprovals(token) });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["merged-approvals"] });

  const approveMut = useMutation({
    mutationFn: (item: MergedApproval) =>
      item.source === "cicd_deployment" ? approveCommit(token, item.id) : approveRequest(token, item.id),
    onSuccess: () => { toast.push("Approved.", "success"); invalidate(); },
    onError: () => toast.push("Failed to approve.", "danger"),
  });

  const rejectMut = useMutation({
    mutationFn: (item: MergedApproval) =>
      item.source === "cicd_deployment" ? rejectCommit(token, item.id) : rejectRequest(token, item.id),
    onSuccess: () => { toast.push("Rejected.", "default"); invalidate(); },
    onError: () => toast.push("Failed to reject.", "danger"),
  });

  const list = approvals.data?.approvals ?? [];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Approvals</h1>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {approvals.isLoading ? (
          <Skeleton style={{ height: 300, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">Nothing pending approval</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              Agent actions and CI/CD deployments that need a human sign-off will show up here.
            </p>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Request</Th>
                  <Th>Source</Th>
                  <Th>Risk</Th>
                  <Th>Requested</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((a: MergedApproval) => (
                  <Tr key={`${a.source}-${a.id}`}>
                    <Td>
                      <div style={{ fontWeight: 600 }}>{a.title}</div>
                      <div className="text-muted text-sm">{a.description}</div>
                    </Td>
                    <Td><Badge variant="info">{sourceLabel(a.source)}</Badge></Td>
                    <Td><Badge variant={riskVariant(a.risk_level)}>{a.risk_level}</Badge></Td>
                    <Td>{formatApiDate(a.created_at)}</Td>
                    <Td>
                      <div className="row-actions">
                        <Button
                          variant="ghost" icon title="Approve" aria-label={`Approve ${a.title}`}
                          disabled={approveMut.isPending} onClick={() => approveMut.mutate(a)}
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        </Button>
                        <RowActionsMenu
                          actions={[
                            { label: "Reject", disabled: rejectMut.isPending, onClick: () => rejectMut.mutate(a) },
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
    </div>
  );
}
