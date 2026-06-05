import { defineConfig, devices } from "@playwright/test";

import baseConfig from "./playwright.config";

export default defineConfig({
  ...baseConfig,
  projects: [
    {
      name: "edge-desktop",
      use: {
        ...devices["Desktop Chrome"],
        channel: "msedge",
      },
    },
  ],
});
