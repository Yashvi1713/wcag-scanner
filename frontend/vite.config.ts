import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs separately (python -m wcag_scanner serve) and Vite forwards to it.
// In production FastAPI serves the built files from dist/, so everything is one origin.
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": backend, "/scans": backend, "/demo-site": backend },
    fs: { allow: [".."] }, // the stylesheet is shared with the server-rendered report downloads
  },
  build: { sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
