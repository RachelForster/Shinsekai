import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

function modulePath(path: string) {
  return new URL(path, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@tanstack/react-query": modulePath("./node_modules/@tanstack/react-query"),
      "lucide-react": modulePath("./node_modules/lucide-react/dist/esm/lucide-react.js"),
      react: modulePath("./node_modules/react"),
      "react-dom": modulePath("./node_modules/react-dom"),
      "react/jsx-runtime": modulePath("./node_modules/react/jsx-runtime.js"),
    },
  },
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
    coverage: {
      provider: "v8",
      all: true,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/**/*.d.ts", "src/vite-env.d.ts", "src/main.tsx"],
      reporter: ["text", "html", "lcov", "json-summary"],
      reportsDirectory: "./coverage",
    },
  },
});
