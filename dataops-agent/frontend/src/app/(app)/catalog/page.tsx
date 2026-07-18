"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Badge, Button, Input, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast } from "@/components/ui";
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

export default function CatalogPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<{ current: number; total: number } | null>(null);

  const catalogQuery = useQuery({ queryKey: ["catalog"], queryFn: () => getCatalog(token) });
  const entries = catalogQuery.data?.entries ?? [];
  const filtered = entries.filter((e) => matches(e, search));

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

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Data Catalog</h1>
          <Button
            size="sm" variant="secondary" disabled={syncing || entries.length === 0}
            onClick={syncMetadata}
          >
            {syncing && syncProgress
              ? `Profiling ${syncProgress.current} of ${syncProgress.total}…`
              : "Sync Metadata"}
          </Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
        <Input
          id="catalog-search" value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search tables, columns, tags…" style={{ maxWidth: 500 }}
        />

        {catalogQuery.isLoading ? (
          <Skeleton style={{ height: 240, borderRadius: 12 }} />
        ) : entries.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No sources to catalog yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              Add a data source, then profile it to populate the catalog with real table and
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
                      {e.last_profiled_at ? new Date(e.last_profiled_at).toLocaleString() : "Never"}
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
