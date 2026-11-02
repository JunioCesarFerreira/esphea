/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Development server: proxy API calls (and the events websocket) to the local backend.
const apiTarget = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true, ws: true },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    // Plotly (~4.6 MB) is an intentionally separate, lazily loaded chunk.
    chunkSizeWarningLimit: 5000,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
