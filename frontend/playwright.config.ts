import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174";
const launchOptions =
  process.platform === "linux"
    ? {
        args: ["--disable-dev-shm-usage", "--disable-setuid-sandbox", "--no-sandbox"],
        chromiumSandbox: false,
      }
    : undefined;

export default defineConfig({
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.01,
      scale: "css",
    },
  },
  fullyParallel: false,
  reporter: [["list"]],
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL,
    colorScheme: "dark",
    launchOptions,
    trace: "retain-on-failure",
    viewport: { height: 900, width: 1280 },
  },
  projects: [
    {
      name: "chromium-desktop",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
