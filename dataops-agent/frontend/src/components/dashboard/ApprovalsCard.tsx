"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardHeader, CardBody, Badge, Button, useToast } from "@/components/ui";
import { approveRequest, rejectRequest, type Approval } from "@/lib/api";

export function ApprovalsCard({ approvals, token }: { approvals: Approval[]; token: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();

  const approve = useMutation({
    mutationFn: (id: string) => approveRequest(token, id),
    onSuccess: () => {
      toast.push("Approved.", "success");
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: () => toast.push("Couldn't approve — try again.", "danger"),
  });

  const reject = useMutation({
    mutationFn: (id: string) => rejectRequest(token, id),
    onSuccess: () => {
      toast.push("Rejected.", "default");
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: () => toast.push("Couldn't reject — try again.", "danger"),
  });

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <span className="font-semibold text-sm">Pending Approvals</span>
        {approvals.length > 0 && <Badge variant="warning">{approvals.length}</Badge>}
      </CardHeader>
      <CardBody className="flex flex-col gap-2">
        {approvals.length === 0 ? (
          <div className="text-sm text-muted">Nothing pending approval.</div>
        ) : (
          approvals.map((a) => (
            <Card key={a.approval_id} style={{ padding: "10px 12px" }}>
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium" style={{ fontSize: 12 }}>
                  {a.action_name}
                </span>
                {a.risk_level === "high" && (
                  <Badge variant="danger" style={{ fontSize: 10 }}>
                    High risk
                  </Badge>
                )}
              </div>
              <div className="text-xs text-muted mb-2">{a.reason}</div>
              <div className="flex gap-2">
                <Button
                  variant="success"
                  size="sm"
                  style={{ flex: 1, fontSize: 11 }}
                  disabled={approve.isPending || reject.isPending}
                  onClick={() => approve.mutate(a.approval_id)}
                >
                  Approve
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  style={{ flex: 1, fontSize: 11 }}
                  disabled={approve.isPending || reject.isPending}
                  onClick={() => reject.mutate(a.approval_id)}
                >
                  Reject
                </Button>
              </div>
            </Card>
          ))
        )}
      </CardBody>
    </Card>
  );
}
