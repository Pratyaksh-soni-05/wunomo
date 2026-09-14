"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Modal, Button, Input, Select, Skeleton, useToast } from "@/components/ui";
import { EmployeeCard } from "@/components/shared/EmployeeCard";
import { EMPLOYEES } from "@/lib/employees";
import { hireAgent, getSources, listProjects, ApiError, type HiredAgent } from "@/lib/api";

/**
 * Extracted from the old standalone /agents/hire page (Wunomo UI-rebuild
 * slice 5, 2026-09-14) — the audit's own REBUILD correction (page -> modal,
 * matching both design previews) made real here. Two call sites: the
 * project container's header ("Hire agent", project pre-filled from
 * context) and the global /agents list ("+ Hire Agent", no project). Same
 * project Select either way, still changeable even when pre-filled -
 * matches the old page's exact behavior, not a new restriction.
 *
 * Deliberate behavior change from the old page: on success this no longer
 * navigates anywhere (the page had to - it was the whole screen; a modal
 * closing and refreshing the list it was opened over is the more modal-
 * appropriate outcome). Callers that want to navigate after a hire (e.g.
 * into the newly agent-bearing project) can do so via onHired.
 */
export function HireAgentModal({
  token, open, onClose, initialProjectId, onHired,
}: {
  token: string;
  open: boolean;
  onClose: () => void;
  initialProjectId?: string;
  onHired?: (agent: HiredAgent) => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState(initialProjectId ?? "");
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [budget, setBudget] = useState("");

  // Re-sync the pre-fill each time the modal opens -- the same instance is
  // reused across a page's lifetime, but which project (if any) it should
  // default to can change between opens (e.g. global /agents list has none,
  // a project header always has one).
  useEffect(() => {
    if (open) setProjectId(initialProjectId ?? "");
  }, [open, initialProjectId]);

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token), enabled: open });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token), enabled: open });
  const projectList = projects.data?.projects ?? [];
  const sourceList = sources.data?.sources ?? [];

  const reset = () => {
    setName("");
    setProjectId(initialProjectId ?? "");
    setSourceIds([]);
    setBudget("");
  };

  const hireMut = useMutation({
    mutationFn: () => hireAgent(token, {
      name, project_id: projectId || null, source_ids: sourceIds,
      monthly_token_budget: budget ? Number(budget) : null,
    }),
    onSuccess: (agent) => {
      toast.push(`Hired "${agent.name}".`, "success");
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["selectable-agents"] });
      if (projectId) qc.invalidateQueries({ queryKey: ["project-agents", projectId] });
      reset();
      onClose();
      onHired?.(agent);
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
    <Modal
      open={open}
      onClose={() => { reset(); onClose(); }}
      title="Hire an agent"
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={() => { reset(); onClose(); }}>Cancel</Button>
          <Button disabled={!name.trim() || hireMut.isPending} onClick={() => hireMut.mutate()}>
            {hireMut.isPending ? "Hiring…" : "Hire"}
          </Button>
        </>
      }
    >
      <p className="text-muted text-sm" style={{ marginBottom: 14 }}>
        Only DataOps is available today — the rest are shown for context, not selectable.
      </p>
      <div
        className="text-muted text-xs"
        style={{ textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10, fontWeight: 600 }}
      >
        Employee types — reference only, not clickable
      </div>
      <div className="grid grid-3" style={{ gap: 12, marginBottom: 20 }}>
        {EMPLOYEES.map((e) => (
          <EmployeeCard key={e.id} employee={e} interactive={false} />
        ))}
      </div>

      <div className="flex flex-col gap-4">
        <Input
          id="hire-agent-name" label="Name" value={name} onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Nova" required
        />

        <Select
          id="hire-agent-project" label="Project (optional)" value={projectId}
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
              No sources connected yet. <Link href="/sources" className="btn btn-text">Connect one</Link> to
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
          id="hire-agent-budget" label="Monthly token budget (optional)" type="number" min="1"
          value={budget} onChange={(e) => setBudget(e.target.value)}
          hint="Leave blank for no agent-level limit — the tenant's own plan quota still applies."
        />
      </div>
    </Modal>
  );
}
