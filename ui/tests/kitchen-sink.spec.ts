import { expect, test } from "@playwright/test";

// Screenshots for the owner's visual review (CLAUDE.md §9): every theme x accent, plus key interactive states.
const OUT = "../docs/screenshots/m3a";

for (const theme of ["dark", "light"] as const) {
  for (const accent of ["brand", "aurora"] as const) {
    test(`kitchen sink ${theme} ${accent}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

      await page.goto(`/_kitchen-sink?theme=${theme}&accent=${accent}&lang=en`);
      await expect(page.getByRole("heading", { name: "Design system" })).toBeVisible();
      // Three WebGL scenes: drop zone, cadence instrument, job cadence.
      await expect(page.locator("canvas")).toHaveCount(3);
      await page.waitForTimeout(1800); // let springs settle and the fonts finish loading

      await page.screenshot({ path: `${OUT}/kitchen-sink-${theme}-${accent}.png`, fullPage: true });
      await page.screenshot({ path: `${OUT}/start-${theme}-${accent}.png` });
      expect(errors).toEqual([]);
    });
  }
}

test("interactions: drag preview, selection and target rate", async ({ page }) => {
  await page.goto("/_kitchen-sink?theme=dark&accent=brand&lang=en");
  await page.getByText("Preview drag-over").click();
  await page.waitForTimeout(1200);
  await page.locator("[role=region]").first().screenshot({ path: `${OUT}/dropzone-drag-dark-brand.png` });

  // Keyboard: focus a row, select it with Space; the fix button counts the selection.
  await page.getByRole("button", { name: "Select all fixable" }).click();
  await expect(page.getByRole("button", { name: /Fix 3 clips/ })).toBeEnabled();

  await page.getByRole("radio", { name: "24 fps" }).click();
  await expect(page.getByText(/Leaves out 32 frames each second/)).toBeVisible();
  await page.locator("#cadence").screenshot({ path: `${OUT}/cadence-24fps-dark-brand.png` });
});

test("czech translation renders", async ({ page }) => {
  await page.goto("/_kitchen-sink?theme=dark&accent=brand&lang=cs");
  await expect(page.getByRole("heading", { name: "Přetáhni složku s videi" })).toBeVisible();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/start-dark-brand-cs.png` });
});
