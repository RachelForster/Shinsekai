import { test } from "@playwright/test";

test.describe("CUJ: responsive visual coverage", () => {
  test.skip("renders settings shell without overlap on narrow desktop", async ({ page }) => {
    // Use a narrow viewport, visit all primary settings routes, and assert no clipped/overlapped controls.
    await page.setViewportSize({ width: 900, height: 900 });
    await page.goto("/#/settings/api");
  });

  test.skip("renders settings shell without overlap on mobile viewport", async ({ page }) => {
    // Use a mobile-sized viewport and verify navigation, forms, dialogs, and action bars remain usable.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/settings/api");
  });

  test.skip("renders chat stage controls on mobile viewport", async ({ page }) => {
    // Verify stage, dialogue, options, toolbar, and input area fit and remain reachable.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/chat");
  });
});
