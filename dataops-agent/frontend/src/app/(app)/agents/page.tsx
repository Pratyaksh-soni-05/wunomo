"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Card, Table, Thead, Tbody, Tr, Th, Td, Skeleton } from "@/components/ui";
import { getToken, listAgents } from "@/lib/api";

const EMPLOYEE_TYPE_LABEL: Record<string, string> = {
  dataops: "DataOps Engineer",
};

export default function AgentsPage() {
  const token = getToken() as string;
  const router = useRouter();

  const agents = useQuery({ queryKey: ["agents"], queryFn: () => listAgents(token) });
  const list = agents.data?.agents ?? [];

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="page-title">Agents</h1>
            <p className="text-muted text-sm" style={{ marginTop: 6 }}>
              Every agent your tenant has hired — assigned to a project or not.
            </p>
          </div>
          <Button size="sm" onClick={() => router.push("/agents/hire")}>+ Hire Agent</Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {agents.isLoading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No agents yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              Hire an agent to give it a name, a data source scope, and optionally a project.
            </p>
            <Button size="sm" onClick={() => router.push("/agents/hire")}>+ Hire Agent</Button>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Name</Th>
                  <Th>Type</Th>
                  <Th>Status</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((a) => (
                  <Tr key={a.id}>
                    <Td>
                      <button className="auth-link-btn" onClick={() => router.push(`/agents/${a.id}`)}>
                        {a.name}
                      </button>
                    </Td>
                    <Td className="text-muted text-sm">{EMPLOYEE_TYPE_LABEL[a.employee_type] ?? a.employee_type}</Td>
                    <Td>
                      <Badge variant={a.status === "offboarded" ? "gray" : "success"}>
                        {a.status === "offboarded" ? "Offboarded" : "Active"}
                      </Badge>
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
