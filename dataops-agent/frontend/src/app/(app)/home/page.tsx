"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardBody, Button, Skeleton } from "@/components/ui";
import { ICON_NEW_PROJECT } from "@/components/shell/navItems";
import { formatApiDateOnly } from "@/lib/dates";
import { useProjectScope } from "@/lib/projectScope";
import { getToken, decodeUserFromToken, listProjects } from "@/lib/api";

// Real agent count + real, de-duplicated source count, both from the same
// resolver every Workbench surface reads (lib/projectScope.ts, slice 6a) --
// no aggregate endpoint exists yet for either, source count especially,
// which is why this is still an N-of-N nested fetch under the hood.
// Accepted for now given the small project/agent counts expected at this
// stage; logged as a real backend gap, not silently absorbed:
// WALKTHROUGH_FINDINGS_2026-08.md item 92 (GET /api/v1/projects/summary).
function ProjectCardStats({ token, projectId }: { token: string; projectId: string }) {
  const { agentCount, sourceIds, loading } = useProjectScope(token, projectId);

  if (loading && agentCount === 0) return <Skeleton style={{ height: 14, width: 100 }} />;

  return (
    <span className="text-muted text-xs">
      {agentCount} agent{agentCount === 1 ? "" : "s"}
      {" · "}
      {loading ? "…" : `${sourceIds.size} source${sourceIds.size === 1 ? "" : "s"}`}
    </span>
  );
}

export default function HomePage() {
  const router = useRouter();
  const token = getToken() as string;
  const user = decodeUserFromToken(token);
  const displayName = user?.email ? user.email.split("@")[0] : "there";

  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });
  const projects = projectsQuery.data?.projects ?? [];

  return (
    <div style={{ padding: "44px 24px 40px", maxWidth: 880, margin: "0 auto", width: "100%" }}>
      <h1 className="font-display text-3xl">Welcome back, {displayName}</h1>
      <p className="text-muted text-sm" style={{ margin: "6px 0 28px" }}>
        Pick up a project, or start a new one and hire the team it needs.
      </p>

      <Card hover style={{ cursor: "pointer" }} onClick={() => router.push("/projects?new=1")}>
        <CardBody className="flex items-center gap-3">
          <span
            style={{
              width: 34, height: 34, borderRadius: "var(--radius)", background: "var(--surface-hover)",
              border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text-secondary)", flexShrink: 0,
            }}
          >
            {ICON_NEW_PROJECT}
          </span>
          <div>
            <div className="font-medium">Start a new project</div>
            <div className="text-muted text-sm">Name it, describe the work, then hire the agents it needs.</div>
          </div>
        </CardBody>
      </Card>

      <div
        className="text-muted text-xs"
        style={{ textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, margin: "30px 0 12px" }}
      >
        Recent
      </div>

      {projectsQuery.isLoading ? (
        <Skeleton style={{ height: 120, borderRadius: 12 }} />
      ) : projects.length === 0 ? (
        <p className="text-muted text-sm">No projects yet — start one above.</p>
      ) : (
        <div className="grid grid-3" style={{ gap: 12 }}>
          {projects.map((p) => (
            <Card key={p.id} hover style={{ cursor: "pointer" }} onClick={() => router.push(`/projects/${p.id}/chat`)}>
              <CardBody>
                <div className="font-display" style={{ fontSize: 16 }}>{p.name}</div>
                <p className="text-muted text-sm" style={{ margin: "2px 0 16px", minHeight: 19 }}>
                  {p.description || " "}
                </p>
                <div className="flex items-center justify-between">
                  <ProjectCardStats token={token} projectId={p.id} />
                  <span className="text-muted text-xs">Created {formatApiDateOnly(p.created_at)}</span>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      <div style={{ marginTop: 32 }}>
        <Button variant="text" onClick={() => router.push("/dashboard")}>Workspace health</Button>
      </div>
    </div>
  );
}
