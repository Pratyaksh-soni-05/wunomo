// Item 22 (2026-08 walkthrough): the workspace's configured IANA timezone,
// applied to every formatApiDate/formatApiDateOnly call (see dates.ts) -
// same "localStorage fast path + server reconciliation" pattern theme.ts
// already uses, since both are read synchronously from many places that
// can't all await a settings fetch first.

const STORAGE_KEY = "axiom_workspace_tz";

// A representative, curated list rather than the full ~400-zone IANA
// database - covers every major region/offset without forcing the dropdown
// into an unusable wall of "America/Indiana/Petersburg"-style entries.
export const TIMEZONE_OPTIONS: string[] = [
  "UTC",
  "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York",
  "America/Anchorage", "America/Sao_Paulo", "America/Mexico_City", "America/Toronto",
  "Europe/London", "Europe/Dublin", "Europe/Lisbon", "Europe/Paris", "Europe/Berlin",
  "Europe/Madrid", "Europe/Rome", "Europe/Amsterdam", "Europe/Warsaw", "Europe/Athens",
  "Europe/Moscow", "Europe/Istanbul",
  "Africa/Cairo", "Africa/Johannesburg", "Africa/Lagos", "Africa/Nairobi",
  "Asia/Dubai", "Asia/Karachi", "Asia/Kolkata", "Asia/Dhaka", "Asia/Bangkok",
  "Asia/Jakarta", "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Tokyo",
  "Asia/Seoul", "Asia/Manila",
  "Australia/Perth", "Australia/Adelaide", "Australia/Sydney", "Australia/Brisbane",
  "Pacific/Auckland", "Pacific/Honolulu",
];

export function detectBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// If the detected zone isn't already one of the curated options (e.g. a
// more specific city variant), add it so a first-time default never
// silently falls back to something the user didn't pick.
export function timezoneOptionsWithDetected(): string[] {
  const detected = detectBrowserTimezone();
  return TIMEZONE_OPTIONS.includes(detected) ? TIMEZONE_OPTIONS : [detected, ...TIMEZONE_OPTIONS];
}

export function applyTimezone(tz: string) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, tz);
  } catch {
    // localStorage unavailable (private mode, etc.) - falls back to browser
    // detection for this load, same graceful degradation as theme.ts.
  }
}

// Falls back to the browser's own detected zone until a workspace value has
// ever been saved/reconciled - this is the "correct according to the
// machine's timezone" default the finding asked for.
export function getStoredTimezone(): string {
  if (typeof window === "undefined") return "UTC";
  try {
    return localStorage.getItem(STORAGE_KEY) || detectBrowserTimezone();
  } catch {
    return detectBrowserTimezone();
  }
}
