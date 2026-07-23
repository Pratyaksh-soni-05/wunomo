import { chromium } from "playwright";
async function main() {
  const browser = await chromium.launch();
  const page = await browser.newContext({ viewport: { width: 1440, height: 900 } }).then(c => c.newPage());
  await page.goto("http://localhost:3000/login");
  await page.fill('input[type="email"]', "demo@axiom-yc.ai");
  await page.fill('input[type="password"]', "AxiomDemo2026!");
  await page.click('button[type="submit"]');
  await page.waitForURL(/dashboard/, { timeout: 15000 });
  await page.goto("http://localhost:3000/chat");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "scripts/walkthrough_shots/chat.png", fullPage: true });
  await page.goto("http://localhost:3000/approvals");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "scripts/walkthrough_shots/approvals.png", fullPage: true });
  await browser.close();
}
main();
