import { expect, test } from "@playwright/test";

import { expectToast, gotoAndExpectPage } from "./helpers";

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

  test("adds and deletes background music from a background", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/backgrounds", ".background-page");

    const bgmSection = page.locator(".background-music-section");
    await bgmSection.locator(".section__header").getByRole("button").first().click();

    const picker = page.locator('[role="dialog"]');
    await expect(picker).toBeVisible();
    await picker.getByRole("button", { name: "Data" }).click();
    await picker.locator(".path-picker__row", { hasText: "bgm" }).dblclick();
    await expect(picker.locator(".path-picker__address-control")).toContainText("bgm");
    await picker.getByText("cuj-track.mp3").click();
    await picker.getByRole("button").last().click();

    await expectToast(page);
    const addedRow = bgmSection.locator(".background-bgm-row", { hasText: "cuj-track.mp3" });
    await expect(addedRow).toBeVisible();

    await addedRow.locator(".background-bgm-row__remove").click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
    await page.locator('[role="dialog"]').getByRole("button").last().click();

    await expectToast(page);
    await expect(bgmSection.locator(".background-bgm-row", { hasText: "cuj-track.mp3" })).toHaveCount(0);
    await expect(bgmSection.locator(".background-bgm-row", { hasText: "quiet-night.mp3" })).toBeVisible();
  });

  test.skip("imports and exports a background package", async ({ page }) => {
    // User exports a background, imports the package, and sees media paths remain usable.
    await page.goto("/#/settings/backgrounds");
  });
});
