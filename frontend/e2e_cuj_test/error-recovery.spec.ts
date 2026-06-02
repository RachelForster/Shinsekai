import { test } from "@playwright/test";

test.describe("CUJ: error recovery", () => {
  test.skip("shows a retryable error when config loading fails", async ({ page }) => {
    // Mock platform config.get failure, assert retry UI, then recover on retry.
    await page.goto("/#/settings/api");
  });

  test.skip("keeps edited form state visible when save fails", async ({ page }) => {
    // Mock save failure, assert error feedback appears without dropping the user's draft.
    await page.goto("/#/settings/api");
  });

  test.skip("reports plugin install failure without corrupting installed state", async ({ page }) => {
    // Mock failed plugin install task and assert catalog/installed lists remain consistent.
    await page.goto("/#/settings/plugins");
  });

  test.skip("keeps chat stage usable after command failure", async ({ page }) => {
    // Mock a chat command failure, assert the user can retry or continue interacting.
    await page.goto("/#/chat");
  });
});
