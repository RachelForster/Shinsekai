import { expect, test } from "@playwright/test";

import {
  collectPageErrors,
  expectNoPageErrors,
  expectToast,
  fieldByIndex,
  fieldControlByIndex,
  fillInput,
  gotoAndExpectPage,
  selectCustomValue,
} from "./helpers";

test.describe("CUJ: API configuration", () => {
  test("configures LLM, ASR, TTS, and saves settings", async ({ page }) => {
    const pageErrors = collectPageErrors(page);
    await gotoAndExpectPage(page, "/#/settings/api", ".api-page");

    await selectCustomValue(fieldControlByIndex(page, 2, ".custom-select"), "ChatGPT");
    await fillInput(fieldControlByIndex(page, 3, "input"), "https://api.openai.com/v1");
    await fillInput(fieldControlByIndex(page, 4, "input"), "dummy-e2e-key");
    await fillInput(fieldControlByIndex(page, 5, "input"), "gpt-4o-mini");

    const ttsProviderRow = page.locator(".field-row").filter({ has: page.locator("#tts_provider") });
    await selectCustomValue(ttsProviderRow.locator(".custom-select"), "none");

    await page.locator(".api-page__save-button").click();
    await expectToast(page);

    await page.goto("/#/settings/tools");
    await expect(page.locator(".tools-page")).toBeVisible();
    await page.goto("/#/settings/api");
    await expect(fieldControlByIndex(page, 3, "input")).toHaveValue("https://api.openai.com/v1");
    await expect(fieldControlByIndex(page, 5, "input")).toHaveValue("gpt-4o-mini");
    await expectNoPageErrors(pageErrors);
  });

  test("keeps custom model IDs selectable after provider changes", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/api", ".api-page");

    await selectCustomValue(fieldControlByIndex(page, 2, ".custom-select"), "Deepseek");
    await fillInput(fieldControlByIndex(page, 5, "input"), "deepseek-e2e-custom");
    await selectCustomValue(fieldControlByIndex(page, 2, ".custom-select"), "ChatGPT");
    await fillInput(fieldControlByIndex(page, 5, "input"), "gpt-e2e-custom");
    await selectCustomValue(fieldControlByIndex(page, 2, ".custom-select"), "Deepseek");

    await expect(fieldControlByIndex(page, 5, "input")).toHaveValue("deepseek-e2e-custom");
    await fieldByIndex(page, 5).locator(".editable-combo__button").click();
    await expect(page.getByRole("option", { name: "deepseek-e2e-custom" })).toBeVisible();
  });

  test("downloads a recommended TTS bundle in preview mode", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/api", ".api-page");

    await page.locator(".api-page").getByRole("button").nth(3).click();
    await expect(page.locator(".tts-bundle-dialog")).toBeVisible();
    await page.locator(".tts-bundle-dialog").getByRole("button").last().click();
    await expectToast(page);
    await expect(page.locator(".tts-bundle-dialog")).toBeHidden();
  });

  test("optionally fetches model candidates with a real provider key", async ({ page }) => {
    test.skip(!process.env.SHINSEKAI_E2E_LLM_API_KEY, "Set SHINSEKAI_E2E_LLM_API_KEY to run provider-backed checks.");

    await gotoAndExpectPage(page, "/#/settings/api", ".api-page");
    await fillInput(fieldControlByIndex(page, 4, "input"), process.env.SHINSEKAI_E2E_LLM_API_KEY ?? "");
    await page.locator(".api-page__model-control").getByRole("button").last().click();
    await expectToast(page);
  });
});
