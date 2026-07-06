import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const apiBase = process.env.SHINSEKAI_API_BASE ?? "http://127.0.0.1:8787";
const projectRoot = process.env.SHINSEKAI_PROJECT_ROOT ?? path.resolve(process.cwd(), "..");
const hasLiveBridge = Boolean(process.env.SHINSEKAI_API_BASE && process.env.SHINSEKAI_PROJECT_ROOT);
const liveBridgeWorkflowPath = "test/e2e/live_bridge_runtime.yaml";

declare global {
  interface Window {
    __pluginSavePayloads?: Array<{ id: string; pageId: string; values: Record<string, unknown> }>;
    __SHINSEKAI_IPC__?: unknown;
  }
}

async function requestJson<T>(request: APIRequestContext, method: "get" | "post", endpoint: string, data?: unknown) {
  const response =
    method === "get"
      ? await request.get(`${apiBase}${endpoint}`)
      : await request.post(`${apiBase}${endpoint}`, { data });
  expect(response.ok(), `${method.toUpperCase()} ${endpoint}`).toBeTruthy();
  return (await response.json()) as T;
}

async function launchControlledLiveChat(request: APIRequestContext) {
  const characters = await requestJson<Array<{ name: string }>>(request, "get", "/api/characters");
  expect(characters.length).toBeGreaterThan(0);

  await requestJson(request, "post", "/api/chat/close", {});

  const historyPath = path.join(projectRoot, "data/chat_history", `playwright-live-${Date.now()}.json`);
  return requestJson<{
    runtimeMode?: string;
    sessionId?: string;
    wsUrl?: string;
  }>(request, "post", "/api/chat/launch", {
    backgroundName: "透明场景",
    characters: [characters[0].name],
    historyPath,
    resetHistory: false,
    scenario: "这是一个用于验证 React chat browser live interaction 的受控测试场景。",
    system: "你是一个简短回应的测试角色。",
    templateId: "playwright-live-controlled",
    templateName: "playwright-live-controlled",
    useCg: false,
    workflowPath: liveBridgeWorkflowPath,
  });
}

function field(page: Page, label: string) {
  return page.locator(".field-row").filter({ hasText: label }).first();
}

function fieldControl(page: Page, label: string, selector: string) {
  return field(page, label).locator(selector).first();
}

async function installPluginConfigurationMock(page: Page) {
  await page.addInitScript(() => {
    const plugin = {
      author: "E2E",
      description: "Configuration is provided dynamically.",
      directory: "plugins/e2e_frontend_config",
      enabled: true,
      entry: "e2e.plugin",
      id: "e2e.plugin",
      loaded: true,
      permissions: ["settings"],
      settingsPages: ["settings"],
      slots: ["settings-extension"],
      title: "E2E Plugin",
      toolsTabs: [],
      version: "1.0.0",
    };
    const configPage = {
      description: "Default description",
      i18n: {
        zh_CN: {
          description: "ZH page description",
          groups: {
            main: {
              fields: {
                displayName: { label: "Display Name", placeholder: "Name" },
                extra: { label: "Extra JSON" },
                mode: { label: "Mode", options: { auto: "Automatic", manual: "Manual" } },
              },
              title: "ZH Group",
            },
          },
          restartHint: "ZH Restart",
          title: "ZH Settings",
        },
      },
      id: "settings",
      kind: "settings",
      order: 0,
      pluginId: "e2e.plugin",
      pluginVersion: "1.0.0",
      restartHint: "Restart required",
      schema: [
        {
          fields: [
            { defaultValue: "Miku", key: "displayName", label: "Name", placeholder: "Name", type: "text" },
            {
              defaultValue: "auto",
              key: "mode",
              label: "Mode",
              options: [
                { label: "Auto", value: "auto" },
                { label: "Manual", value: "manual" },
              ],
              type: "select",
            },
            { defaultValue: { rate: 1 }, key: "extra", label: "Extra", span: "full", type: "json" },
          ],
          id: "main",
          title: "Main",
        },
      ],
      title: "Settings",
      values: { displayName: "Miku", extra: { rate: 1 }, mode: "auto" },
    };

    window.__pluginSavePayloads = [];
    window.__SHINSEKAI_IPC__ = {
      config: {
        get: async () => ({
          api_config: {},
          background_list: [],
          characters: [],
          system_config: { theme_color: "#2f7cff", ui_language: "zh_CN" },
        }),
      },
      files: {
        browse: async () => ({ cwd: "/", entries: [], roots: [] }),
        fileUrl: (value: string) => value,
        thumbnailUrl: (value: string) => value,
        openExternal: async () => undefined,
      },
      plugins: {
        appUpdateInfo: async () => ({ repo: "example/repo", version: "test" }),
        appUpdateRun: async () => ({ message: "updated", version: "test" }),
        appUpdateTags: async () => [],
        catalog: async () => [],
        getUi: async () => ({ pages: [configPage], plugin }),
        install: async () => plugin,
        list: async () => [plugin],
        repoTags: async () => [],
        saveUiConfig: async (id: string, pageId: string, values: Record<string, unknown>) => {
          window.__pluginSavePayloads?.push({ id, pageId, values });
          return { message: "Saved", page: { ...configPage, values }, plugin };
        },
        setEnabled: async () => plugin,
        uninstall: async () => ({ message: "uninstalled" }),
      },
    };
  });
}

test("API model dropdown closes when focus moves outside", async ({ page }) => {
  await page.goto("/#/settings/api");
  await expect(page.getByRole("heading", { exact: true, name: "API 配置" })).toBeVisible();

  const modelRow = field(page, "模型 ID");
  const modelInput = modelRow.locator("input").first();
  await modelInput.fill("deepseek-chat");
  await modelRow.locator(".editable-combo__button").click();

  const listbox = page.locator(".editable-combo__menu[role='listbox']");
  await expect(listbox).toBeVisible();
  await expect(listbox.getByRole("option", { name: "deepseek-chat" })).toBeVisible();

  await page.getByRole("heading", { exact: true, name: "API 配置" }).click();
  await expect(listbox).toBeHidden();
});

test("plugin configuration page renders dynamic i18n schema and saves edited values", async ({ page }) => {
  await installPluginConfigurationMock(page);
  await page.goto("/#/settings/plugins");

  const card = page.locator(".plugin-card").filter({ hasText: "E2E Plugin" });
  await expect(card).toBeVisible();
  await card.locator(".plugin-card__actions button").last().click();

  await expect(page.getByText("ZH page description")).toBeVisible();
  await expect(page.getByRole("heading", { name: "ZH Group" })).toBeVisible();
  await expect(fieldControl(page, "Display Name", "input")).toHaveValue("Miku");
  await expect(fieldControl(page, "Mode", ".custom-select__button")).toContainText("Automatic");

  await fieldControl(page, "Display Name", "input").fill("Rin");
  await fieldControl(page, "Mode", ".custom-select__button").click();
  await page.getByRole("option", { name: "Manual" }).click();
  await fieldControl(page, "Extra JSON", "textarea").fill('{"rate":2}');
  await fieldControl(page, "Extra JSON", "textarea").blur();
  await page.locator(".plugin-detail-page__footer button").click();

  await expect(page.locator(".toast__message").filter({ hasText: "ZH Restart" })).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => window.__pluginSavePayloads ?? []))
    .toEqual([
      {
        id: "e2e.plugin",
        pageId: "settings",
        values: { displayName: "Rin", extra: { rate: 2 }, mode: "manual" },
      },
    ]);
});

test("chat stage browser preview supports state-driven interaction flow", async ({ page }) => {
  await page.goto("/#/chat");

  await expect(page.locator(".dialog-layer")).toContainText("欢迎来到新世界");
  await expect(page.locator(".floating-toolbar__transport")).toHaveText("快照模式");
  await expect(page.locator(".floating-toolbar__status")).toHaveText("idle");

  await page.getByRole("button", { name: "继续" }).click();
  await expect(page.locator(".dialog-layer")).toContainText("选择：继续");
  await expect(page.locator(".floating-toolbar__status")).toHaveText("generating");

  const input = page.getByRole("textbox", { name: "输入对白" });
  await input.fill("你好，Nanami");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.locator(".dialog-layer")).toContainText("你好，Nanami");
  await expect(input).toHaveValue("");
  await expect(page.locator(".floating-toolbar__status")).toHaveText("streaming");

  await expect.poll(async () => page.locator(".floating-toolbar__status").textContent()).toBe("speaking");

  await page.getByRole("button", { name: "跳过" }).click();
  await expect(page.locator(".floating-toolbar__status")).toHaveText("idle");

  await page.getByRole("button", { name: "打开历史" }).click();
  const historyDialog = page.getByRole("dialog", { name: "对话历史记录" });
  await expect(historyDialog).toBeVisible();
  await expect(historyDialog).toContainText("你: 你好，Nanami");
  await historyDialog.locator(".dialog__header").getByRole("button", { name: "关闭" }).click();
  await expect(historyDialog).toBeHidden();

  await page.getByRole("button", { name: "暂停识别" }).click();
  await expect(page.locator(".floating-toolbar__status")).toHaveText("paused");
  await expect(page.getByRole("button", { name: "恢复识别" })).toBeVisible();
  await page.getByRole("button", { name: "恢复识别" }).click();
  await expect(page.locator(".floating-toolbar__status")).toHaveText("listening");

  const voiceLanguageSelect = page.locator(".floating-toolbar__voice-select [role='combobox']");
  await voiceLanguageSelect.click();
  await page.getByRole("option", { name: "English" }).click();
  await expect(voiceLanguageSelect).toContainText("English");

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
  await themeDialog.locator(".dialog__header").getByRole("button", { name: "关闭" }).click();
  await expect(themeDialog).toBeHidden();

  await page.getByRole("button", { name: "清空历史" }).click();
  const clearDialog = page.getByRole("dialog", { name: "清空历史" });
  await expect(clearDialog).toBeVisible();
  await clearDialog.getByRole("button", { name: "清空" }).click();
  await expect(page.locator(".dialog-layer")).toContainText("浏览器预览历史已清空");
  await expect(page.locator(".options-layer")).toBeHidden();
  await expect(page.locator(".toast__title").filter({ hasText: "历史已清空" })).toBeVisible();
});

async function exportCharacterPackage(request: APIRequestContext, name: string) {
  const result = await requestJson<{ path: string }>(request, "post", "/api/characters/export", { name });
  return path.resolve(projectRoot, result.path);
}

async function exportBackgroundPackage(request: APIRequestContext, name: string) {
  const result = await requestJson<{ path: string }>(request, "post", "/api/backgrounds/export", { name });
  return path.resolve(projectRoot, result.path);
}

test.describe.serial("live React functionality smoke", () => {
  test.skip(!hasLiveBridge, "Set SHINSEKAI_API_BASE and SHINSEKAI_PROJECT_ROOT to run live bridge smoke tests.");

  test("bridge endpoints expose config, domain lists, and plugin state", async ({ request }) => {
    const config = await requestJson<{
      api_config: { llm_provider: string };
      system_config: { ui_language: string };
    }>(request, "get", "/api/config");
    expect(config.api_config.llm_provider).toBeTruthy();
    expect(config.system_config.ui_language).toBeTruthy();

    const characters = await requestJson<Array<{ name: string }>>(request, "get", "/api/characters");
    const backgrounds = await requestJson<Array<{ name: string }>>(request, "get", "/api/backgrounds");
    const plugins = await requestJson<Array<{ directory?: string; entry: string; loaded: boolean; title: string }>>(
      request,
      "get",
      "/api/plugins",
    );
    expect(characters.length).toBeGreaterThan(0);
    expect(backgrounds.length).toBeGreaterThan(0);
    const moondream = plugins.find((plugin) => plugin.entry.includes("moondream_vision"));
    expect(moondream).toBeTruthy();
    expect(typeof moondream?.loaded).toBe("boolean");
    expect(moondream?.directory).toBe("plugins/moondream_vision");
  });

  test("all settings routes render from the live bridge", async ({ page }) => {
    const routes = [
      ["/#/settings/api", "API 配置"],
      ["/#/settings/characters", "人物设定"],
      ["/#/settings/backgrounds", "背景管理"],
      ["/#/settings/templates", "生成模板"],
      ["/#/settings/plugins", "插件"],
      ["/#/settings/tools", "小工具"],
      ["/#/settings/music-cover", "音乐翻唱流水线"],
      ["/#/settings/launch", "启动聊天"],
      ["/#/settings/system", "系统"],
    ] as const;

    for (const [route, title] of routes) {
      await page.goto(route);
      await expect(page.getByRole("heading", { name: title })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "设置中心导航" })).toBeVisible();
    }
  });

  test("API page dropdowns and save button are wired to the bridge", async ({ page }) => {
    await page.goto("/#/settings/api");
    await expect(page.getByRole("heading", { name: "API 配置" })).toBeVisible();

    const provider = fieldControl(page, "服务商", "select");
    await expect(provider).toBeEnabled();
    await provider.selectOption("Deepseek");
    await expect(provider).toHaveValue("Deepseek");
    await expect(fieldControl(page, "基础网址", "input")).toHaveValue("https://api.deepseek.com/v1");
    const modelInput = fieldControl(page, "模型 ID", "input");
    await expect(modelInput).toBeEnabled();
    const manualModelId = (await modelInput.inputValue()).trim() || `smoke-model-${Date.now()}`;
    await modelInput.fill(manualModelId);
    await expect(modelInput).toHaveValue(manualModelId);
    await provider.selectOption("ChatGPT");
    await expect(provider).toHaveValue("ChatGPT");

    const bundle = fieldControl(page, "整合包", "select");
    await bundle.selectOption("gptso");
    await expect(bundle).toHaveValue("gptso");
    await bundle.selectOption("genie");

    const asrLanguage = fieldControl(page, "识别语言", "select");
    await asrLanguage.selectOption("ja");
    await expect(asrLanguage).toHaveValue("ja");
    await asrLanguage.selectOption("");

    await page.getByRole("button", { name: /^保存$/ }).click();
    await expect(page.getByText("API 设定已保存")).toBeVisible();
  });

  test("character and background package file imports are usable", async ({ page, request }) => {
    const beforeCharacters = await requestJson<Array<{ name: string }>>(request, "get", "/api/characters");
    const characterPackage = await exportCharacterPackage(request, beforeCharacters[0].name);

    await page.goto("/#/settings/characters");
    await expect(page.getByRole("heading", { name: "人物设定" })).toBeVisible();
    await page.locator('input[type="file"][accept=".char,.cha"]').setInputFiles(characterPackage);
    await expect(page.getByText(path.basename(characterPackage))).toBeVisible();
    await page.getByRole("button", { name: /^导入$/ }).click();
    await expect
      .poll(async () => (await requestJson<Array<{ name: string }>>(request, "get", "/api/characters")).length, {
        timeout: 30_000,
      })
      .toBeGreaterThan(beforeCharacters.length);
    const afterCharacters = await requestJson<
      Array<{ name: string; sprites: Array<{ path: string; voice_path?: string }> }>
    >(request, "get", "/api/characters");
    const importedCharacter = afterCharacters.find(
      (character) => !beforeCharacters.some((before) => before.name === character.name),
    );
    expect(importedCharacter?.sprites[0]?.path).toBeTruthy();
    expect(importedCharacter?.sprites[0]?.path).not.toContain("\\");
    if (importedCharacter?.sprites[0]?.voice_path) {
      expect(importedCharacter.sprites[0].voice_path).not.toContain("\\");
    }
    const characterMedia = await request.get(
      `${apiBase}/api/media?path=${encodeURIComponent(importedCharacter?.sprites[0]?.path ?? "")}`,
    );
    expect(characterMedia.ok(), "imported character sprite should be loadable").toBeTruthy();

    const beforeBackgrounds = await requestJson<Array<{ name: string }>>(request, "get", "/api/backgrounds");
    const backgroundPackage = await exportBackgroundPackage(request, beforeBackgrounds[0].name);

    await page.goto("/#/settings/backgrounds");
    await expect(page.getByRole("heading", { name: "背景管理" })).toBeVisible();
    await page.locator('input[type="file"][accept=".bg"]').setInputFiles(backgroundPackage);
    await expect(page.getByText("已选择 1 个文件")).toBeVisible();
    await page.getByRole("button", { name: /^导入$/ }).click();
    await expect
      .poll(async () => (await requestJson<Array<{ name: string }>>(request, "get", "/api/backgrounds")).length, {
        timeout: 30_000,
      })
      .toBeGreaterThan(beforeBackgrounds.length);
    const afterBackgrounds = await requestJson<Array<{ name: string; sprites: Array<{ path: string }> }>>(
      request,
      "get",
      "/api/backgrounds",
    );
    const importedBackground = afterBackgrounds.find(
      (background) => !beforeBackgrounds.some((before) => before.name === background.name),
    );
    expect(importedBackground?.sprites[0]?.path).toBeTruthy();
    expect(importedBackground?.sprites[0]?.path).not.toContain("\\");
    const backgroundMedia = await request.get(
      `${apiBase}/api/media?path=${encodeURIComponent(importedBackground?.sprites[0]?.path ?? "")}`,
    );
    expect(backgroundMedia.ok(), "imported background image should be loadable").toBeTruthy();
  });

  test("template and launch controls keep dropdowns, checkboxes, and text inputs interactive", async ({ page }) => {
    await page.goto("/#/settings/templates");
    await expect(page.getByRole("heading", { name: "生成模板" })).toBeVisible();
    await fieldControl(page, "背景", "select").selectOption({ label: "透明场景" });
    const firstCharacter = page.locator(".character-check-grid input").first();
    await firstCharacter.check();
    await expect(firstCharacter).toBeChecked();
    await expect(page.getByRole("heading", { name: "用户情景" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "保存与启动" })).toBeVisible();

    await page.goto("/#/settings/launch");
    await expect(page.getByRole("heading", { name: "启动聊天" })).toBeVisible();
    await fieldControl(page, "背景", "select").selectOption({ label: "透明场景" });
    await fieldControl(page, "角色", "select").selectOption({ index: 0 });
    await fieldControl(page, "历史", "input").fill(path.join(projectRoot, "data/chat_history/smoke-history.json"));
    const useCg = fieldControl(page, "启用 ComfyUI", 'input[type="checkbox"]');
    await useCg.check();
    await expect(useCg).toBeChecked();
    await useCg.uncheck();
  });

  test("launch page opens the React chat stage on the live stream path", async ({ page, request }) => {
    test.setTimeout(60_000);

    const config = await requestJson<{
      system_config: { chat_ui_runtime_mode?: string };
    }>(request, "get", "/api/config");
    test.skip(
      String(config.system_config.chat_ui_runtime_mode ?? "")
        .trim()
        .toLowerCase() !== "react",
      "Live bridge config is not in react mode.",
    );

    await page.goto("/#/settings/launch");
    await expect(page.getByRole("heading", { name: "启动聊天" })).toBeVisible();

    await fieldControl(page, "背景", "[role='combobox']").click();
    await page.getByRole("option", { name: "透明场景" }).click();
    await fieldControl(page, "角色", "select").selectOption({ index: 0 });

    await page.getByRole("button", { name: "启动" }).click();

    await expect(page).toHaveURL(/#\/chat$/);
    await expect(page.locator(".dialog-layer")).toBeVisible();
    await expect(page.locator(".floating-toolbar")).toBeVisible();
    await expect(page.locator(".input-layer")).toBeVisible();
    await expect(page.locator(".floating-toolbar__transport")).not.toHaveText("");

    const snapshot = await requestJson<{
      runtimeMode?: string;
      sessionId?: string;
      wsUrl?: string;
    }>(request, "get", "/api/chat/snapshot");
    expect(snapshot.runtimeMode).toBe("react");
    expect(snapshot.sessionId).toBeTruthy();
    expect(snapshot.wsUrl).toBeTruthy();

    await page.getByRole("button", { name: "主题管理" }).click();
    const themeDialog = page.getByRole("dialog", { name: "聊天主题" });
    await expect(themeDialog).toBeVisible();
    await expect(themeDialog).toContainText("经典暗色");
    await expect(themeDialog).toContainText("浅色纸张");
    await themeDialog.locator(".dialog__header").getByRole("button", { name: "关闭" }).click();
    await expect(themeDialog).toBeHidden();
  });

  test("chat stage dedicated live route stays interactive without the settings shell", async ({ page, request }) => {
    test.setTimeout(60_000);

    const config = await requestJson<{
      system_config: { chat_ui_runtime_mode?: string };
    }>(request, "get", "/api/config");
    test.skip(
      String(config.system_config.chat_ui_runtime_mode ?? "")
        .trim()
        .toLowerCase() !== "react",
      "Live bridge config is not in react mode.",
    );

    const launchSnapshot = await launchControlledLiveChat(request);
    expect(launchSnapshot.runtimeMode).toBe("react");
    expect(launchSnapshot.sessionId).toBeTruthy();
    expect(launchSnapshot.wsUrl).toBeTruthy();

    try {
      await page.goto(`/?shinsekai_bridge=${encodeURIComponent(apiBase)}#/chat-stage`);

      await expect(page).toHaveURL(/#\/chat-stage$/);
      await expect(page.locator(".dialog-layer")).toContainText("欢迎来到新世界程序");
      await expect(page.locator(".floating-toolbar")).toBeVisible();
      await expect(page.getByRole("navigation", { name: "设置中心导航" })).toHaveCount(0);

      const input = page.getByRole("textbox", { name: "输入对白" });
      await input.fill("独立路由验证");
      await page.getByRole("button", { name: "发送" }).click();

      await expect(page.locator(".dialog-layer")).toContainText("收到消息：独立路由验证");
      await expect(page.getByRole("button", { name: "继续剧情" })).toBeVisible();

      await expect
        .poll(async () => {
          const snapshot = await requestJson<{
            historyEntries?: Array<{ text?: string }>;
            sessionId?: string;
            wsUrl?: string;
          }>(request, "get", "/api/chat/snapshot");
          const hasMessage = snapshot.historyEntries?.some((entry) =>
            String(entry.text ?? "").includes("独立路由验证"),
          );
          return `${snapshot.sessionId ?? ""}|${snapshot.wsUrl ?? ""}|${hasMessage ? "1" : "0"}`;
        })
        .toBe(`${launchSnapshot.sessionId}|${launchSnapshot.wsUrl}|1`);
    } finally {
      await requestJson(request, "post", "/api/chat/close", {});
    }
  });

  test("chat stage live bridge interaction flow stays state-driven in the browser", async ({ page, request }) => {
    test.setTimeout(60_000);

    const config = await requestJson<{
      system_config: { chat_ui_runtime_mode?: string };
    }>(request, "get", "/api/config");
    test.skip(
      String(config.system_config.chat_ui_runtime_mode ?? "")
        .trim()
        .toLowerCase() !== "react",
      "Live bridge config is not in react mode.",
    );

    const launchSnapshot = await launchControlledLiveChat(request);
    expect(launchSnapshot.runtimeMode).toBe("react");
    expect(launchSnapshot.sessionId).toBeTruthy();
    expect(launchSnapshot.wsUrl).toBeTruthy();

    try {
      await page.goto("/#/chat");

      await expect
        .poll(async () => {
          const value = (await page.locator(".floating-toolbar__transport").textContent())?.trim() ?? "";
          return value === "实时连接" || value === "轮询回退" ? value : "";
        })
        .not.toBe("");
      await expect(page.locator(".input-layer")).toBeVisible();
      await expect(page.locator(".options-layer")).toHaveCount(0);
      await expect(page.locator(".dialog-layer")).toContainText("欢迎来到新世界程序");

      const input = page.getByRole("textbox", { name: "输入对白" });
      await input.fill("第一句测试消息");
      await page.getByRole("button", { name: "发送" }).click();

      await expect(page.locator(".dialog-layer")).toContainText("收到消息：第一句测试消息");
      await expect(page.getByRole("button", { name: "继续剧情" })).toBeVisible();
      await expect(page.locator(".options-layer")).toBeVisible();

      await page.getByRole("button", { name: "继续剧情" }).click();
      await expect(page.locator(".dialog-layer")).toContainText("已选择：继续剧情");
      await expect(page.locator(".dialog-layer")).toContainText("已选择：继续剧情");
      await expect(page.locator(".options-layer")).toHaveCount(0);

      await page.locator(".dialog-layer").click();
      await expect(page.locator(".dialog-layer")).toContainText("下一段已展开。");

      await input.fill("触发打断测试");
      await page.getByRole("button", { name: "发送" }).click();
      await page.getByRole("button", { name: "跳过" }).click();
      await expect(page.locator(".dialog-layer")).toContainText("语音已打断：触发打断测试");

      await page.getByRole("button", { name: "打开历史" }).click();
      const historyDialog = page.getByRole("dialog", { name: "对话历史记录" });
      await expect(historyDialog).toBeVisible();
      await expect(historyDialog).toContainText("你: 第一句测试消息");
      await expect(historyDialog).toContainText("直播桥接测试：收到消息：第一句测试消息");
      await expect(historyDialog).toContainText("直播桥接测试：已选择：继续剧情");
      await historyDialog.locator(".dialog__header").getByRole("button", { name: "关闭" }).click();
      await expect(historyDialog).toBeHidden();

      await page.getByRole("button", { name: "暂停识别" }).click();
      await expect(page.getByRole("button", { name: "恢复识别" })).toBeVisible();
      await page.getByRole("button", { name: "恢复识别" }).click();
      await expect(page.getByRole("button", { name: "暂停识别" })).toBeVisible();

      const voiceLanguageSelect = page.locator(".floating-toolbar__voice-select [role='combobox']");
      await voiceLanguageSelect.click();
      await page.getByRole("option", { name: "English" }).click();
      await expect(voiceLanguageSelect).toContainText("English");
      await expect
        .poll(async () => {
          const snapshot = await requestJson<{ voiceLanguage?: string }>(request, "get", "/api/chat/snapshot");
          return snapshot.voiceLanguage;
        })
        .toBe("en");

      await page.getByRole("button", { name: "清空历史" }).click();
      const clearDialog = page.getByRole("dialog", { name: "清空历史" });
      await expect(clearDialog).toBeVisible();
      await clearDialog.getByRole("button", { name: "清空" }).click();
      await expect
        .poll(async () => {
          const history = await requestJson<Array<{ text: string }>>(request, "get", "/api/chat/history");
          return history.length;
        })
        .toBe(0);

      await page.getByRole("button", { name: "打开历史" }).click();
      const clearedHistoryDialog = page.getByRole("dialog", { name: "对话历史记录" });
      await expect(clearedHistoryDialog).toContainText("当前还没有历史记录。");
      await clearedHistoryDialog.locator(".dialog__header").getByRole("button", { name: "关闭" }).click();
      await expect(page.locator(".options-layer")).toHaveCount(0);

      await requestJson(request, "post", "/api/chat/close", {});
      await expect(page.locator(".chat-stage__notification")).toContainText("聊天会话已结束。");
      await expect(page.locator(".input-layer")).toHaveCount(0);
    } finally {
      await requestJson(request, "post", "/api/chat/close", {});
    }
  });

  test("chat stage live bridge reload restores snapshot state and keeps the session interactive", async ({
    page,
    request,
  }) => {
    test.setTimeout(60_000);

    const config = await requestJson<{
      system_config: { chat_ui_runtime_mode?: string };
    }>(request, "get", "/api/config");
    test.skip(
      String(config.system_config.chat_ui_runtime_mode ?? "")
        .trim()
        .toLowerCase() !== "react",
      "Live bridge config is not in react mode.",
    );

    const launchSnapshot = await launchControlledLiveChat(request);
    expect(launchSnapshot.runtimeMode).toBe("react");
    expect(launchSnapshot.sessionId).toBeTruthy();
    expect(launchSnapshot.wsUrl).toBeTruthy();

    try {
      await page.goto("/#/chat");

      await expect(page.locator(".input-layer")).toBeVisible();
      await expect(page.locator(".dialog-layer")).toContainText("欢迎来到新世界程序");

      const input = page.getByRole("textbox", { name: "输入对白" });
      await input.fill("刷新恢复测试");
      await page.getByRole("button", { name: "发送" }).click();

      await expect(page.locator(".dialog-layer")).toContainText("收到消息：刷新恢复测试");
      await expect(page.getByRole("button", { name: "继续剧情" })).toBeVisible();
      await expect(page.locator(".options-layer")).toBeVisible();

      await page.reload();

      await expect(page).toHaveURL(/#\/chat$/);
      await expect(page.locator(".input-layer")).toBeVisible();
      await expect(page.locator(".dialog-layer")).toContainText("收到消息：刷新恢复测试");
      await expect(page.getByRole("button", { name: "继续剧情" })).toBeVisible();
      await expect
        .poll(async () => {
          const value = (await page.locator(".floating-toolbar__transport").textContent())?.trim() ?? "";
          return value === "实时连接" || value === "轮询回退" ? value : "";
        })
        .not.toBe("");

      const recoveredSnapshot = await requestJson<{
        dialogText?: string;
        historyEntries?: Array<{ text?: string }>;
        sessionId?: string;
        wsUrl?: string;
      }>(request, "get", "/api/chat/snapshot");
      expect(recoveredSnapshot.sessionId).toBe(launchSnapshot.sessionId);
      expect(recoveredSnapshot.wsUrl).toBe(launchSnapshot.wsUrl);
      expect(recoveredSnapshot.dialogText).toContain("刷新恢复测试");
      expect(recoveredSnapshot.historyEntries?.some((entry) => String(entry.text ?? "").includes("刷新恢复测试"))).toBe(
        true,
      );

      await page.getByRole("button", { name: "继续剧情" }).click();
      await expect(page.locator(".dialog-layer")).toContainText("已选择：继续剧情");
      await expect(page.locator(".options-layer")).toHaveCount(0);

      await page.locator(".dialog-layer").click();
      await expect(page.locator(".dialog-layer")).toContainText("下一段已展开。");
    } finally {
      await requestJson(request, "post", "/api/chat/close", {});
    }
  });

  test("chat stage live bridge clears closed markers and restores input when runtime stays online", async ({
    page,
    request,
  }) => {
    test.setTimeout(60_000);

    const config = await requestJson<{
      system_config: { chat_ui_runtime_mode?: string };
    }>(request, "get", "/api/config");
    test.skip(
      String(config.system_config.chat_ui_runtime_mode ?? "")
        .trim()
        .toLowerCase() !== "react",
      "Live bridge config is not in react mode.",
    );

    const launchSnapshot = await launchControlledLiveChat(request);
    expect(launchSnapshot.runtimeMode).toBe("react");
    expect(launchSnapshot.sessionId).toBeTruthy();
    expect(launchSnapshot.wsUrl).toBeTruthy();

    try {
      await page.goto(`/?shinsekai_bridge=${encodeURIComponent(apiBase)}#/chat`);

      await expect(page.locator(".input-layer")).toBeVisible();
      const input = page.getByRole("textbox", { name: "输入对白" });
      await input.fill("触发关闭恢复测试");
      await page.getByRole("button", { name: "发送" }).click();

      await expect(page.locator(".chat-stage__notification")).toContainText("聊天会话已结束。");
      await expect(page.locator(".input-layer")).toHaveCount(0);

      await expect
        .poll(async () => {
          const snapshot = await requestJson<{ notificationText?: string; sessionClosedReason?: string }>(
            request,
            "get",
            "/api/chat/snapshot",
          );
          return `${snapshot.sessionClosedReason ?? ""}|${snapshot.notificationText ?? ""}`;
        })
        .toBe("聊天会话已结束。|聊天会话已结束。");

      await page.getByRole("button", { name: "暂停识别" }).click();
      await expect(page.locator(".input-layer")).toBeVisible();
      await expect(page.locator(".chat-stage__notification")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "恢复识别" })).toBeVisible();

      const recoveredInput = page.getByRole("textbox", { name: "输入对白" });
      await recoveredInput.fill("恢复后继续");
      await page.getByRole("button", { name: "发送" }).click();
      await expect(page.locator(".dialog-layer")).toContainText("收到消息：恢复后继续");

      await expect
        .poll(async () => {
          const snapshot = await requestJson<{
            historyEntries?: Array<{ text?: string }>;
            notificationText?: string;
            sessionClosedReason?: string;
          }>(request, "get", "/api/chat/snapshot");
          const hasRecoveredText = snapshot.historyEntries?.some((entry) =>
            String(entry.text ?? "").includes("恢复后继续"),
          );
          return `${snapshot.sessionClosedReason ?? ""}|${snapshot.notificationText ?? ""}|${hasRecoveredText ? "1" : "0"}`;
        })
        .toBe("||1");
    } finally {
      await requestJson(request, "post", "/api/chat/close", {});
    }
  });

  test("plugin manager tabs and manifest status controls render from live plugin state", async ({ page }) => {
    await page.goto("/#/settings/plugins");
    await expect(page.getByRole("heading", { name: "插件" })).toBeVisible();

    const moondreamCard = page.locator(".plugin-card").filter({ hasText: "moondream_vision" }).first();
    await expect(moondreamCard).toBeVisible();
    await expect(moondreamCard.locator(".plugin-card__status")).toContainText(/已启用|已停用|未加载/);

    await page.getByRole("tab", { name: "发现" }).click();
    await expect(page.getByRole("heading", { name: "发现" })).toBeVisible();
    await page.getByRole("tab", { name: "MCP" }).click();
    await expect(page.getByRole("heading", { exact: true, name: "MCP" })).toBeVisible();
    await page.getByRole("tab", { name: "已安装" }).click();
    await expect(page.getByRole("heading", { name: "已安装" })).toBeVisible();
  });

  test("tools crop action and music-cover save action call backend endpoints", async ({ page }) => {
    await page.goto("/#/settings/tools");
    await expect(page.getByRole("heading", { name: "小工具" })).toBeVisible();
    await fieldControl(page, "输入目录", "input").fill(path.resolve(process.cwd(), "../assets/system/picture"));
    await fieldControl(page, "输出目录", "input").fill(path.join(projectRoot, "output/smoke-crop"));
    await fieldControl(page, "保留上半部分比例", "input").fill("0.5");
    await page.getByRole("button", { name: "确认裁剪" }).click();
    await expect(page.locator(".tools-page__output")).toHaveValue(/成功裁剪/);

    await page.goto("/#/settings/music-cover");
    await expect(page.getByRole("heading", { name: "音乐翻唱流水线" })).toBeVisible();
    await fieldControl(page, "模型版本", "select").selectOption("v2");
    await fieldControl(page, "音高 method", "select").selectOption("rmvpe");
    await fieldControl(page, "来源", "select").selectOption("url");
    await page.getByRole("button", { name: "保存翻唱流水线配置" }).click();
    await expect(page.getByText("音乐翻唱配置已保存。")).toBeVisible();
  });
});
