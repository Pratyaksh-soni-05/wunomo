// Shared DEMO_EMAIL/DEMO_PASSWORD loader for the demo scripts in this
// directory (demo_reset.mjs, demo_check.mjs, demo_unbreak.mjs,
// demo_chat_test.mjs). Never hardcode the demo tenant's credentials --
// read them from the environment, falling back to dataops-agent/.env if
// present (this repo has no dotenv dependency installed anywhere, so this
// is a minimal manual parse, not a general-purpose .env loader).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATAOPS_ROOT = path.resolve(__dirname, ".."); // dataops-agent/

function loadEnvFallback(varNames) {
  let text;
  try { text = readFileSync(path.join(DATAOPS_ROOT, ".env"), "utf8"); } catch { return; }
  for (const line of text.split("\n")) {
    const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
    if (m && varNames.includes(m[1]) && !process.env[m[1]]) {
      process.env[m[1]] = m[2].trim();
    }
  }
}

export function getDemoCredentials() {
  loadEnvFallback(["DEMO_EMAIL", "DEMO_PASSWORD"]);
  const EMAIL = process.env.DEMO_EMAIL;
  const PASSWORD = process.env.DEMO_PASSWORD;
  if (!EMAIL || !PASSWORD) {
    console.error(
      "DEMO_EMAIL and DEMO_PASSWORD must be set -- either in the shell environment " +
      "or in dataops-agent/.env (see backend/.env.example for the placeholder keys). Refusing to run without them."
    );
    process.exit(1);
  }
  return { EMAIL, PASSWORD };
}
