import { defineConfig } from "@playwright/test";

// Uses the Microsoft Edge already installed on Windows (the same engine as the app's WebView2),
// so no browser download is needed.
// CI runners have no GPU: three software-rendered WebGL scenes starve the page's main thread. There the tests run
// one at a time with reduced motion, which renders the 3D views on demand instead of every frame; the checks
// are the same, only the animation is off.
const CI = !!process.env.CI;

export default defineConfig({
  testDir: "tests",
  timeout: 60_000,
  reporter: "list",
  workers: CI ? 1 : undefined,
  use: {
    channel: "msedge",
    reducedMotion: CI ? "reduce" : "no-preference",
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  },
  webServer: {
    command: "npm run preview",
    url: "http://127.0.0.1:4173/_kitchen-sink",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
