"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Badge, Button, Input, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast } from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import { useProjectScope } from "@/lib/projectScope";
import { NoSourcesGrantedEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import { getToken, getCatalog, profileSource, type CatalogEntry } from "@/lib/api";

function matches(entry: CatalogEntry, query: string): boolean {
  if (!query.trim()) return true;
  const q = query.toLowerCase();
  return (
    entry.source_name.toLowerCase().includes(q) ||
    (entry.table_name ?? "").toLowerCase().includes(q) ||
    entry.tags.some((t) => t.toLowerCase().includes(q)) ||
    entry.columns.some((c) => (c.name ?? "").toLowerCase().includes(q))
  );
}

// Filtered copy of /catalog (Wunomo UI-rebuild slice 12, 2026-09-15) --
// same search + sync, entries scoped to this project's resolved
// sourceIds. A catalog entry is always source_id-scoped (one per table
// per source, GET /catalog's own shape) -- no unscoped case to handle,
// same reasoning as Sources itself.
export default function ProjectCatalogTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<{ current: number; total: number } | null>(null);

  const { sourceIds, loading: scopeLoading } = useProjectScope(token, projectId);
  const catalogQuery = useQuery({ queryKey: ["catalog"], queryFn: () => getCatalog(token) });
  const entries = (catalogQuery.data?.entries ?? []).filter((e) => sourceIds.has(e.source_id));
  const filtered = entries.filter((e) => matches(e, search));
  const loading = catalogQuery.isLoading || scopeLoading;

  const syncMetadata = async () => {
    const uniqueSourceIds = Array.from(new Set(entries.map((e) => e.source_id)));
    if (uniqueSourceIds.length === 0) return;
    setSyncing(true);
    for (let i = 0; i < uniqueSourceIds.length; i++) {
      setSyncProgress({ current: i + 1, total: uniqueSourceIds.length });
      try {
        await profileSource(token, uniqueSourceIds[i]);
      } catch {
        // one source failing to profile shouldn't stop the rest of the sync
      }
    }
    setSyncProgress(null);
    setSyncing(false);
    toast.push("Metadata sync complete.", "success");
    qc.invalidateQueries({ queryKey: ["catalog"] });
  };

  if (loading) return <Skeleton style={{ height: 300, borderRadius: 12 }} />;
  if (sourceIds.size === 0) return <NoSourcesGrantedEmptyState projectId={projectId} surface="the catalog" />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="flex items-center justify-between">
        <Input
          id="catalog-search" value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search tables, columns, tags…" style={{ maxWidth: 500 }}
        />
        <Button
          size="sm" variant="secondary" disabled={syncing || entries.length === 0}
          onClick={syncMetadata}
        >
          {syncing && syncProgress
            ? `Profiling ${syncProgress.current} of ${syncProgress.total}…`
            : "Sync Metadata"}
        </Button>
      </div>

      {entries.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">Nothing to catalog yet</h2>
          <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
            Profile one of this project&apos;s sources to populate the catalog with real table and
            column metadata.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">No matches</h2>
          <p className="text-muted text-sm">Try a different search term.</p>
        </div>
      ) : (
        <Card style={{ overflow: "hidden" }}>
          <Table>
            <Thead>
              <Tr><Th>Table</Th><Th>Source</Th><Th>Columns</Th><Th>Rows</Th><Th>Owner</Th><Th>Tags</Th><Th>Last Profiled</Th></Tr>
            </Thead>
            <Tbody>
              {filtered.map((e, i) => (
                <Tr key={`${e.source_id}-${e.table_name ?? i}`}>
                  <Td className="font-medium mono text-sm">
                    {e.profiled ? e.table_name : <Badge variant="warning">Not profiled</Badge>}
                  </Td>
                  <Td className="text-sm text-secondary">{e.source_name}</Td>
                  <Td className="text-sm text-secondary">{e.profiled ? e.column_count : "—"}</Td>
                  <Td className="text-sm text-secondary">{e.row_count ?? "—"}</Td>
                  <Td className="text-sm text-secondary">{e.owner ?? "—"}</Td>
                  <Td>
                    {e.tags.length === 0
                      ? <span className="text-muted text-xs">—</span>
                      : e.tags.map((t) => (
                          <Badge key={t} variant="gray" style={{ fontSize: 10, marginRight: 3 }}>{t}</Badge>
                        ))}
                  </Td>
                  <Td className="text-xs text-muted">
                    {formatApiDate(e.last_profiled_at, "Never")}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
