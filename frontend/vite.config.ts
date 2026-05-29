import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    assetsDir: "web-assets",
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replace(/\\/g, "/");
          const has = (value: string) => moduleId.indexOf(value) >= 0;

          if (!has("/node_modules/")) {
            return undefined;
          }

          if (
            has("/react/") ||
            has("/react-dom/") ||
            has("/react-router/") ||
            has("/react-router-dom/") ||
            has("/scheduler/")
          ) {
            return "react-vendor";
          }

          if (has("/@tanstack/")) {
            return "query-vendor";
          }

          if (has("/lucide-react/")) {
            return "icon-vendor";
          }

          return "vendor";
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/test/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: "./src/test/setup.ts",
  },
});
