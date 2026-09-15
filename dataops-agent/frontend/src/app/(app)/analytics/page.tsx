import { RetiredRouteRedirect } from "@/components/shell";

// Retired as a stub, not as a decision that analytics itself is
// unwanted (slice 12, 2026-09-15) -- a full backend already exists
// unused behind this route (overview, recent-runs, pipelines, quality,
// KPI GET+POST, usage, a typed client already in lib/api.ts). Logged as
// findings item 101 so that real, already-built surface doesn't get
// silently forgotten just because the stub in front of it is gone --
// building the real screen is its own slice, not this one.
export default function RetiredAnalyticsPage() {
  return (
    <RetiredRouteRedirect
      label="Analytics"
      message="Analytics isn't available in this interface yet."
      to="/home"
    />
  );
}
