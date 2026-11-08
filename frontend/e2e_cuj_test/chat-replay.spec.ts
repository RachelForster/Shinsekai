import { expect, test } from "@playwright/test";

test.setTimeout(90_000);
test.use({ actionTimeout: 15_000 });

test.beforeEach(async ({ context, page }) => {
  await context.route("**/replay-cuj*", (route) =>
    route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body><div id="root"></div><script type="module">
      import RefreshRuntime from "/@react-refresh";
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {};
      window.$RefreshSig$ = () => type => type;
      window.__vite_plugin_react_preamble_installed__ = true;
      import { createBrowserPreviewPlatform } from "/src/shared/platform/browserPreviewPlatform.ts";
      const platform = createBrowserPreviewPlatform();
      const base = await platform.chat.getSnapshot();
      const entries = Array.from({ length: 130 }, (_, index) => ({
        id: "history-" + index, key: "key-" + index, role: "assistant", position: index + 1,
        text: "Mio: " + (index === 17 ? "start mark" : index === 21 ? "end mark" : "line " + index),
        body: index === 17 ? "start mark" : index === 21 ? "end mark" : "line " + index,
        speaker: "Mio", voiceUrls: [], voiceSource: "", voiceLabel: "Mio · test", canGenerate: true, frame: null,
      }));
      const snapshot = { ...base, sessionId: "replay-cuj", status: "idle", historyEntries: entries,
        options: [], inputDraft: "draft kept", dialogText: "live dialogue", bgmPath: "", audioCommands: [] };
      Object.assign(entries[16], { role: "user", revertUserIndex: 4 });
      Object.assign(entries[19], { role: "options", speaker: "选项", text: "选项: Left / Right", body: "Left / Right", options: ["Left", "Right"], selectedIndex: 1, canGenerate: false });
      const fixture = { commands: [], controls: [], started: null, cancelled: false, requests: [], resolvers: {} };
      window.REPLAY_CUJ = fixture;
      let listener, seq = 0, selected = [], progress, timer;
      const emit = event => { snapshot.eventSeq = ++seq; listener?.({ ...event, seq, v: 1, ts: Date.now() }); };
      const state = () => emit({ type: "replay.state", replay: { ...progress } });
      const schedule = () => {
        clearTimeout(timer);
        if (progress.paused || progress.waiting || fixture.cancelled) return;
        timer = setTimeout(() => {
          if (progress.index === selected.length - 1) {
            progress.ended = true; progress.paused = true; state();
          } else { progress.index++; show(); }
        }, 1000);
      };
      const show = () => {
        const entry = selected[progress.index];
        state();
        emit({ type: "presentation.restore", presentation: { options: [], backgroundPath: "", cgPath: "", sprites: [], stats: [] } });
        emit({ type: "dialog.end", speaker: entry.speaker, color: "", isSystem: false, animate: !progress.paused, fullHtml: "<p>" + entry.body + "</p>" });
        if (entry.options) emit({ type: "options.show", options: entry.options, selectedIndex: entry.selectedIndex });
        schedule();
      };
      platform.chat.getSnapshot = async () => structuredClone(snapshot);
      platform.chat.subscribeEvents = next => { listener = next; return () => { if (listener === next) listener = null; }; };
      platform.chat.getHistory = async () => structuredClone(entries);
      platform.chat.prepareReplay = async () => ({ id: "replay-plan", sessionId: "replay-cuj", historyCount: entries.length,
        branchId: "main", branchLabel: "", entries: structuredClone(entries) });
      platform.chat.startReplay = async (id, startKey, endKey, generate) => {
        fixture.started = { id, startKey, endKey, generate }; fixture.cancelled = false;
        selected = entries.slice(entries.findIndex(entry => entry.key === startKey), entries.findIndex(entry => entry.key === endKey) + 1);
        progress = { id, index: 0, total: selected.length, paused: false, ended: false, waiting: generate, error: "" };
        if (generate) {
          fixture.requests.push(selected[0].key);
          fixture.resolvers[selected[0].key] = () => { if (fixture.cancelled) return; progress.waiting = false; state(); schedule(); };
        }
        show();
      };
      platform.chat.generateReplayVoice = async (id, key) => {
        fixture.requests.push(key);
        return new Promise(resolve => { fixture.resolvers[key] = resolve; });
      };
      platform.chat.controlReplay = async (id, control) => {
        fixture.controls.push(control);
        if (control.action === "pause") progress.paused = true;
        if (control.action === "play") progress.paused = false;
        if (control.action === "seek") { progress.index = control.index; progress.paused = !control.playing; progress.ended = false; show(); return; }
        if (control.action === "skip-voice") { progress.waiting = false; }
        state(); schedule();
      };
      platform.chat.cancelReplay = async () => {
        fixture.cancelled = true; clearTimeout(timer);
        if (progress) {
          emit({ type: "presentation.restore", presentation: { characterName: "Mio", dialogHtml: "", dialogText: "live dialogue", options: [] } });
          emit({ type: "replay.state", replay: null });
        }
      };
      platform.chat.command = async command => { fixture.commands.push(command); return structuredClone(snapshot); };
      const getConfig = platform.config.get.bind(platform.config);
      platform.config.get = async () => { const config = await getConfig(); config.system_config.ui_language = "en"; return config; };
      window.__SHINSEKAI_IPC__ = platform;
      await import("/src/main.tsx");
    </script></body></html>`,
    }),
  );
  await page.goto("/replay-cuj#/chat-stage");
  await expect(page.getByRole("button", { name: "打开历史", exact: true })).toBeVisible({ timeout: 60_000 });
});

test("selects an inclusive clip through search, locates its end, and preserves live input", async ({ page }) => {
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("button", { name: "从头回放", exact: true }).click();
  await expect(history.getByText("第 1–130 条，共 130 条")).toBeVisible();
  await history.getByRole("button", { name: "取消", exact: true }).click();
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("button", { name: "从这里回放", exact: true }).click();
  await history.getByRole("button", { name: "更改终点", exact: true }).click();
  await history.getByRole("searchbox").fill("end mark");
  await history.getByRole("button", { name: "到这里结束", exact: true }).click();
  await expect(history.getByText("第 18–22 条，共 5 条")).toBeVisible();
  await history.getByRole("button", { name: "直接回放", exact: true }).click();
  const replay = page.locator(".chat-replay-controls");
  await expect(replay).toBeVisible();
  await expect(page.locator(".top-stage-tools__state")).toHaveText("replaying");
  await expect(page.locator(".input-layer__input")).toBeVisible();
  await expect(page.locator(".input-layer__input")).toBeDisabled();
  await expect(page.locator(".dialog-layer")).toContainText("start mark");
  await expect(replay).toContainText("片段第 1 / 5 条");
  await replay.getByRole("button", { name: "定位", exact: true }).click();
  const locate = page.getByRole("dialog", { name: "定位", exact: true });
  await expect(locate.getByRole("button", { name: "跳转到这里", exact: true })).toHaveCount(5);
  await locate.getByRole("button", { name: "跳转到这里", exact: true }).last().click();
  await expect(replay).toContainText("片段第 5 / 5 条");
  await replay.getByRole("button", { name: "播放", exact: true }).click();
  await expect(replay).toContainText("片段回放结束");
  await replay.getByRole("button", { name: "返回历史", exact: true }).click();
  await expect(history.getByRole("searchbox")).toHaveValue("end mark");
  await history.getByRole("button", { name: "关闭", exact: true }).last().click();
  await expect(page.locator(".input-layer__input")).toHaveValue("draft kept");
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.started)).toMatchObject({
    startKey: "key-17",
    endKey: "key-21",
    generate: false,
  });
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.commands)).toEqual([]);
});

test("can skip missing speech while synthesis is pending, and ignores completion after exit", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("button", { name: "从这里回放", exact: true }).click();
  await history.getByRole("button", { name: "更改终点", exact: true }).click();
  await history.getByRole("button", { name: "到这里结束", exact: true }).click();
  await history.getByRole("button", { name: "边播放边补全语音", exact: true }).click();
  const replay = page.locator(".chat-replay-controls");
  await expect(replay).toBeVisible();
  await expect(replay).toContainText("正在生成本句语音");
  await expect(page.locator(".dialog-layer")).toContainText("start mark");
  expect(
    await page.locator(".dialog-stack").evaluate((element) => element.getBoundingClientRect().bottom),
  ).toBeLessThan(await replay.evaluate((element) => element.getBoundingClientRect().top));
  await page.screenshot({ path: "test-results/replay-mobile.png" });
  await replay.getByRole("button", { name: "跳过本句语音", exact: true }).click();
  await expect(replay).toContainText("片段回放结束");
  await replay.getByRole("button", { name: "回到聊天", exact: true }).click();
  await expect(replay).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (window as any).REPLAY_CUJ.cancelled)).toBe(true);
  await page.evaluate(() =>
    (window as any).REPLAY_CUJ.resolvers["key-17"]({
      voiceUrls: ["late.wav"],
      voiceSource: "generated",
      voiceLabel: "Mio",
    }),
  );
  await expect(page.locator(".input-layer__input")).toHaveValue("draft kept");
  await expect(page.locator(".chat-replay-controls")).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.requests)).toEqual(["key-17"]);
});

test("puts replay beside existing icon actions and highlights the historical choice read-only", async ({ page }) => {
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("searchbox").fill("line 16");
  const row = history.locator(".chat-history__entry").filter({ hasText: "line 16" });
  await expect(row.locator(".chat-history__actions")).toHaveCount(1);
  await expect(row.locator(".chat-history__actions > button")).toHaveCount(3);
  await expect(row.getByRole("button", { name: "从这里回放", exact: true }).locator("svg")).toHaveCount(1);
  const bounds = await row
    .locator(".chat-history__actions > button")
    .evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().top));
  expect(new Set(bounds).size).toBe(1);
  await history.getByRole("searchbox").fill("Left / Right");
  await history.getByRole("button", { name: "从这里回放", exact: true }).click();
  await history.getByRole("button", { name: "直接回放", exact: true }).click();
  await expect(page.locator('.options-layer__item[data-replay-selected="true"]')).toContainText("Right");
  await expect(page.locator('.options-layer__item[data-replay-selected="true"]')).toContainText("当时的选择");
  await expect(page.locator(".options-layer__button").first()).toBeDisabled();
  await expect(page.locator(".options-layer__button").last()).toBeDisabled();
  expect(
    await page.locator(".options-layer").evaluate((element) => element.getBoundingClientRect().bottom),
  ).toBeLessThan(
    await page.locator(".chat-replay-controls").evaluate((element) => element.getBoundingClientRect().top),
  );
  await page.screenshot({ path: "test-results/replay-choice.png" });
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.commands)).toEqual([]);
  await page.evaluate(() => (window as any).__SHINSEKAI_IPC__.chat.cancelReplay("replay-plan"));
  await expect(page.locator(".chat-replay-controls")).toHaveCount(0);
  await expect(page.locator(".input-layer__input")).toBeEnabled();
  await expect(page.locator(".dialog-layer")).toContainText("live dialogue");
});
