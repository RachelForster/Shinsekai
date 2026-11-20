import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function modulePath(path: string) {
  return new URL(path, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
}

export default defineConfig({
  base: "./",
  plugins: [react()],
  define: {
    "import.meta.env.VITE_SHINSEKAI_TARGET": JSON.stringify("toy"),
    "import.meta.env.VITE_SHINSEKAI_STANDALONE": JSON.stringify("true"),
  },
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
    outDir: "dist-toy",
    emptyOutDir: true,
    assetsDir: "web-assets",
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        entryFileNames: "web-assets/[name]-[hash].js",
        chunkFileNames: "web-assets/[name]-[hash].js",
        assetFileNames: "web-assets/[name]-[hash][extname]",
        manualChunks(id) {
          const moduleId = id.replace(/\\/g, "/");
          const has = (value: string) => moduleId.indexOf(value) >= 0;

          if (!has("/node_modules/")) {
            return undefined;
          }
          if (has("/typescript/")) {
            return "l2d-compiler";
          }
          if (has("/@babylonjs/") || has("/babylon-mmd/")) {
            return "mmd-vendor";
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
});
