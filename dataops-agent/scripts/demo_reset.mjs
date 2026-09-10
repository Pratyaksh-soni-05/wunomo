// One-command reset for the YC demo tenant.
//
// Run:  node dataops-agent/scripts/demo_reset.mjs
//
// Idempotent — safe to re-run any number of times. Always leaves the same
// fixed tenant (email/password below) in exactly this state:
//   - Source "Sales Orders" (CSV, healthy) -> Pipeline "Sales Ingestion
//     Pipeline" (ACTIVE, 2 real successful runs, 1 real passing quality rule)
//   - Source "Employee Records" (CSV) -> Pipeline "HR Sync Pipeline":
//     triggered once successfully, then the source's file_path is broken via
//     a real PUT /sources/{id} call (same path a user would use), then
//     triggered again -> a real FAILED run with a real "File not found"
//     error message.
//   - Exactly ONE open Incident, logged via the real POST /incidents/
//     endpoint against that failed run (the freshness-checker's duplicate-
//     incident bug is a known, separate issue -- this bypasses it by never
//     relying on the freshness checker to create the incident at all).
//
// Uses only real HTTP calls against the running backend for all product
// state (nothing is written directly into product tables) -- the only
// direct-DB step is wiping this one dedicated tenant's child rows before
// rebuilding, for tables with no REST "delete all" endpoint (incidents,
// chat messages, approvals, lineage, audit log).

import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", ".."); // ai workforce/
const DATAOPS_ROOT = path.resolve(__dirname, ".."); // dataops-agent/
const STATE_FILE = path.join(__dirname, ".demo_state.json");

const BASE = "http://localhost:8000/api/v1";
const EMAIL = "demo@axiom-yc.ai";
const PASSWORD = "AxiomDemo2026!";
const TENANT_NAME = "AXIOM YC Demo";
const FULL_NAME = "Demo Owner";

const SALES_CSV = path.join(REPO_ROOT, "sales_data.csv");
const EMPLOYEE_CSV = path.join(REPO_ROOT, "employee_data.csv");

function b64urlDecode(seg) {
  seg = seg.replace(/-/g, "+").replace(/_/g, "/");
  while (seg.length % 4) seg += "=";
  return Buffer.from(seg, "base64").toString("utf8");
}

function decodeJwt(token) {
  const [, payload] = token.split(".");
  return JSON.parse(b64urlDecode(payload));
}

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

async function uploadRegister(token, filePath, name) {
  const buf = readFileSync(filePath);
  const fd = new FormData();
  fd.append("file", new Blob([buf]), path.basename(filePath));
  fd.append("name", name);
  const res = await fetch(`${BASE}/uploads/register`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  });
  const data = await res.json();
  if (res.status >= 300) throw new Error(`upload/register failed for ${name}: ${res.status} ${JSON.stringify(data)}`);
  return data;
}

function psql(sql) {
  const r = spawnSync(
    "docker",
    ["compose", "exec", "-T", "postgres", "psql", "-U", "dataops_user", "-d", "dataops", "-v", "ON_ERROR_STOP=1", "-c", sql],
    { cwd: DATAOPS_ROOT, encoding: "utf8" }
  );
  if (r.status !== 0) {
    throw new Error(`psql failed:\n${r.stdout}\n${r.stderr}`);
  }
  return r.stdout;
}

async function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function pollRunStatus(token, pipelineId, runId, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const { data } = await j("GET", `/pipelines/${pipelineId}/runs?limit=20`, { token });
    const runs = data.runs || data || [];
    const run = (Array.isArray(runs) ? runs : []).find((r) => r.id === runId);
    if (run && run.status && run.status !== "pending" && run.status !== "running") {
      return run;
    }
    await sleep(1000);
  }
  throw new Error(`Timed out waiting for run ${runId} to finish`);
}

async function main() {
  console.log("== AXIOM YC demo reset ==");

  // 1. Get a token: try login first, register only if this is truly the first run.
  let token, tenantId;
  {
    const { status, data } = await j("POST", "/auth/login", {
      form: { username: EMAIL, password: PASSWORD },
    });
    if (status === 200 && data.access_token) {
      token = data.access_token;
      tenantId = data.tenant_id;
      console.log(`Existing tenant found: ${tenantId}`);
    } else if (status === 200 && data.status === "choose_workspace") {
      throw new Error("Multiple workspaces matched this demo email -- unexpected, investigate manually.");
    } else {
      console.log("No existing tenant for this email -- registering fresh.");
      const reg = await j("POST", "/auth/register", {
        body: { email: EMAIL, password: PASSWORD, full_name: FULL_NAME, tenant_name: TENANT_NAME },
      });
      if (reg.status >= 300) throw new Error(`register failed: ${JSON.stringify(reg.data)}`);
      token = reg.data.access_token;
      tenantId = reg.data.tenant_id;
      console.log(`Registered new tenant: ${tenantId}`);
    }
  }

  // 1a. Complete onboarding every reset -- a fresh/API-registered tenant
  // has no OnboardingProfile, so the real app correctly redirects login to
  // /onboarding instead of /dashboard. The demo must land on /dashboard.
  await j("POST", "/onboarding/", {
    token,
    body: {
      role: "Data Engineering Lead", industry: "SaaS", company_size: "11-50",
      use_cases: ["Pipeline monitoring", "Data quality"], data_stack: ["Postgres", "CSV/Excel"],
    },
  });

  // 1b. Force the plan to "scale" every reset. A single multi-tool-call
  // AXIOM conversation costs ~25k-30k AI credits (every LLM call in a
  // tool-calling turn resends the full system prompt + all 38 tool schemas
  // as input tokens, and the credit formula weights output tokens 3x) --
  // Starter's 25,000/mo default limit was found live to be exhausted by
  // just 2 chat turns during demo-script verification. "scale" (500,000/mo)
  // gives real headroom for repeated rehearsals plus the final recording.
  // This is a real, supported product action (POST /billing/change-plan),
  // not a workaround -- see CLAUDE.md's Known-broken row on unconditional
  // plan changes (harmless here, this is an upgrade with real spare quota).
  await j("POST", "/billing/change-plan", { token, body: { plan: "scale" } });
  console.log("Set plan to scale (500,000 AI credits/mo) so rehearsals don't hit a quota wall.");

  // 2. Wipe this tenant's product data via the real endpoints first (handles
  // FK cleanup correctly, same as a real user deleting things), then a raw
  // SQL sweep for the tables with no REST delete-all endpoint.
  {
    const { data: pipelines } = await j("GET", "/pipelines/", { token });
    const pipelineList = pipelines.pipelines || pipelines || [];
    for (const p of Array.isArray(pipelineList) ? pipelineList : []) {
      await j("DELETE", `/pipelines/${p.id}`, { token });
    }
    const { data: sources } = await j("GET", "/sources/", { token });
    const sourceList = sources.sources || sources || [];
    for (const s of Array.isArray(sourceList) ? sourceList : []) {
      await j("DELETE", `/sources/${s.id}`, { token });
    }
    // task_steps must go first: it's the only table with a live FK onto
    // either tasks (task_id, NOT NULL) or approval_requests
    // (approval_request_id, nullable) -- Tasks postdates when this sweep
    // was written, so it was never added here, and a task_steps row left
    // behind is exactly what made "DELETE FROM approval_requests" fail
    // with task_steps_approval_request_id_fkey the moment any walkthrough
    // on this tenant ever produced an approval-gated task step.
    psql(
      `DELETE FROM task_steps WHERE task_id IN (SELECT id FROM tasks WHERE tenant_id = '${tenantId}');
       DELETE FROM tasks WHERE tenant_id = '${tenantId}';
       DELETE FROM chat_messages WHERE tenant_id = '${tenantId}';
       DELETE FROM approval_requests WHERE tenant_id = '${tenantId}';
       DELETE FROM transform_runs WHERE tenant_id = '${tenantId}';
       DELETE FROM audit_logs WHERE tenant_id = '${tenantId}';
       DELETE FROM lineage_edges WHERE tenant_id = '${tenantId}';
       DELETE FROM lineage_nodes WHERE tenant_id = '${tenantId}';
       DELETE FROM incidents WHERE tenant_id = '${tenantId}';`
    );
    console.log("Wiped prior demo state for this tenant.");
  }

  // 3. Rebuild: healthy pipeline first.
  const salesSource = await uploadRegister(token, SALES_CSV, "Sales Orders");
  await j("POST", `/sources/${salesSource.source_id}/profile`, { token });

  const { data: salesPipeline } = await j("POST", "/pipelines/", {
    token,
    body: { name: "Sales Ingestion Pipeline", source_id: salesSource.source_id, description: "Daily sales order ingestion" },
  });
  const salesPipelineId = salesPipeline.id || salesPipeline.pipeline_id;

  await j("POST", "/quality/", {
    token,
    body: {
      pipeline_id: salesPipelineId,
      name: "order_id_not_null",
      rule_type: "not_null",
      column_name: "order_id",
      severity: "high",
      is_blocking: true,
    },
  });

  // Two real successful runs for run-history depth.
  for (let i = 0; i < 2; i++) {
    const { data: trig } = await j("POST", `/pipelines/${salesPipelineId}/trigger`, { token });
    const runId = trig.id || trig.run_id;
    if (runId) {
      try { await pollRunStatus(token, salesPipelineId, runId); } catch (e) { console.warn(e.message); }
    }
  }
  console.log(`Sales Ingestion Pipeline ready: ${salesPipelineId}`);

  // 4. HR pipeline: healthy first, then broken.
  const hrSource = await uploadRegister(token, EMPLOYEE_CSV, "Employee Records");
  await j("POST", `/sources/${hrSource.source_id}/profile`, { token });

  const { data: hrPipeline } = await j("POST", "/pipelines/", {
    token,
    body: { name: "HR Sync Pipeline", source_id: hrSource.source_id, description: "Nightly HR roster sync" },
  });
  const hrPipelineId = hrPipeline.id || hrPipeline.pipeline_id;

  const { data: goodTrig } = await j("POST", `/pipelines/${hrPipelineId}/trigger`, { token });
  if (goodTrig.id || goodTrig.run_id) {
    try { await pollRunStatus(token, hrPipelineId, goodTrig.id || goodTrig.run_id); } catch (e) { console.warn(e.message); }
  }
  console.log(`HR Sync Pipeline established as healthy first: ${hrPipelineId}`);

  // Break it -- honest failure, via the real PUT /sources/{id} endpoint,
  // same path a real user would use to edit a source's connection.
  const { data: hrSourceFull } = await j("GET", `/sources/${hrSource.source_id}`, { token });
  const brokenConfig = { ...hrSourceFull.connection_config, file_path: "/root/dataops_uploads/employee_data_MISSING.csv" };
  await j("PUT", `/sources/${hrSource.source_id}`, { token, body: { connection_config: brokenConfig } });
  console.log("Broke Employee Records source: file_path now points at a nonexistent file.");

  const { data: badTrig } = await j("POST", `/pipelines/${hrPipelineId}/trigger`, { token });
  const badRunId = badTrig.id || badTrig.run_id;
  let failedRun = null;
  if (badRunId) {
    failedRun = await pollRunStatus(token, hrPipelineId, badRunId);
  }
  console.log(`HR Sync Pipeline failed run: ${badRunId} -> status=${failedRun && failedRun.status}`);
  console.log(`  error: ${failedRun && failedRun.error_message}`);

  // 5. Log exactly one real incident against this failure.
  const { data: incident } = await j("POST", "/incidents/", {
    token,
    body: {
      title: "HR Sync Pipeline failed — source file not found",
      description: `HR Sync Pipeline's run ${badRunId} failed: ${failedRun ? failedRun.error_message : "source sync failed"}. The Employee Records source's file_path appears to have been changed or the file removed.`,
      severity: "high",
      pipeline_id: hrPipelineId,
    },
  });
  console.log(`Logged incident: ${incident.id} (status=${incident.status})`);

  // Save the pre-break good config so demo_unbreak.mjs can restore exactly
  // this path (not guess it) when it's time to show a real corrected re-run.
  writeFileSync(STATE_FILE, JSON.stringify({
    tenantId, hrSourceId: hrSource.source_id, hrPipelineId,
    goodConnectionConfig: hrSourceFull.connection_config,
  }, null, 2));

  console.log("\n== Demo state ready ==");
  console.log(`Tenant:        ${TENANT_NAME}  (${tenantId})`);
  console.log(`Login email:   ${EMAIL}`);
  console.log(`Login password:${PASSWORD}`);
  console.log(`Healthy pipeline: Sales Ingestion Pipeline  (${salesPipelineId})`);
  console.log(`Broken pipeline:  HR Sync Pipeline  (${hrPipelineId})`);
  console.log(`Broken source:    Employee Records  (${hrSource.source_id})`);
  console.log(`Open incident:    ${incident.id}`);
  console.log("\nFrontend: http://localhost:3000/login");
}

main().catch((err) => {
  console.error("DEMO RESET FAILED:", err);
  process.exit(1);
});
