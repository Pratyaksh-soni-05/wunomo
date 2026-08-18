// Item 22: rendering honors the workspace's configured IANA timezone
// (Settings > Workspace), falling back to the browser's own detected zone
// until one has ever been saved - see lib/timezone.ts.
import { getStoredTimezone } from "./timezone";

// This project's own backend emits three distinct raw timestamp shapes for
// what is, in every case, a UTC value with no local-timezone meaning of its
// own - see CLAUDE.md Hard Rule 3 and docs/context/GOTCHAS.md for the full
// history. Confirmed live, 2026-08-19, not assumed:
//
//   Shape A - "2026-08-16 09:48:03.893873"      (space, no T, no offset)
//     A manual str(datetime) on a naive column - e.g. api/v1/chat.py's
//     "last_activity": str(row.last_activity).
//   Shape B - "2026-08-18T09:30:22.144134"       (T, no offset)
//     Pydantic auto-serializing a naive-column datetime field.
//   Shape C - "2026-08-16T09:48:03.893873Z"      (T, WITH a trailing Z)
//     Pydantic auto-serializing an AWARE-column datetime field - today
//     that's exactly PipelineCommit.trigger_time and
//     PipelineDeployment.deployed_at, the two Hard-Rule-3 CI/CD exception
//     columns that are genuinely timezone-aware on purpose. Confirmed via a
//     direct pydantic.BaseModel serialization test: an aware UTC datetime
//     renders as "...Z", not "...+00:00".
//
// Shapes A and B are indistinguishable from "just a UTC value with the
// marker stripped" - both need a "Z" appended before new Date() will parse
// them as UTC instead of silently assuming the browser's local timezone.
// Shape C already has its offset marker. Appending "Z" to it produces
// "...893873ZZ", which new Date() turns into a silent Invalid Date - not an
// error, just a broken CI/CD timestamp with no signal anything went wrong.
//
// DO NOT simplify this to "always append Z". That is the exact regression
// that would silently break every CI/CD commit/deployment timestamp on this
// page - re-read the Shape C paragraph above first.
const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/;

/**
 * Parses a raw timestamp string from this backend's API into a real, UTC-
 * correct Date - handling all three shapes described above. Returns null
 * for a missing/empty input, matching the many call sites that render a
 * fallback ("Never", "—", etc.) instead of a formatted date.
 */
export function parseApiDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const normalized = iso.includes(" ") && !iso.includes("T") ? iso.replace(" ", "T") : iso;
  return new Date(HAS_OFFSET.test(normalized) ? normalized : normalized + "Z");
}

/**
 * Full date + time, in the workspace's configured timezone (Settings >
 * Workspace, item 22) - falls back to the browser's own detected zone
 * until one has ever been saved. An invalid/unrecognized IANA name (should
 * never happen via the Settings dropdown, but not impossible via a raw API
 * call) makes toLocaleString throw - caught here so a bad stored value
 * degrades to the browser's default zone instead of blanking the whole page.
 */
export function formatApiDate(iso: string | null | undefined, fallback = "—"): string {
  const d = parseApiDate(iso);
  if (!d || isNaN(d.getTime())) return fallback;
  try {
    return d.toLocaleString(undefined, { timeZone: getStoredTimezone() });
  } catch {
    return d.toLocaleString();
  }
}

/** Date only (no time), in the workspace's configured timezone - see formatApiDate. */
export function formatApiDateOnly(iso: string | null | undefined, fallback = "—"): string {
  const d = parseApiDate(iso);
  if (!d || isNaN(d.getTime())) return fallback;
  try {
    return d.toLocaleDateString(undefined, { timeZone: getStoredTimezone() });
  } catch {
    return d.toLocaleDateString();
  }
}
