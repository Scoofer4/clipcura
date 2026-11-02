import { defineConfig } from "@playwright/test";

// Uses the Microsoft Edge already installed on Windows (the same engine as the app's WebView2),
// so no browser download is needed.
export default defineConfig({
  testDir: "tests",
  timeout: 60_000,
  reporter: "list",
  use: {
    channel: "msedge",
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
