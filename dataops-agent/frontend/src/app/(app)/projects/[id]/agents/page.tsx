"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardHeader, CardBody, Badge, Button } from "@/components/ui";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import { getToken, getProjectAgents } from "@/lib/api";

const EMPLOYEE_TYPE_LABEL: Record<string, string> = {
  dataops: "DataOps Engineer",
};

// Moved verbatim from the pre-slice-5 /projects/[id] page (Wunomo
// UI-rebuild slice 5) -- this content IS the Agents tab, unchanged in
// substance. The page-level header/back-link it used to render are now
// the container layout's job (layout.tsx, one level up); this page is
// just the "Agents in this project" card.
export default function ProjectAgentsTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const router = useRouter();
  const qc = useQueryClient();
  const [hireOpen, setHireOpen] = useState(false);

  const agents = useQuery({
    queryKey: ["project-agents", projectId],
    queryFn: () => getProjectAgents(token, projectId),
  });
  const agentList = agents.data?.agents ?? [];

  return (
    <div style={{ padding: "20px 24px" }}>
      <Card>
        <CardHeader className="flex items-center justify-between">
          <span className="font-medium text-sm">
            Agents in this project · {agentList.length} agent{agentList.length === 1 ? "" : "s"}
          </span>
          <Button size="sm" onClick={() => setHireOpen(true)}>+ Hire Agent</Button>
        </CardHeader>
        <CardBody>
          {agents.isLoading ? (
            <p className="text-muted text-sm">Loading…</p>
          ) : agentList.length === 0 ? (
            <p className="text-muted text-sm">
              No agents yet — agents are assigned to a project when you hire them.
            </p>
          ) : (
            <div className="grid grid-3" style={{ gap: 12 }}>
              {agentList.map((a) => (
                <Card
                  key={a.id} hover style={{ cursor: "pointer" }}
                  onClick={() => router.push(`/agents/${a.id}`)}
                >
                  <CardBody>
                    <div className="font-medium text-sm">{a.name}</div>
                    <Badge variant="midnight" style={{ marginTop: 6 }}>
                      {EMPLOYEE_TYPE_LABEL[a.employee_type] ?? a.employee_type}
                    </Badge>
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <HireAgentModal
        token={token}
        open={hireOpen}
        onClose={() => setHireOpen(false)}
        initialProjectId={projectId}
        onHired={() => qc.invalidateQueries({ queryKey: ["project-agents", projectId] })}
      />
    </div>
  );
}
