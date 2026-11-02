import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/** In development, proxy /api to the running `clipsana serve` (found via its server.json announcement). */
function apiTarget(): string | undefined {
  const home = process.env.CLIPSANA_HOME ?? (process.env.APPDATA ? join(process.env.APPDATA, "Clipsana") : undefined);
  const file = home && join(home, "server.json");
  if (!file || !existsSync(file)) return undefined;
  try {
    return JSON.parse(readFileSync(file, "utf-8")).url as string;
  } catch {
    return undefined;
  }
}

const target = apiTarget();

// The built files are served by the local API (same origin, so no CORS is ever needed).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rolldownOptions: {
      output: {
        // three.js only loads where a 3D view is on screen; keep it out of the first paint.
        advancedChunks: { groups: [{ name: "three", test: /node_modules[\\/](three|@react-three)/ }] },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: target ? { "/api": { target, ws: true, changeOrigin: false } } : undefined,
  },
  preview: { host: "127.0.0.1" },
});
