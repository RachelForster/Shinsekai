import { expect, test } from "@playwright/test";

import { collectPageErrors, expectNoPageErrors, expectToast, gotoAndExpectPage } from "./helpers";

test.describe("CUJ: chat stage", () => {
  test("submits an option and observes stage state changes", async ({ page }) => {
    const pageErrors = collectPageErrors(page);
    await gotoAndExpectPage(page, "/#/chat", ".chat-stage");

    const dialog = page.locator(".dialog-layer__text");
    const before = await dialog.textContent();
    const firstOption = page.locator(".options-layer__button").first();
    const optionText = (await firstOption.textContent())?.trim() ?? "";
    await expect(firstOption).toBeEnabled();
    await firstOption.click();

    await expect(dialog).toContainText(optionText);
    await expect(dialog).not.toHaveText(before ?? "");
    await expect(page.locator(".floating-toolbar__status")).toContainText(/generating|idle|streaming|speaking/);
    await expectNoPageErrors(pageErrors);
  });

  test("sends typed dialogue and skips speech", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/chat", ".chat-stage");

    await page.locator(".input-layer__input").fill("Hello from CUJ");
    const sendButton = page.locator(".input-layer").getByRole("button").last();
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    await expect(page.locator(".dialog-layer__text")).toContainText("Hello from CUJ");
    await expect(page.locator(".floating-toolbar__status")).toContainText(/streaming|speaking/);
    await page.locator(".floating-toolbar").getByRole("button").last().click();
    await expect(page.locator(".floating-toolbar__status")).toContainText("idle");
  });

  test("copies, opens, and clears chat history safely", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/chat", ".chat-stage");

    const toolbarButtons = page.locator(".floating-toolbar").getByRole("button");
    await toolbarButtons.nth(1).click();
    await expectToast(page);

    await toolbarButtons.nth(2).click();
    await expectToast(page);

    await toolbarButtons.nth(3).click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
    await page.locator('[role="dialog"]').getByRole("button").last().click();
    await expectToast(page);
    await expect(page.locator('[role="dialog"]')).toBeHidden();
  });
});
