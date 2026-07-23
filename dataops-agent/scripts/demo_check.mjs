// Read-only sanity check of the demo tenant's current state (dashboard KPIs,
// incidents, quality, lineage/governance). Run after demo_reset.mjs.
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
  const { data: login } = await j("POST", "/auth/login", { form: { username: EMAIL, password: PASSWORD } });
  const token = login.access_token;
  console.log("tenant_id:", login.tenant_id);

  const { data: analytics } = await j("GET", "/analytics/", { token });
  console.log("\n=== /analytics ===\n", JSON.stringify(analytics, null, 2));

  const { data: quality } = await j("GET", "/analytics/quality", { token });
  console.log("\n=== /analytics/quality ===\n", JSON.stringify(quality, null, 2));

  const { data: recentRuns } = await j("GET", "/analytics/recent-runs", { token });
  console.log("\n=== /analytics/recent-runs ===\n", JSON.stringify(recentRuns, null, 2));

  const { data: incidents } = await j("GET", "/incidents/?status=open", { token });
  console.log("\n=== /incidents?status=open ===\n", JSON.stringify(incidents, null, 2));

  const { data: approvalsMerged } = await j("GET", "/approvals/merged", { token });
  console.log("\n=== /approvals/merged ===\n", JSON.stringify(approvalsMerged, null, 2));

  const { data: graph } = await j("GET", "/governance/graph", { token });
  console.log("\n=== /governance/graph (node/edge count) ===\n",
    JSON.stringify({ nodes: (graph.nodes || []).length, edges: (graph.edges || []).length }));
}

main().catch((e) => { console.error(e); process.exit(1); });
