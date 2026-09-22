import { RetiredRouteRedirect } from "@/components/shell";

// Slice 12 (2026-09-15): fully retired, not just Lineage this time.
// Contracts moved into each project's Workbench (source-scoped, same as
// Sources); Audit Log moved into Settings (tenant-wide by nature, same
// reasoning as every other admin-facing Settings tab). Two different
// real destinations for what used to be one page -- redirects to
// Settings since Audit Log needs no project context, Contracts does.
export default function RetiredGovernancePage() {
  return (
    <RetiredRouteRedirect
      label="Governance"
      message="Governance has moved: Contracts now live in each project's Workbench, Audit Log is a tab in Settings."
      to="/settings?tab=audit-log"
    />
  );
}
