import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("shinsekai-onboarding-seen", "true");
    localStorage.setItem("shinsekai-feature-highlights-seen", "999.0.0");
  });
  await page.route("https://api.github.com/repos/RachelForster/Shinsekai", (route) =>
    route.fulfill({ json: { stargazers_count: 12 } }),
  );
});

for (const width of [1280, 390]) {
  test(`assistant sessions and chat at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/#/settings/tools");
    const entry = page.getByRole("button", { name: "助手", exact: true });
    await entry.click();
    const drawer = page.getByRole("dialog", { name: "助手", exact: true });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: "新建会话", exact: true }).click();
    await expect(drawer.getByRole("tab", { name: "会话 1", exact: true })).toHaveAttribute("aria-selected", "true");
    const composer = drawer.getByRole("textbox", { name: "消息", exact: true });
    await composer.fill("解释 Agent 与角色的区别");
    await drawer.getByRole("button", { name: "发送", exact: true }).click();
    await expect(drawer.getByText("已完成", { exact: true })).toBeVisible();
    await expect(drawer.locator(".agent-message--assistant")).toContainText("浏览器预览");
    await drawer.getByRole("button", { name: "新建会话", exact: true }).click();
    await expect(drawer.getByRole("tab", { name: "会话 2", exact: true })).toHaveAttribute("aria-selected", "true");
    await composer.fill("保留第二个会话的草稿");
    await drawer.getByRole("tab", { name: "会话 1", exact: true }).click();
    await expect(composer).toHaveValue("");
    await expect(drawer.locator(".agent-message--user")).toContainText("解释 Agent 与角色的区别");
    const bounds = await drawer.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: testInfo.outputPath(`assistant-${width}.png`) });
    await drawer.locator(".agent-drawer__close").click();
    await expect(drawer).toBeHidden();
    await expect(entry).toBeFocused();
    await entry.click();
    await drawer.getByRole("tab", { name: "会话 2", exact: true }).click();
    await expect(composer).toHaveValue("保留第二个会话的草稿");
    expect(errors).toEqual([]);
  });
}
