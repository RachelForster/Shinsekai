import { expect, test, type Page } from "@playwright/test";

const settingsRoutes = [
  { name: "settings-api", path: "/#/settings/api", title: "AI 服务设置" },
  { name: "settings-characters", path: "/#/settings/characters", title: "角色管理" },
  { name: "settings-backgrounds", path: "/#/settings/backgrounds", title: "背景素材" },
  { name: "settings-templates", path: "/#/settings/templates", title: "生成模板" },
  { name: "settings-plugins", path: "/#/settings/plugins", title: "插件管理" },
  { name: "settings-tools", path: "/#/settings/tools", title: "实用工具" },
  { name: "settings-music-cover", path: "/#/settings/music-cover", title: "音乐翻唱" },
  { name: "settings-launch", path: "/#/settings/launch", title: "开始聊天" },
  { name: "settings-system", path: "/#/settings/system", title: "程序设置" },
] as const;

async function expectChatStageReady(page: Page) {
  await expect(page.getByText("欢迎来到新世界。")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("toolbar", { name: "聊天舞台操作" })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".input-layer")).toBeVisible({ timeout: 15_000 });
}

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
  await expectChatStageReady(page);
  await expect(page).toHaveScreenshot("chat-stage.png", { fullPage: true });
});

test("chat stage config dialog visual regression", async ({ page }) => {
  await page.goto("/#/chat");
  await expectChatStageReady(page);

  const configButton = page.getByRole("button", { name: "聊天界面设置" });
  await expect(configButton).toBeVisible();
  await configButton.evaluate((button) => (button as HTMLButtonElement).click());
  const configDialog = page.getByRole("dialog", { name: "聊天界面设置" });
  await expect(configDialog).toBeVisible();
  await expect(configDialog.getByRole("heading", { name: "字体" })).toBeVisible();
  await expect(page).toHaveScreenshot("chat-stage-config.png", { fullPage: true });
});
