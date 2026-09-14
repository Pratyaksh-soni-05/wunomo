"use client";

import { useQuery, useQueries } from "@tanstack/react-query";
import { getProjectAgents, getAgentSources, getPipelines } from "./api";

/**
 * The Option B resolver (Wunomo UI-rebuild slice 6a, 2026-09-14) —
 * project_agents -> agents -> agent_sources, per
 * docs/design/UI_REBUILD_INVENTORY.md §2. Every Workbench surface that
 * needs "this project's sources/pipelines" reads from here, not its own
 * copy of the join.
 *
 * Deliberately NOT exclusive: this hook only ever reads FROM this
 * project's own agents (project_agents scoped to `projectId`) and each of
 * THEIR OWN granted sources (agent_sources keyed by agent_id, not by
 * project) — there is no step anywhere that could filter a source out for
 * being "claimed" by another project, because nothing here ever looks at
 * another project at all. Two different projects whose agents each hold a
 * grant on the same source will each independently resolve to include
 * it — verified live, not just reasoned about (see slice 6a's
 * verification notes): a source shared between two different agents in
 * two different projects shows up in both.
 *
 * Pipeline resolution is derived, not a second independent join: a
 * pipeline belongs to this project's scope only if its own source_id is
 * in the resolved source set (a pipeline with no source_id at all -- a
 * manual pipeline -- can never resolve into any project; that's the
 * "Unscoped" case, handled by the two surfaces that need it, not by this
 * hook pretending it belongs somewhere).
 */
export function useProjectScope(token: string, projectId: string) {
  const agentsQuery = useQuery({
    queryKey: ["project-agents", projectId],
    queryFn: () => getProjectAgents(token, projectId),
  });
  const agents = agentsQuery.data?.agents ?? [];

  const sourceQueries = useQueries({
    queries: agents.map((a) => ({
      queryKey: ["agent-sources", a.id],
      queryFn: () => getAgentSources(token, a.id),
    })),
  });
  const sourcesLoading = agents.length > 0 && sourceQueries.some((q) => q.isLoading);
  const sourceIds = new Set(sourceQueries.flatMap((q) => (q.data?.sources ?? []).map((s) => s.id)));

  // Tenant-wide list, no scoped pipelines endpoint exists -- filtered
  // client-side against the resolved source set, same reasoning as
  // everything else in this hook.
  const pipelinesQuery = useQuery({ queryKey: ["pipelines"], queryFn: () => getPipelines(token) });
  const pipelineIds = new Set(
    (pipelinesQuery.data?.pipelines ?? [])
      .filter((p) => p.source_id && sourceIds.has(p.source_id))
      .map((p) => p.id)
  );

  return {
    agentCount: agents.length,
    sourceIds,
    pipelineIds,
    loading: agentsQuery.isLoading || sourcesLoading || pipelinesQuery.isLoading,
  };
}
