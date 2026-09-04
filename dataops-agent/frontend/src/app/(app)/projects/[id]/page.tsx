"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardBody, Badge, Skeleton, Button } from "@/components/ui";
import { getToken, listProjects, getProjectAgents } from "@/lib/api";

const EMPLOYEE_TYPE_LABEL: Record<string, string> = {
  dataops: "DataOps Engineer",
};

export default function ProjectDetailPage() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const router = useRouter();

  // No GET /api/v1/projects/{id} endpoint exists -- the list is already a
  // single cheap tenant-scoped query, so finding this project's own name
  // client-side avoids a second backend endpoint for one field.
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });
  const agents = useQuery({
    queryKey: ["project-agents", projectId],
    queryFn: () => getProjectAgents(token, projectId),
  });

  const project = projects.data?.projects.find((p) => p.id === projectId);
  const agentList = agents.data?.agents ?? [];

  if (projects.isError || agents.isError) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Project</h1></div>
        <div style={{ padding: "20px 24px" }}>
          <div className="empty-state">
            <h2 className="font-display text-xl">Can&apos;t open this project</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              It may not exist, or it may belong to a different tenant.
            </p>
            <Button size="sm" onClick={() => router.push("/projects")}>← Back to Projects</Button>
          </div>
        </div>
      </div>
    );
  }

  if (projects.isLoading || agents.isLoading) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Project</h1></div>
        <div style={{ padding: "20px 24px" }}><Skeleton style={{ height: 200, borderRadius: 12 }} /></div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <button className="auth-link-btn text-sm" onClick={() => router.push("/projects")}>← All Projects</button>
        <h1 className="page-title" style={{ marginTop: 4 }}>{project?.name ?? "Project"}</h1>
        <p className="text-muted text-sm" style={{ marginTop: 6 }}>
          {agentList.length} agent{agentList.length === 1 ? "" : "s"}
        </p>
      </div>

      <div style={{ padding: "20px 24px" }}>
        <Card>
          <CardHeader className="flex items-center justify-between">
            <span className="font-medium text-sm">Agents in this project</span>
            <Button size="sm" onClick={() => router.push(`/agents/hire?project_id=${projectId}`)}>
              + Hire Agent
            </Button>
          </CardHeader>
          <CardBody>
            {agentList.length === 0 ? (
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
      </div>
    </div>
  );
}
