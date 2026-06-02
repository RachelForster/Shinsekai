import { expect, test } from "@playwright/test";

import { expectToast, fillInput, gotoAndExpectPage } from "./helpers";

test.describe("CUJ: system settings", () => {
  test("changes theme color, base font size, and saves", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/system", ".system-page");

    await fillInput(page.locator("#base_font_size_px"), "48");
    await page.locator("#theme_color").fill("#4f9d8f");
    await page.locator(".page__actions").getByRole("button").click();

    await expectToast(page);
    await expect(page.locator("html")).toHaveAttribute("style", /--theme-accent/);
  });

  test("persists runtime preferences across reload", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/system", ".system-page");

    await fillInput(page.locator("#live_room_id"), "cuj-room-100");
    await page.locator(".page__actions").getByRole("button").click();
    await expectToast(page);

    await page.goto("/#/settings/tools");
    await expect(page.locator(".tools-page")).toBeVisible();
    await page.goto("/#/settings/system");
    await expect(page.locator(".system-page")).toBeVisible();
    await expect(page.locator("#live_room_id")).toHaveValue("cuj-room-100");
  });
});
