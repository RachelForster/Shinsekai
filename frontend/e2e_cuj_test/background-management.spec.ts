import { test } from "@playwright/test";

test.describe("CUJ: background management", () => {
  test.skip("creates a background and reopens the saved draft", async ({ page }) => {
    // User creates a background, fills name/prefix fields, saves, and reselects it.
    await page.goto("/#/settings/backgrounds");
  });

  test.skip("manages background images, image tags, BGM, and BGM tags", async ({ page }) => {
    // User adds images/BGM, edits tags, selects rows, and verifies the preview/list state.
    await page.goto("/#/settings/backgrounds");
  });

  test.skip("prevents accidental destructive background actions", async ({ page }) => {
    // User attempts delete/delete-all image and BGM actions and must confirm first.
    await page.goto("/#/settings/backgrounds");
  });

  test.skip("imports and exports a background package", async ({ page }) => {
    // User exports a background, imports the package, and sees media paths remain usable.
    await page.goto("/#/settings/backgrounds");
  });
});
