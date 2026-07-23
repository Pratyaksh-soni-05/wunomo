// Playwright walkthrough of the demo tenant against the production build.
// Screenshots + console-error capture for every screen the demo touches.
import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, "walkthrough_shots");
fs.mkdirSync(OUT_DIR, { recursive: true });

const EMAIL = "demo@axiom-yc.ai";
const PASSWORD = "AxiomDemo2026!";

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[console] ${msg.text()}`);
  });
  page.on("pageerror", (err) => consoleErrors.push(`[pageerror] ${err.message}`));

  // Login
  await page.goto("http://localhost:3000/login");
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL(/dashboard/, { timeout: 15000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(OUT_DIR, "01-dashboard.png"), fullPage: true });
  console.log("dashboard loaded:", page.url());

  // Topbar inspection
  const topbarText = await page.locator("header, [class*=topbar], [class*=Topbar]").first().innerText().catch(() => "(no topbar found)");
  console.log("\n--- topbar text ---\n", topbarText);

  for (const route of ["sources", "pipelines", "incidents", "approvals", "governance", "quality"]) {
    await page.goto(`http://localhost:3000/${route}`);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(OUT_DIR, `${route}.png`), fullPage: true });
    const bodyText = await page.locator("body").innerText();
    const hasEmptyState = /no data|nothing (here|found)|empty state|no sources|no pipelines|no incidents|no results|get started by/i.test(bodyText);
    console.log(`${route}: loaded, possible-empty-state-language=${hasEmptyState}`);
  }

  console.log("\n--- console errors/warnings captured ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
