import { expect, test } from "@playwright/test";

import { expectTaskDone, expectToast, fillInput, gotoAndExpectPage, selectCustomValue } from "./helpers";

test.describe("CUJ: music cover pipeline", () => {
  test("saves music cover toolchain configuration", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/music-cover", ".music-cover-page");

    const settings = page.locator(".settings-grid");
    await fillInput(settings.locator("input").first(), "./data/music_cover_cuj");
    await fillInput(settings.locator("input").nth(5), "cuda:0");
    await selectCustomValue(settings.locator(".custom-select").first(), "v2");
    await selectCustomValue(settings.locator(".custom-select").nth(1), "rmvpe");

    await settings.getByRole("button").last().click();
    await expectToast(page);
    await expect(settings.locator("textarea").last()).not.toHaveValue("");
  });

  test("searches for a source track and runs the pipeline", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/music-cover", ".music-cover-page");

    const runner = page.locator(".music-cover-layout > .section").last();
    await selectCustomValue(runner.locator(".custom-select").first(), "url");
    await fillInput(runner.locator("textarea").first(), "https://example.test/song.mp3");

    await runner.getByRole("button").first().click();
    await expect(runner.locator("textarea").last()).toContainText("https://example.test/song.mp3");

    await runner.getByRole("button").nth(1).click();
    await expectTaskDone(page);
    await expect(runner.locator(".path-display")).toContainText("final_mix.wav");
  });

  test("runs the pipeline in skip-RVC mode", async ({ page }) => {
    await gotoAndExpectPage(page, "/#/settings/music-cover", ".music-cover-page");

    const runner = page.locator(".music-cover-layout > .section").last();
    await selectCustomValue(runner.locator(".custom-select").first(), "youtube");
    await fillInput(runner.locator("textarea").first(), "preview song");
    await runner.locator('input[type="checkbox"]').check();
    await runner.getByRole("button").nth(1).click();

    await expectTaskDone(page);
    await expect(runner.locator("textarea").last()).toContainText("skip_rvc=true");
  });
});
