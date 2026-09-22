"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, Badge, Skeleton, Table, Thead, Tbody, Tr, Th, Td } from "@/components/ui";
import { useProjectScope } from "@/lib/projectScope";
import { NoSourcesGrantedEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import { getToken, getPipelines, getLineageGraph, type LineageNode, type PipelineItem } from "@/lib/api";

// New in slice 6b (2026-09-14) -- "lineage by convention," per the audit:
// every node/edge here comes from LineageTracker.sync_tenant_lineage()
// (backend/modules/governance/lineage_tracker.py), which derives the whole
// graph from DataSource/Pipeline registration metadata on every read, not
// from tracing real query-level column lineage. No tool exposed to the
// agent (agent/tools/governance_tools.py) ever writes a node either -- the
// two manual POST /lineage/node|edge endpoints exist but nothing in this
// UI calls them. So every node this page can show is, by construction,
// auto-derived -- checked per node via metadata.auto rather than assumed,
// so a real non-auto node (created by hand through the API) would still
// read correctly if one ever existed.
//
// A pipeline with no source_id gets only a bare, edge-less node from
// sync_tenant_lineage's own logic (its else-branch skips
// auto_register_pipeline_lineage entirely) -- that's "Unresolved," not a
// UI state invented here, it's what the backend actually produces.
//
// Important structural consequence: useProjectScope's pipelineIds only
// ever contains pipelines that HAVE a source_id in this project's resolved
// set (lib/projectScope.ts's own filter). So a project's own pipeline list
// can never actually produce "Unresolved" -- every one always resolves,
// always reads Approximate. That's correct, not a bug, but it also means
// "Unresolved" needs a real place to ever appear: Lineage gets the same
// two-tier unscoped treatment as Pipelines/Incidents/Transforms below --
// an unscoped (manual, no-source) pipeline is exactly the case that hits
// sync_tenant_lineage's bare-node branch, so it's the one real, reachable
// source of "Unresolved" data, not a fabricated UI state.
function findPipelineNode(nodes: LineageNode[], pipelineId: string): LineageNode | undefined {
  return nodes.find((n) => n.node_type === "pipeline" && n.metadata?.pipeline_id === pipelineId);
}

function resolveRow(p: PipelineItem, nodes: LineageNode[], edges: { edge_id: string; upstream_id: string; downstream_id: string }[]) {
  const node = findPipelineNode(nodes, p.id);
  if (!node) return { pipeline: p, upstream: null as string | null, downstream: null as string | null, resolved: false, approximate: false };
  const upstreamEdge = edges.find((e) => e.downstream_id === node.id);
  const downstreamEdge = edges.find((e) => e.upstream_id === node.id);
  const upstream = upstreamEdge ? nodes.find((n) => n.id === upstreamEdge.upstream_id) : undefined;
  const downstream = downstreamEdge ? nodes.find((n) => n.id === downstreamEdge.downstream_id) : undefined;
  return {
    pipeline: p,
    upstream: upstream?.name ?? null,
    downstream: downstream?.name ?? null,
    resolved: !!upstreamEdge,
    approximate: node.metadata?.auto === true,
  };
}

function LineageTable({ rows }: { rows: ReturnType<typeof resolveRow>[] }) {
  return (
    <Table>
      <Thead>
        <Tr>
          <Th>Source</Th>
          <Th>Pipeline</Th>
          <Th>Output</Th>
          <Th>Status</Th>
        </Tr>
      </Thead>
      <Tbody>
        {rows.map(({ pipeline, upstream, downstream, resolved, approximate }) => (
          <Tr key={pipeline.id}>
            <Td>{upstream ?? "—"}</Td>
            <Td>{pipeline.name}</Td>
            <Td>{downstream ?? "—"}</Td>
            <Td>
              {resolved ? (
                <Badge variant={approximate ? "gray" : "info"}>
                  {approximate ? "Approximate" : "Resolved"}
                </Badge>
              ) : (
                <Badge variant="warning">Unresolved</Badge>
              )}
            </Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

export default function ProjectLineageTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;

  const { sourceIds, pipelineIds, loading: scopeLoading } = useProjectScope(token, projectId);
  const pipelinesQuery = useQuery({ queryKey: ["pipelines"], queryFn: () => getPipelines(token) });
  const unscopedQuery = useQuery({ queryKey: ["pipelines", "unscoped"], queryFn: () => getPipelines(token, { unscoped: true }) });
  const graphQuery = useQuery({ queryKey: ["lineage-graph"], queryFn: () => getLineageGraph(token) });

  const loading = scopeLoading || pipelinesQuery.isLoading || unscopedQuery.isLoading || graphQuery.isLoading;
  const projectPipelines = (pipelinesQuery.data?.pipelines ?? []).filter((p) => pipelineIds.has(p.id));
  const unscopedPipelines = unscopedQuery.data?.pipelines ?? [];
  const nodes = graphQuery.data?.nodes ?? [];
  const edges = graphQuery.data?.edges ?? [];

  if (loading) return <Skeleton style={{ height: 300, borderRadius: 12 }} />;
  if (sourceIds.size === 0) return <NoSourcesGrantedEmptyState projectId={projectId} surface="lineage" />;

  const projectRows = projectPipelines.map((p) => resolveRow(p, nodes, edges));
  const unscopedRows = unscopedPipelines.map((p) => resolveRow(p, nodes, edges));

  return (
    <div>
      <p className="text-muted text-sm" style={{ marginBottom: 16 }}>
        Derived from source/pipeline registration, not real query-level tracing — treat as
        approximate.
      </p>

      {projectRows.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">No pipelines to trace yet</h2>
          <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
            Lineage traces this project&apos;s pipelines back to their source and forward to their
            output — create a pipeline first.
          </p>
        </div>
      ) : (
        <Card>
          <LineageTable rows={projectRows} />
        </Card>
      )}

      <p className="text-muted text-xs" style={{ marginTop: 14, marginBottom: 8 }}>
        {unscopedRows.length > 0
          ? `+ ${unscopedRows.length} unscoped pipeline${unscopedRows.length === 1 ? "" : "s"} — no source, so lineage can't resolve.`
          : "No unscoped pipelines."}
      </p>
      {unscopedRows.length > 0 && (
        <Card>
          <LineageTable rows={unscopedRows} />
        </Card>
      )}
    </div>
  );
}
