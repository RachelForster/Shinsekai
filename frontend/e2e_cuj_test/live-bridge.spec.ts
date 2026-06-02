import { test } from "@playwright/test";

test.describe("CUJ: live bridge", () => {
  test.skip("saves API settings and verifies persisted bridge config", async ({ page }) => {
    // Requires SHINSEKAI_API_BASE and SHINSEKAI_PROJECT_ROOT.
    // User saves settings in the UI, then the test reads the bridge config endpoint.
    await page.goto("/#/settings/api");
  });

  test.skip("exports and reimports a character package through the real bridge", async ({ page }) => {
    // Verify imported character appears and media paths resolve without backslashes.
    await page.goto("/#/settings/characters");
  });

  test.skip("exports and reimports a background package through the real bridge", async ({ page }) => {
    // Verify imported background appears and image media paths resolve.
    await page.goto("/#/settings/backgrounds");
  });

  test.skip("runs a real bridge tool task and observes task completion", async ({ page }) => {
    // Run a small tool workflow and assert bridge task status/result.
    await page.goto("/#/settings/tools");
  });
});
