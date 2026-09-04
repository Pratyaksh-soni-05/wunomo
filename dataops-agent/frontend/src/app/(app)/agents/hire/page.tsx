"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Button, Card, CardHeader, CardBody, Input, Select, Skeleton, useToast,
} from "@/components/ui";
import { EmployeeCard } from "@/components/shared/EmployeeCard";
import { EMPLOYEES } from "@/lib/employees";
import { getToken, listProjects, getSources, hireAgent, ApiError } from "@/lib/api";

export default function HireAgentPage() {
  const token = getToken() as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const initialProjectId = searchParams.get("project_id") ?? "";

  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState(initialProjectId);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [budget, setBudget] = useState("");

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });

  const projectList = projects.data?.projects ?? [];
  const sourceList = sources.data?.sources ?? [];
  const currentProjectName = useMemo(
    () => projectList.find((p) => p.id === projectId)?.name,
    [projectList, projectId]
  );

  const hireMut = useMutation({
    mutationFn: () => hireAgent(token, {
      name,
      project_id: projectId || null,
      source_ids: sourceIds,
      monthly_token_budget: budget ? Number(budget) : null,
    }),
    onSuccess: (agent) => {
      toast.push(`Hired "${agent.name}".`, "success");
      if (projectId) qc.invalidateQueries({ queryKey: ["project-agents", projectId] });
      router.push(projectId ? `/projects/${projectId}` : "/projects");
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? err.detail : null;
      toast.push(typeof detail === "string" ? detail : "Failed to hire agent.", "danger");
    },
  });

  const toggleSource = (id: string) => {
    setSourceIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));
  };

  return (
    <div>
      <div className="page-header">
        {projectId && (
          <button className="auth-link-btn text-sm" onClick={() => router.push(`/projects/${projectId}`)}>
            ← {currentProjectName ?? "Project"}
          </button>
        )}
        <h1 className="page-title" style={{ marginTop: projectId ? 4 : 0 }}>Hire an agent</h1>
        <p className="text-muted text-sm" style={{ marginTop: 6 }}>
          Only DataOps is available today — the rest are shown for context, not selectable.
        </p>
      </div>

      <div style={{ padding: "20px 24px" }}>
        <div className="grid grid-3" style={{ gap: 16, marginBottom: 20 }}>
          {EMPLOYEES.map((e) => (
            <EmployeeCard key={e.id} employee={e} />
          ))}
        </div>

        <Card>
          <CardHeader><span className="font-medium text-sm">DataOps Engineer — details</span></CardHeader>
          <CardBody className="flex flex-col gap-4">
            <Input
              id="agent-name" label="Name" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Nova" required
            />

            <Select
              id="agent-project" label="Project (optional)" value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">No project</option>
              {projectList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>

            <div className="input-group">
              <label className="input-label">Data source scope</label>
              {sources.isLoading ? (
                <Skeleton style={{ height: 60, borderRadius: 8 }} />
              ) : sourceList.length === 0 ? (
                <p className="text-muted text-sm">
                  No sources connected yet. <Link href="/sources" className="auth-link-btn">Connect one</Link> to
                  scope this agent&apos;s access — or hire now with no scope.
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {sourceList.map((s) => (
                    <label key={s.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={sourceIds.includes(s.id)}
                        onChange={() => toggleSource(s.id)}
                      />
                      {s.name}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <Input
              id="agent-budget" label="Monthly token budget (optional)" type="number" min="1"
              value={budget} onChange={(e) => setBudget(e.target.value)}
              hint="Leave blank for no agent-level limit — the tenant's own plan quota still applies."
            />

            <div className="flex justify-end">
              <Button disabled={!name.trim() || hireMut.isPending} onClick={() => hireMut.mutate()}>
                {hireMut.isPending ? "Hiring…" : "Hire"}
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
