import { expect, test } from "@playwright/test";

import { expectTaskDone, expectToast, gotoAndExpectPage } from "./helpers";

test.describe("CUJ: plugin management", () => {
  test("installs a plugin from the discovery catalog", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/plugins", ".plugin-page");

    await page.getByRole("tab").nth(1).click();
    await expect(page.locator(".data-table")).toBeVisible();
    await page.locator(".data-table tbody tr").first().getByRole("button").first().click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
    await page.locator('[role="dialog"]').getByRole("button").last().click();

    await expectTaskDone(page);
    await expectToast(page);
    await page.locator('[role="dialog"]').getByRole("button").first().click();
    await expect(page.locator('[role="dialog"]')).toBeHidden();
    await page.getByRole("tab").first().click();
    await expect(page.locator(".plugin-card").filter({ hasText: "RachelForster" })).toBeVisible();
  });

  test.skip("opens plugin configuration, edits fields, and saves", async ({ page }) => {
    // Implement with a focused IPC mock that exposes a real schema-driven plugin settings page.
    await page.goto("/#/settings/plugins");
  });

  test("disables, enables, and uninstalls a plugin", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/plugins", ".plugin-page");

    const card = page.locator(".plugin-card").filter({ hasText: "core-tools" });
    await expect(card).toBeVisible();
    await card.locator(".plugin-card__actions").getByRole("button").nth(1).click();
    await expectToast(page);
    await card.locator(".plugin-card__actions").getByRole("button").nth(1).click();
    await expectToast(page);

    await card.locator(".plugin-card__actions").getByRole("button").first().click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
    await page.locator('[role="dialog"]').getByRole("button").last().click();
    await expectToast(page);
    await expect(card).toHaveCount(0);
  });

  test("edits MCP config, previews tools, and applies changes", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/plugins", ".plugin-page");

    await page.getByRole("tab").nth(2).click();
    const mcpHeader = page.locator(".plugin-page > .section").first();
    await expect(mcpHeader).toBeVisible();
    await mcpHeader.locator('input[type="number"]').fill("123");

    await page.locator(".plugin-page > .section").nth(2).getByRole("button").click();
    await expectTaskDone(page);
    await expect(page.locator(".data-table").nth(1)).toContainText("demo_search");

    await mcpHeader.getByRole("button").nth(1).click();
    await expectTaskDone(page);
    await expectToast(page);
  });

  test("runs app self-update flow and shows task progress", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/plugins", ".plugin-page");

    await page.getByRole("tab").nth(1).click();
    await page.locator(".section__header").getByRole("button").first().click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
    await page.locator('[role="dialog"]').getByRole("button").last().click();

    await expectTaskDone(page);
    await expectToast(page);
  });
});
