import { expect, test } from "@playwright/test";

import { expectTaskDone, fillInput, gotoAndExpectPage } from "./helpers";

test.describe("CUJ: tools workflows", () => {
  test("generates sprite prompts and uses them for sprite generation", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/tools", ".tools-page");

    const promptForm = page.locator(".tools-grid--three .form-grid").first();
    await promptForm.locator('input[type="number"]').fill("2");
    await promptForm.getByRole("button").first().click();

    await expect(page.locator(".tools-page__prompts")).toContainText("pose 1");
    await fillInput(promptForm.locator("input").last(), "/home/shinsekai/project/assets/ref.png");

    const generationForm = page.locator(".tools-grid--three .form-grid").nth(1);
    await fillInput(generationForm.locator("input").first(), "output/cuj-sprites");
    await generationForm.getByRole("button").click();

    await expectTaskDone(page);
    await expect(page.locator(".tool-gallery__item")).toHaveCount(2);
    await expect(page.locator(".tools-page__output")).toContainText("output/cuj-sprites");
  });

  test("crops sprites with explicit input and output directories", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/tools", ".tools-page");

    const cropGroup = page.locator(".tools-grid--two .tool-group").first();
    const inputs = cropGroup.locator("input");
    await fillInput(inputs.nth(0), "/home/shinsekai/project/assets/system/picture");
    await fillInput(inputs.nth(1), "output/cuj-crop");
    await inputs.nth(2).fill("0.5");
    await cropGroup.getByRole("button").click();

    await expectTaskDone(page);
    await expect(page.locator(".tools-page__output")).toContainText("output/cuj-crop");
  });

  test("removes sprite backgrounds in batch", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/tools", ".tools-page");

    const removeBgGroup = page.locator(".tools-grid--two .tool-group").nth(1);
    const inputs = removeBgGroup.locator("input");
    await fillInput(inputs.nth(0), "/home/shinsekai/project/assets/sprites");
    await fillInput(inputs.nth(1), "output/cuj-rmbg");
    await removeBgGroup.getByRole("button").click();

    await expectTaskDone(page);
    await expect(page.locator(".tools-page__output")).toContainText("output/cuj-rmbg");
  });
});
