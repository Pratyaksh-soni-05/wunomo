"use client";

// DESIGN_SPEC.md §7.4 / §3 "Employee avatar" -- replaces .chat-avatar (a
// single fixed 28px AXIOM icon, the old single-agent assumption) across
// every consumer. --c resolves from tokens.css's per-employee-type hue
// classes (.c-dataops etc.), keyed directly off AgentEmployeeType's own
// value -- AgentEmployeeType has exactly one real member ("dataops")
// today, but this reads the value itself rather than a hardcoded lookup
// table, so it needs no change the day a second type actually ships.
// AXIOM (the pre-agents default identity) is treated as a dataops
// employee named "AXIOM" -- it always was one, just never had a tile.

export type AvatarSize = "sm" | "default" | "lg";

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function employeeHueClass(employeeType?: string | null): string {
  return `c-${employeeType || "dataops"}`;
}

export function EmployeeAvatar({
  name,
  employeeType,
  size = "default",
  isWorking = false,
  title,
}: {
  name: string;
  // Null/undefined (no resolved agent identity for this message -- see
  // ChatMessageItem.agent_id's own comment) falls back to the dataops
  // hue rather than rendering an unstyled tile with no --c at all.
  employeeType?: string | null;
  size?: AvatarSize;
  // Wraps in .is-working -- tokens.css's `.is-working .avatar` selector
  // (the wunomo-pulse keyframe) keys off exactly this structure, a
  // descendant combinator, not a class on the tile itself.
  isWorking?: boolean;
  title?: string;
}) {
  const sizeClass = size === "sm" ? "avatar-sm" : size === "lg" ? "avatar-lg" : "";
  return (
    <div className={["avatar-wrap", isWorking ? "is-working" : ""].filter(Boolean).join(" ")}>
      <div
        className={["avatar", sizeClass, employeeHueClass(employeeType)].filter(Boolean).join(" ")}
        title={title ?? name}
      >
        {initialsFromName(name)}
      </div>
    </div>
  );
}
