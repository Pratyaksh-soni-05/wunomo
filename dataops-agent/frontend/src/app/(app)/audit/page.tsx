import { RetiredRouteRedirect } from "@/components/shell";

// Was always a StubPage with nothing behind it -- superseded, not just
// retired, now that the real Audit Log (moved from Governance) lives in
// Settings (slice 12, 2026-09-15). Two orphaned destinations for the
// same concept would have been a worse outcome than one real one.
export default function RetiredAuditPage() {
  return (
    <RetiredRouteRedirect
      label="Audit Logs"
      message="Audit Log is now a tab in Settings."
      to="/settings?tab=audit-log"
    />
  );
}
