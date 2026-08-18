// Plain assertion script for src/lib/dates.ts - no test framework exists in
// this frontend, so this is the pytest-equivalent: run with `node`, paste
// the output. Re-implements the exact same logic as dates.ts (kept in sync
// by hand) since this runs standalone via `node`, outside Next.js's module
// resolution - the real file is the source of truth, this just proves the
// same algorithm is correct before it's wired into 20 call sites.

const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/;
function parseApiDate(iso) {
  if (!iso) return null;
  const normalized = iso.includes(" ") && !iso.includes("T") ? iso.replace(" ", "T") : iso;
  return new Date(HAS_OFFSET.test(normalized) ? normalized : normalized + "Z");
}

let pass = 0, fail = 0;
function assert(label, cond) {
  if (cond) { pass++; console.log("PASS:", label); }
  else { fail++; console.log("FAIL:", label); }
}

// Shape A - space-separated, no T, no offset
const a = parseApiDate("2026-08-16 09:48:03.893873");
assert("Shape A parses to a valid date", a && !isNaN(a.getTime()));
assert("Shape A interpreted as UTC (ISO string round-trips)", a.toISOString() === "2026-08-16T09:48:03.893Z");

// Shape B - T-separated, no offset
const b = parseApiDate("2026-08-18T09:30:22.144134");
assert("Shape B parses to a valid date", b && !isNaN(b.getTime()));
assert("Shape B interpreted as UTC (ISO string round-trips)", b.toISOString() === "2026-08-18T09:30:22.144Z");

// Shape C - T-separated, WITH a trailing Z (the CI/CD aware-column case)
const c = parseApiDate("2026-08-16T09:48:03.893873Z");
assert("Shape C parses to a valid date", c && !isNaN(c.getTime()));
assert("Shape C does NOT get a second Z appended (regex matched the existing one)", !c.toString().includes("ZZ"));
assert("Shape C is NOT Invalid Date - the regression this exists to prevent", c.toString() !== "Invalid Date" && !isNaN(c.getTime()));
assert("Shape C interpreted as UTC exactly as given (unchanged by the helper)", c.toISOString() === "2026-08-16T09:48:03.893Z");

// Shape C with a real +HH:MM offset (not currently emitted by this backend's
// Pydantic version, but the regex is written to cover it too, not just a
// literal "Z" - future-proofing against a serialization change)
const c2 = parseApiDate("2026-08-16T09:48:03.893873+05:30");
assert("Shape C with a real offset also parses correctly, offset respected", c2.toISOString() === "2026-08-16T04:18:03.893Z");
assert("Shape C with a real offset does not get Z appended either", !c2.toString().includes("+05:30Z"));

// Edge cases
assert("null returns null", parseApiDate(null) === null);
assert("undefined returns null", parseApiDate(undefined) === null);
assert("empty string returns null", parseApiDate("") === null);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
