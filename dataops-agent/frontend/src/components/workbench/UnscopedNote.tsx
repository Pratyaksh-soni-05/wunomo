// Always-visible muted note for the Pipelines/Incidents/Transforms
// Workbench sub-pages (Wunomo UI-rebuild slice 6b, 2026-09-14) -- the
// two-tier "Unscoped" treatment approved for the exceptions Sources/
// Quality/CI-CD don't have (a pipeline/incident/transform run with no
// source_id or pipeline_id can never resolve into any project's scope,
// regardless of which project is asking). Always rendered, not only when
// count > 0 -- a silently-absent section reads as "nothing to see," which
// is indistinguishable from "this project just has none," the exact
// ambiguity the two-tier design was meant to remove.
export function UnscopedNote({
  loading, count, itemLabel,
}: { loading: boolean; count: number; itemLabel: string }) {
  return (
    <p className="text-muted text-xs" style={{ marginTop: 14 }}>
      {loading
        ? "Checking for unscoped items…"
        : count > 0
        ? `+ ${count} ${itemLabel}${count === 1 ? "" : "s"} not tied to any project.`
        : `No ${itemLabel}s outside a project.`}
    </p>
  );
}
