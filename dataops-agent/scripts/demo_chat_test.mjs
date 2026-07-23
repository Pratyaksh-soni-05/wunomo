// Ad-hoc live chat test harness for demo-script verification.
// Usage: node demo_chat_test.mjs "<message>" [personality] [operation] [sessionId]
const BASE = "http://localhost:8000/api/v1";
const EMAIL = "demo@axiom-yc.ai";
const PASSWORD = "AxiomDemo2026!";

async function main() {
  const [, , message, personality = "engineer", operation = "assisted", sessionId] = process.argv;
  if (!message) { console.error("usage: node demo_chat_test.mjs <message> [personality] [operation] [sessionId]"); process.exit(1); }

  const form = new URLSearchParams({ username: EMAIL, password: PASSWORD });
  const loginRes = await fetch(`${BASE}/auth/login`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form });
  const login = await loginRes.json();
  const token = login.access_token;

  const t0 = Date.now();
  const res = await fetch(`${BASE}/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      message,
      personality_mode: personality,
      operation_mode: operation,
      session_id: sessionId || undefined,
    }),
  });
  const data = await res.json();
  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

  console.log(`status: ${res.status}   elapsed: ${elapsed}s`);
  console.log(`provider: ${data.provider}`);
  console.log(`session_id: ${data.session_id}`);
  console.log(`\n--- response ---\n${data.response}`);
  console.log(`\n--- tool_calls (${(data.tool_calls || []).length}) ---`);
  for (const tc of data.tool_calls || []) {
    console.log(`  [${tc.status}] ${tc.tool}(${JSON.stringify(tc.args)})`);
    if (tc.result) console.log(`      -> ${JSON.stringify(tc.result).slice(0, 300)}`);
  }
  console.log(`\n--- pending_approvals (${(data.pending_approvals || []).length}) ---`);
  for (const pa of data.pending_approvals || []) {
    console.log(`  ${JSON.stringify(pa)}`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
