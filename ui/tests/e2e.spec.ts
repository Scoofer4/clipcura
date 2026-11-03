import { expect, test, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * End-to-end against the real service: `clipcura serve` with throw-away app data, generated clips, the built
 * GUI. Covers the M3b acceptance criterion: the whole cycle works with the keyboard alone.
 */
const REPO = resolve(__dirname, "..", "..");
const CLIPS = join(REPO, "tests", "fixtures", "generated", "clips");
const OUT = process.env.CLIPCURA_SCREENSHOTS ? join(REPO, "docs", "screenshots", "m3b") : join(REPO, "ui", "test-results", "screens", "m3b");
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
  // Long path form: the runner's temp dir is an 8.3 short name (RUNNER~1), the service stores resolved paths.
  home = realpathSync.native(mkdtempSync(join(tmpdir(), "clipcura-e2e-")));
  raw = join(home, "footage", "raw");
  mkdirSync(raw, { recursive: true });
  for (const n of NEEDED) copyFileSync(join(CLIPS, n), join(raw, n));
  const env = { ...process.env, CLIPCURA_HOME: join(home, "app"), CLIPCURA_UI_DIR: join(REPO, "ui", "dist") };
  const allow = uv(["clipcura", "config", "allow", join(home, "footage")], env);
  expect(allow.status, allow.stderr).toBe(0);
  server = spawn("uv", ["run", "--project", REPO, "clipcura", "serve"], { env, shell: process.platform === "win32" });
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
  // Approved conversions may still be running when the server is killed; Windows frees ffmpeg's file lock a
  // moment after the process ends, so retry instead of failing on EBUSY.
  if (home) rmSync(home, { recursive: true, force: true, maxRetries: 20, retryDelay: 250 });
});

async function shoot(page: Page, name: string) {
  // CI runners have no GPU: software WebGL makes a screenshot of the 3D views take most of a minute.
  if (process.env.CI && !process.env.CLIPCURA_SCREENSHOTS) return;
  mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(700);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
}

test("whole cycle with the keyboard only: scan, fix, watch jobs finish", async ({ page }) => {
  test.setTimeout(240_000); // three real conversions; CPU-only runners are slow
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
  const ai = { Authorization: `Bearer ${token}`, "X-Clipcura-Actor": "ai", "Content-Type": "application/json" };
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

test("profile editor: duplicate, validate, save and delete", async ({ page }) => {
  await page.goto(`${base}/settings?theme=dark&accent=brand&lang=en#token=${token}`);
  await page.getByRole("button", { name: "Duplicate social-30" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "New profile" })).toBeVisible();
  await dialog.getByLabel("Name", { exact: true }).fill("reels-25");
  await dialog.getByLabel("Label", { exact: true }).fill("Reels 25 fps");
  await dialog.getByLabel("Frame rate", { exact: true }).fill("25");
  // An editing codec in MP4 cannot work: the editor says so and will not save.
  await dialog.getByRole("radio", { name: "MP4" }).click();
  await expect(dialog.getByText(/needs MOV or MKV/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Save profile" })).toBeDisabled();
  await dialog.getByRole("radio", { name: "MOV" }).click();
  await shoot(page, "profile-editor-dark");
  // The API has the last word: a folder outside the allowed ones is refused with its reason.
  await dialog.getByLabel("Output folder", { exact: true }).fill("C:\Windows\Temp");
  await dialog.getByRole("button", { name: "Save profile" }).click();
  await expect(dialog.getByRole("alert")).toContainText("allowed folder");
  await dialog.getByLabel("Output folder", { exact: true }).fill("../02_edit");
  await dialog.getByRole("button", { name: "Save profile" }).press("Enter");
  await expect(dialog).toBeHidden();
  const card = page.locator("li").filter({ has: page.getByRole("button", { name: "Edit reels-25" }) });
  await expect(card).toContainText("25 fps");
  await expect(card).toContainText("yours");
  await page.getByRole("button", { name: "Delete reels-25" }).click();
  await expect(page.getByRole("button", { name: "Edit reels-25" })).toHaveCount(0);
});

test("help for each screen, and the About screen with owner and licences", async ({ page }) => {
  await page.goto(`${base}/?theme=dark&accent=brand&lang=en#token=${token}`);
  await page.getByRole("button", { name: "Help" }).click();
  const help = page.getByRole("dialog");
  await expect(help.getByRole("heading", { name: "Help: Start" })).toBeVisible();
  await expect(help.getByText("How to use it")).toBeVisible();
  await shoot(page, "help-start-dark");
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();

  // F1 opens the help of whatever screen is on display.
  await page.goto(`${base}/jobs`);
  await page.keyboard.press("F1");
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Help: Jobs" })).toBeVisible();
  await page.getByRole("dialog").getByRole("link", { name: "About Clipcura" }).click();

  await expect(page.getByRole("heading", { name: "Clipcura", level: 1 })).toBeVisible();
  await expect(page.getByText("A Metaverse Media s.r.o. production")).toBeVisible();
  await expect(page.getByText("Owner and creator")).toBeVisible();
  const credits = page.getByRole("region", { name: "Service" });
  await expect(credits.getByRole("cell", { name: "fastapi", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Interface" }).getByRole("cell", { name: "react", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Media engine" }).getByText("FFmpeg", { exact: true })).toBeVisible();
  await shoot(page, "about-dark");

  await page.getByRole("button", { name: "Licence texts" }).click();
  const texts = page.getByRole("dialog");
  await expect(texts.getByText(/Corresponding source code/)).toBeVisible({ timeout: 30_000 });
  await expect(texts.getByText(/==== react /)).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(`${base}/about?theme=light&lang=cs`);
  await expect(page.getByText("Vlastník a tvůrce")).toBeVisible();
  await expect(page.getByText("Vyrobila Metaverse Media s.r.o.")).toBeVisible();
  await page.keyboard.press("F1");
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Nápověda: O aplikaci" })).toBeVisible();
  await page.keyboard.press("Escape");
  await shoot(page, "about-light-cs");
});

test("browser mode: a one-time code opens the GUI once and never shows the key (#23)", async ({ browser }) => {
  const issue = async () => (await (await fetch(`${base}/api/login-codes`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  })).json()).code as string;
  const code = await issue();
  const first = await browser.newContext();
  const page = await first.newPage();
  await page.goto(`${base}/?theme=dark&lang=en#code=${code}`);
  await expect(page.getByRole("heading", { name: "Check a folder" })).toBeVisible();
  expect(page.url()).not.toContain("code=");
  await page.goto(`${base}/about?lang=en`);   // the key stays with the tab, so reloads and links keep working
  await expect(page.getByText("Run from source code")).toBeVisible();
  await first.close();

  // The same link a second time, e.g. from the browser's history: refused.
  const again = await browser.newContext();
  const stale = await again.newPage();
  await stale.goto(`${base}/?lang=en#code=${code}`);
  await expect(stale.getByRole("heading", { name: "This link has expired" })).toBeVisible();
  await again.close();
});
