"use client";

import { useRouter } from "next/navigation";
import { Card, CardHeader, CardBody, Button } from "@/components/ui";
import type { RecentRun } from "@/lib/api";

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso + "Z").getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function RecentRunsCard({ runs }: { runs: RecentRun[] }) {
  const router = useRouter();
  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <span className="font-semibold text-sm">Recent Pipeline Runs</span>
        <Button variant="ghost" size="sm" onClick={() => router.push("/pipelines")}>
          View all
        </Button>
      </CardHeader>
      <CardBody style={{ padding: 0 }}>
        {runs.length === 0 ? (
          <div className="text-sm text-muted" style={{ padding: 16 }}>
            No pipeline runs yet.
          </div>
        ) : (
          runs.map((r) => (
            <div
              key={r.run_id}
              className="flex items-center gap-3"
              style={{ padding: "9px 16px", borderBottom: "1px solid var(--border)", fontSize: 12 }}
            >
              <span
                className={`status-dot ${r.status === "success" ? "success" : r.status === "failed" ? "danger" : "info"} ${r.status === "running" ? "pulse" : ""}`}
              />
              <span className="truncate font-medium" style={{ flex: 1 }}>
                {r.pipeline_name}
              </span>
              <span className="text-muted">{timeAgo(r.created_at)}</span>
              <span style={{ color: r.status === "failed" ? "var(--danger)" : "var(--text-muted)" }}>
                {r.rows_processed !== null ? `${r.rows_processed.toLocaleString()} rows` : "…"}
              </span>
            </div>
          ))
        )}
      </CardBody>
    </Card>
  );
}
