// Companion to demo_reset.mjs -- restores the Employee Records source's
// real, working file_path (reversing the deliberate break), so the HR Sync
// Pipeline can be re-triggered to a real, honest success.
//
// Run:  node dataops-agent/scripts/demo_unbreak.mjs
//
// Use this between the "approve the backfill" beat and the "re-run
// succeeds" beat of the demo (see the demo script). AXIOM has no tool that
// can edit a source's connection config itself (by design -- read/diagnose/
// execute only, see CLAUDE.md), and approving a blocked action does not
// currently auto-execute it either (see CLAUDE.md's Known-broken row on
// PolicyEngine.execute_approved_action) -- so this step is the honest stand-
// in for "the data engineer applies the fix AXIOM identified." A natural
// place to make a cut in the recording, or narrate as a quick terminal beat.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATE_FILE = path.join(__dirname, ".demo_state.json");
const BASE = "http://localhost:8000/api/v1";
const EMAIL = "demo@axiom-yc.ai";
const PASSWORD = "AxiomDemo2026!";

async function j(method, urlPath, { token, body, form } = {}) {
  const headers = {};
  let payload;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${urlPath}`, { method, headers, body: payload });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  return { status: res.status, data };
}

async function main() {
  const state = JSON.parse(readFileSync(STATE_FILE, "utf8"));
  const form = new URLSearchParams({ username: EMAIL, password: PASSWORD });
  const login = await j("POST", "/auth/login", { form: { username: EMAIL, password: PASSWORD } });
  const token = login.data.access_token;

  await j("PUT", `/sources/${state.hrSourceId}`, {
    token, body: { connection_config: state.goodConnectionConfig },
  });
  console.log(`Employee Records source's file_path restored to: ${state.goodConnectionConfig.file_path}`);
  console.log(`Now go trigger the HR Sync Pipeline (${state.hrPipelineId}) -- it will succeed for real.`);
}

main().catch((e) => { console.error(e); process.exit(1); });
