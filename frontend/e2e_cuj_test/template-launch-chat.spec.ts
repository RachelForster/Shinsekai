import { expect, test } from "@playwright/test";

import { expectToast, fillInput, gotoAndExpectPage } from "./helpers";

test.describe("CUJ: template generation and chat launch", () => {
  test("generates a template from selected characters and background", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/templates", ".template-page");

    await fillInput(page.locator(".template-scenario-textarea"), "A quiet evening conversation near the window.");
    await page.locator(".template-generate-button").click();

    await expectToast(page);
    await fillInput(page.locator(".template-topbar-field input").first(), "cuj-template");
    await page.locator(".template-save-button").click();
    await expectToast(page);
  });

  test("restores the last launch page session after starting chat", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/launch", ".launch-page");

    const launchInputs = page.locator(".launch-page input");
    await fillInput(launchInputs.nth(1), "data/chat_history/cuj-restore.json");
    await page.locator(".page__actions").getByRole("button").first().click();

    await expect(page).toHaveURL(/#\/chat/);
    await page.goto("/#/settings/launch");
    await expect(page.locator(".launch-page")).toBeVisible();
    await expect(page.locator(".launch-page input.input").last()).toHaveValue(/cuj-restore\.json/);
  });

  test("launches chat from the launch page", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/launch", ".launch-page");

    const launchInputs = page.locator(".launch-page input");
    await fillInput(launchInputs.nth(1), "data/chat_history/cuj-launch.json");
    await page.locator(".page__actions").getByRole("button").first().click();

    await expect(page).toHaveURL(/#\/chat/);
    await expect(page.locator(".chat-stage")).toBeVisible();
    await expect(page.locator(".dialog-layer__name")).toContainText("Nanami");
  });

  test("requires confirmation for quick restart with reset history", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/templates", ".template-page");

    await page.locator(".template-page__footer").getByRole("button").nth(1).click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
    await page.locator('[role="dialog"]').getByRole("button").last().click();

    await expectToast(page);
    await expect(page.locator(".template-page")).toBeVisible();
  });
});
