import { expect, test } from "@playwright/test";

const settingsRoutes = [
  { name: "settings-api", path: "/#/settings/api", title: "API 配置" },
  { name: "settings-characters", path: "/#/settings/characters", title: "人物设定" },
  { name: "settings-backgrounds", path: "/#/settings/backgrounds", title: "背景管理" },
  { name: "settings-templates", path: "/#/settings/templates", title: "生成模板" },
  { name: "settings-plugins", path: "/#/settings/plugins", title: "插件" },
  { name: "settings-tools", path: "/#/settings/tools", title: "小工具" },
  { name: "settings-music-cover", path: "/#/settings/music-cover", title: "音乐翻唱流水线" },
  { name: "settings-launch", path: "/#/settings/launch", title: "启动聊天" },
  { name: "settings-system", path: "/#/settings/system", title: "系统" },
] as const;

test.describe("settings center visual regression", () => {
  for (const route of settingsRoutes) {
    test(route.name, async ({ page }) => {
      await page.goto(route.path);
      await expect(page.getByRole("heading", { exact: true, name: route.title })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "设置中心导航" })).toBeVisible();
      await expect(page).toHaveScreenshot(`${route.name}.png`, { fullPage: true });
    });
  }
});

test("chat stage visual regression", async ({ page }) => {
  await page.goto("/#/chat");
  await expect(page.locator(".dialog-layer")).toBeVisible();
  await expect(page.locator(".floating-toolbar")).toBeVisible();
  await expect(page.locator(".input-layer")).toBeVisible();
  await expect(page).toHaveScreenshot("chat-stage.png", { fullPage: true });
});

test("chat stage light-paper theme visual regression", async ({ page }) => {
  await page.goto("/#/chat");
  await expect(page.locator(".dialog-layer")).toBeVisible();

  await page.getByRole("button", { name: "主题管理" }).click();
  const themeDialog = page.getByRole("dialog", { name: "聊天主题" });
  await expect(themeDialog).toBeVisible();

  const lightPaperCard = themeDialog.locator(".chat-theme-picker__card").filter({ hasText: "浅色纸张" });
  await lightPaperCard.getByRole("button", { name: "应用" }).click();

  await expect
    .poll(async () => {
      return page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue("--chat-theme-color").trim(),
      );
    })
    .toBe("#c77dff");

  await themeDialog.getByRole("button", { name: "关闭" }).click();
  await expect(themeDialog).toBeHidden();
  await expect(page).toHaveScreenshot("chat-stage-light-paper.png", { fullPage: true });
});
