import Link from "next/link";

// Layout-level: this project has zero agents at all. Shown instead of the
// sub-nav + any surface's own content, not per-surface -- no point
// rendering 7 empty Sources/Pipelines/Quality/... pages that all say the
// same thing (Wunomo UI-rebuild slice 6a, 2026-09-14, Q3).
export function NoAgentsEmptyState({ projectId }: { projectId: string }) {
  return (
    <div className="empty-state" style={{ gridColumn: "1 / -1" }}>
      <h2 className="font-display text-xl">No agents in this project yet</h2>
      <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
        Workbench shows what this project's agents can reach — hire one first, and its sources,
        pipelines, and everything built on them will show up here.
      </p>
      <Link href={`/projects/${projectId}/agents`} className="btn btn-primary">Go to Agents</Link>
    </div>
  );
}

// Per-surface: agents exist, but none of them have been granted a source
// yet -- a real, distinct condition from "no agents at all" (Q3). Every
// Workbench surface hits this simultaneously since they all cascade from
// the same resolved source set, so one shared message, not seven
// near-duplicate ones.
export function NoSourcesGrantedEmptyState({ projectId, surface }: { projectId: string; surface: string }) {
  return (
    <div className="empty-state">
      <h2 className="font-display text-xl">No sources granted yet</h2>
      <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
        This project&apos;s agents don&apos;t have any sources granted yet — grant one from the Agents
        tab to see {surface} here.
      </p>
      <Link href={`/projects/${projectId}/agents`} className="btn btn-primary btn-sm">Go to Agents</Link>
    </div>
  );
}
