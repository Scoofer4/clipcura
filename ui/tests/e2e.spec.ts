import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * End-to-end against the real service: `clipsana serve` with throw-away app data, generated clips, the built
 * GUI. Covers the M3b acceptance criterion: the whole cycle works with the keyboard alone.
 */
const REPO = resolve(__dirname, "..", "..");
const CLIPS = join(REPO, "tests", "fixtures", "generated", "clips");
const OUT = process.env.CLIPSANA_SCREENSHOTS ? join(REPO, "docs", "screenshots", "m3b") : join(REPO, "ui", "test-results", "screens", "m3b");
const NEEDED = ["vfr.mp4", "a44k.mp4", "ok.mp4", "hlg.mp4"];

let server: ChildProcess | undefined;
let base = "";
let token = "";
let home = "";
let raw = "";

function uv(args: string[], env: NodeJS.ProcessEnv) {
  return spawnSync("uv", ["run", "--project", REPO, ...args], { env, encoding: "utf-8", shell: process.platform === "win32" });
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.skip(!NEEDED.every((n) => existsSync(join(CLIPS, n))), "generated clips missing: run pytest first");
  home = mkdtempSync(join(tmpdir(), "clipsana-e2e-"));
  raw = join(home, "footage", "raw");
  mkdirSync(raw, { recursive: true });
  for (const n of NEEDED) copyFileSync(join(CLIPS, n), join(raw, n));
  const env = { ...process.env, CLIPSANA_HOME: join(home, "app"), CLIPSANA_UI_DIR: join(REPO, "ui", "dist") };
  const allow = uv(["clipsana", "config", "allow", join(home, "footage")], env);
  expect(allow.status, allow.stderr).toBe(0);
  server = spawn("uv", ["run", "--project", REPO, "clipsana", "serve"], { env, shell: process.platform === "win32" });
  const announce = join(home, "app", "server.json");
  for (let i = 0; i < 150 && !existsSync(announce); i++) await new Promise((r) => setTimeout(r, 200));
  base = JSON.parse(readFileSync(announce, "utf-8")).url;
  token = JSON.parse(readFileSync(join(home, "app", "config.json"), "utf-8")).token;
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 200));
  }
});

test.afterAll(() => {
  if (server?.pid) {
    // Kill the whole tree: uv and the venv launcher sit between us and the real server process.
    if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(server.pid), "/T", "/F"]);
    else server.kill();
  }
  if (home) rmSync(home, { recursive: true, force: true });
});

async function shoot(page: Page, name: string) {
  mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(700);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
}

test("whole cycle with the keyboard only: scan, fix, watch jobs finish", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?theme=dark&accent=brand&lang=en#token=${token}`);
  await expect(page.getByRole("heading", { name: "Check a folder" })).toBeVisible();
  expect(page.url()).not.toContain("token"); // the key leaves the address bar at once
  await expect(page.getByText("Fastest paths")).toBeVisible({ timeout: 30_000 }); // HUD loaded
  await shoot(page, "start-dark");

  await page.getByLabel("Folder path").focus();
  await page.keyboard.type(raw);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "raw" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: /Fix 3 clips/ })).toBeEnabled();
  await expect(page.locator("tbody img")).toHaveCount(4, { timeout: 30_000 }); // real frames in the table
  await shoot(page, "results-dark");

  // Detail panel: focus a row and open it with Enter, then close with Escape.
  await page.locator("tbody tr").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: /Details of/ })).toBeVisible();
  await page.getByRole("button", { name: "Preview the fix" }).click();
  await expect(page.getByAltText("After")).toBeVisible({ timeout: 30_000 });
  await shoot(page, "detail-dark");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("complementary", { name: /Details of/ })).toBeHidden();

  // F opens the confirmation; Tab reaches "Start conversion"; Enter starts it.
  await page.locator("body").press("f");
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Start conversion" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByText("Finished")).toBeVisible({ timeout: 120_000 });
  await expect(page.locator("li", { hasText: "Converted" })).toHaveCount(3, { timeout: 120_000 });
  await shoot(page, "jobs-dark");
  expect(errors).toEqual([]);
});

test("AI request waits in AI activity until a human approves it", async ({ page }) => {
  const ai = { Authorization: `Bearer ${token}`, "X-Clipsana-Actor": "ai", "Content-Type": "application/json" };
  const scan = await (await fetch(`${base}/api/scans`, { method: "POST", headers: ai, body: JSON.stringify({ path: raw, profile: "ipad-light" }) })).json();
  const plan = await (await fetch(`${base}/api/plans`, { method: "POST", headers: ai, body: JSON.stringify({ scan_id: scan.scan_id }) })).json();
  const applied = await (await fetch(`${base}/api/plans/${plan.plan_id}/apply`, { method: "POST", headers: ai })).json();
  expect(applied.jobs.every((j: { status: string }) => j.status === "awaiting_approval")).toBe(true);

  await page.goto(`${base}/activity?theme=dark&accent=brand&lang=en#token=${token}`);
  await expect(page.getByText(/wait for your approval/)).toBeVisible();
  await shoot(page, "activity-dark");
  await page.getByRole("button", { name: "Approve all" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/wait for your approval/)).toBeHidden({ timeout: 30_000 });
  await expect(page.getByText("Approved").first()).toBeVisible();
});

test("command palette, settings and light theme", async ({ page }) => {
  await page.goto(`${base}/?theme=light&accent=brand&lang=en#token=${token}`);
  await expect(page.getByRole("heading", { name: "Check a folder" })).toBeVisible();
  await shoot(page, "start-light");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("settings");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByText(join(home, "footage"))).toBeVisible();
  await shoot(page, "settings-light");

  await page.goto(`${base}/settings?theme=dark&accent=brand&lang=cs`);
  await expect(page.getByRole("heading", { name: "Nastavení" })).toBeVisible();
  await shoot(page, "settings-dark-cs");

  for (const route of ["jobs", "activity"]) {
    await page.goto(`${base}/${route}?theme=light&accent=brand&lang=en`);
    await shoot(page, `${route}-light`);
  }
});
