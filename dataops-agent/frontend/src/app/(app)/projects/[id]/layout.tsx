"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import { getToken, listProjects } from "@/lib/api";

const TABS = [
  { slug: "chat", label: "Chat" },
  { slug: "workbench", label: "Workbench" },
  { slug: "tasks", label: "Tasks" },
  { slug: "agents", label: "Agents" },
];

/**
 * The project container shell (Wunomo UI-rebuild slice 5, 2026-09-14) —
 * matches wunomo-all-screens.html's PHEAD + subnav exactly: project name,
 * a "Hire agent" button, then the Chat/Workbench/Tasks/Agents tabs. Wraps
 * every /projects/[id]/* route, including the bare /projects/[id] page,
 * which only ever redirects to a real tab (see that file).
 *
 * No GET /api/v1/projects/{id} endpoint exists -- same reasoning as the
 * pre-slice-5 project detail page this replaces: listProjects() is
 * already a single cheap tenant-scoped query, so finding this project's
 * own name client-side avoids a second backend endpoint for one field.
 */
export default function ProjectContainerLayout({ children }: { children: ReactNode }) {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const [hireOpen, setHireOpen] = useState(false);

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });
  const project = projects.data?.projects.find((p) => p.id === projectId);

  const activeTab = pathname.split("/")[3] ?? "";

  if (projects.isError) {
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

  if (projects.isLoading) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Project</h1></div>
        <div style={{ padding: "20px 24px" }}><Skeleton style={{ height: 200, borderRadius: 12 }} /></div>
      </div>
    );
  }

  if (!project) {
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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <Link href="/projects" className="btn btn-text text-sm">← All Projects</Link>
            <h1 className="page-title" style={{ marginTop: 4 }}>{project.name}</h1>
          </div>
          <Button size="sm" onClick={() => setHireOpen(true)}>Hire agent</Button>
        </div>
      </div>

      <div className="tabs" role="tablist" style={{ padding: "0 24px" }}>
        {TABS.map((t) => (
          <Link
            key={t.slug}
            href={`/projects/${projectId}/${t.slug}`}
            role="tab"
            aria-selected={activeTab === t.slug}
            className={["tab", activeTab === t.slug ? "active" : ""].filter(Boolean).join(" ")}
          >
            {t.label}
          </Link>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>{children}</div>

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
