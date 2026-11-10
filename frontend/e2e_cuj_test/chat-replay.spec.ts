import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

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
      Object.assign(entries[16], {
        role: "user", revertUserIndex: 4, speaker: "You",
        body: "line 16, can you say hello?", text: "You: line 16, can you say hello?",
      });
      Object.assign(entries[19], { role: "options", speaker: "选项", text: "选项: Left / Right", body: "Left / Right", options: ["Left", "Right"], selectedIndex: 1, canGenerate: false });
      const fixture = { commands: [], controls: [], started: null, cancelled: false, requests: [], resolvers: {} };
      window.REPLAY_CUJ = fixture;
      let listener, seq = 0, selected = [], progress, timer, epoch = 0;
      const emit = event => { snapshot.eventSeq = ++seq; listener?.({ ...event, seq, v: 1, ts: Date.now() }); };
      const state = () => emit({ type: "replay.state", replay: { ...progress } });
      const schedule = () => {
        clearTimeout(timer);
        if (progress.paused || progress.waiting || fixture.cancelled) return;
        if (progress.input?.phase === "typing") {
          timer = setTimeout(() => {
            const entry = selected[progress.index];
            progress.input = { ...progress.input, phase: "submitting" };
            state();
            emit({ type: "dialog.end", speaker: entry.speaker, color: "", isSystem: false, animate: false, fullHtml: "<p>" + entry.body + "</p>" });
            schedule();
          }, progress.input.durationMs + 220);
          return;
        }
        timer = setTimeout(() => {
          progress.input = undefined;
          if (progress.index === selected.length - 1) {
            progress.ended = true; progress.paused = true; state();
          } else { progress.index++; show(); }
        }, progress.input?.phase === "submitting" ? 2400 : 1000);
      };
      const show = () => {
        const entry = selected[progress.index];
        progress.input = entry.role === "user" ? { phase: "typing", text: entry.body, durationMs: 1500, epoch: ++epoch } : undefined;
        state();
        const sprites = entry.role === "assistant" && !entry.frame ? [{
          id: "Mio", label: "Mio", path: new URL("/chat-empty-catgirl.png", location.origin).href,
          avatarType: "static", modelUrl: "", slot: 0,
        }] : [];
        emit({ type: "presentation.restore", presentation: { options: [], backgroundPath: "", cgPath: "", sprites, stats: [] } });
        if (entry.role !== "user") emit({ type: "dialog.end", speaker: entry.speaker, color: "", isSystem: false, animate: !progress.paused, fullHtml: "<p>" + entry.body + "</p>" });
        if (entry.options) emit({ type: "options.show", options: entry.options, selectedIndex: entry.selectedIndex });
        if (fixture.recordingAudio) {
          emit({ type: "bgm.change", url: fixture.recordingAudio.bgm });
          emit({ type: "tts.play", url: fixture.recordingAudio.voice, playbackId: "recorded-voice", characterName: "Mio", volume: 0.6 });
          emit({ type: "effect.play", url: fixture.recordingAudio.effect });
        }
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
  const placement = await page.locator(".dialog-toolbar-layer").getAttribute("data-placement");
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("button", { name: "回放/分享", exact: true }).click();
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("checkbox", { name: "选择第 18 条消息" }).click();
  await history.getByRole("searchbox").fill("end mark");
  await expect(history.getByText("已选 1 条")).toBeVisible();
  await history.getByRole("button", { name: "选到此处", exact: true }).click();
  await expect(history.getByText("已选 5 条")).toBeVisible();
  await history.getByRole("button", { name: "回放", exact: true }).click();
  await expect(history.getByText("第 18–22 条，共 5 条")).toBeVisible();
  await history.getByRole("button", { name: "直接回放", exact: true }).click();
  const replay = page.locator(".chat-replay-controls");
  const handle = page.getByRole("button", { name: "显示回放控制", exact: true });
  await page.mouse.move(0, 0);
  await expect(replay).toBeHidden();
  await handle.hover();
  await expect(replay).toBeVisible();
  await expect(page.locator(".dialog-toolbar-layer")).toHaveAttribute("data-placement", placement!);
  expect((await replay.boundingBox())!.height).toBeLessThan(38);
  const bar = (await replay.boundingBox())!;
  const field = (await page.locator(".input-layer").boundingBox())!;
  expect(Math.abs(bar.x - field.x)).toBeLessThan(1);
  expect(Math.abs(bar.width - field.width)).toBeLessThan(1);
  expect(field.y - bar.y - bar.height).toBeCloseTo(12, 0);
  await page.mouse.move(0, 0);
  await expect(replay).toBeHidden();
  await handle.hover();
  await expect(page.locator(".top-stage-tools__state")).toHaveText("replaying");
  await expect(page.locator(".input-layer__input")).toBeVisible();
  await expect(page.locator(".input-layer__input")).toBeDisabled();
  await expect(page.locator(".dialog-layer")).toContainText("start mark");
  const position = replay.locator(".chat-replay-position");
  await expect(position).toHaveText("1/5");
  await expect(replay).not.toContainText("Mio · test");
  const portrait = page.getByAltText("Mio", { exact: true });
  await expect(portrait).toBeVisible();
  await expect.poll(() => portrait.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await replay.getByRole("button", { name: "暂停", exact: true }).click();
  const timeline = replay.getByRole("slider", { name: "回放进度", exact: true });
  await timeline.press("End");
  await expect(position).toHaveText("5/5");
  await timeline.press("Home");
  await expect(position).toHaveText("1/5");
  const track = (await timeline.boundingBox())!;
  const seekCount = () =>
    page.evaluate(() => (window as any).REPLAY_CUJ.controls.filter((control: any) => control.action === "seek").length);
  const beforeDrag = await seekCount();
  await page.mouse.move(track.x + track.width / 4, track.y + track.height / 2);
  await page.mouse.down();
  await page.mouse.move(track.x + (track.width * 3) / 4, track.y + track.height / 2, { steps: 5 });
  expect(await seekCount()).toBe(beforeDrag);
  await page.mouse.up();
  await expect(position).toHaveText("4/5");
  expect(await seekCount()).toBe(beforeDrag + 1);
  await replay.getByRole("button", { name: "定位", exact: true }).click();
  const locate = page.getByRole("dialog", { name: "定位", exact: true });
  await expect(locate.getByRole("button", { name: "跳转到这里", exact: true })).toHaveCount(5);
  await locate.getByRole("button", { name: "跳转到这里", exact: true }).last().click();
  await handle.hover();
  await expect(position).toHaveText("5/5");
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
  const share = history.getByRole("button", { name: "回放/分享", exact: true });
  await expect(share).toHaveText("回放/分享");
  const archive = (await history.locator(".chat-history__voice-toggle").boundingBox())!;
  const shareBounds = (await share.boundingBox())!;
  expect(shareBounds.x).toBeGreaterThan(archive.x + archive.width);
  expect(shareBounds.y).toBeLessThan(archive.y + archive.height);
  await share.click();
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("checkbox", { name: "选择第 18 条消息" }).click();
  await history.getByRole("button", { name: "回放", exact: true }).click();
  await history.getByRole("checkbox", { name: "补全缺失语音", exact: true }).check();
  await history.getByRole("button", { name: "直接回放", exact: true }).click();
  const replay = page.locator(".chat-replay-controls");
  await page.getByRole("button", { name: "显示回放控制", exact: true }).hover();
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

test("types and visibly sends a historical user message without sending a live chat command", async ({ page }) => {
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("button", { name: "回放/分享", exact: true }).click();
  await history.getByRole("searchbox").fill("line 16");
  await history.getByRole("checkbox", { name: "选择第 17 条消息" }).click();
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("checkbox", { name: "选择第 18 条消息" }).click();
  await history.getByRole("button", { name: "回放", exact: true }).click();
  await history.getByRole("button", { name: "直接回放", exact: true }).click();

  const input = page.locator(".input-layer__input");
  const message = "line 16, can you say hello?";
  await expect(input).toBeDisabled();
  await expect.poll(() => input.inputValue()).toMatch(/^line/);
  await expect(input).not.toHaveValue(message);
  await page.waitForFunction(
    (text) => document.querySelector<HTMLInputElement>(".input-layer__input")?.value === text,
    message,
  );
  await expect(page.getByText("已发送", { exact: true })).toBeVisible();
  await expect(input).toHaveValue("");
  await expect(page.locator(".dialog-layer")).toContainText(message);
  const submittedAt = Date.now();
  await expect(page.locator(".dialog-layer")).toContainText("start mark");
  expect(Date.now() - submittedAt).toBeGreaterThan(1900);
  await page.keyboard.press("Escape");
  await expect(input).toHaveValue("draft kept");
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.commands)).toEqual([]);
});

test("preserves normal history actions and highlights the historical choice read-only", async ({ page }) => {
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("searchbox").fill("line 16");
  const row = history.locator(".chat-history__entry").filter({ hasText: "line 16" });
  await expect(row.locator(".chat-history__actions")).toHaveCount(1);
  await expect(row.locator(".chat-history__actions > button")).toHaveCount(2);
  const bounds = await row
    .locator(".chat-history__actions > button")
    .evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().top));
  expect(new Set(bounds).size).toBe(1);
  await history.getByRole("button", { name: "回放/分享", exact: true }).click();
  await expect(row.locator(".chat-history__actions")).toHaveCount(0);
  await history.getByRole("searchbox").fill("Left / Right");
  await history.getByRole("checkbox", { name: "选择第 20 条消息" }).click();
  await history.getByRole("button", { name: "回放", exact: true }).click();
  await history.getByRole("button", { name: "直接回放", exact: true }).click();
  await page.getByRole("button", { name: "显示回放控制", exact: true }).hover();
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

test("drag-selects a range and keeps extending it while the pointer is at the scroll edge", async ({ page }) => {
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("button", { name: "回放/分享", exact: true }).click();
  const body = history.locator(".chat-history-dialog__body");
  const start = history.locator('[data-history-entry-id="history-17"]');
  await start.scrollIntoViewIfNeeded();
  const from = (await start.boundingBox())!;
  const viewport = (await body.boundingBox())!;
  const scroll = await body.evaluate((element) => element.scrollTop);
  await page.mouse.move(from.x + 25, from.y + 24);
  await page.mouse.down();
  await page.mouse.move(from.x + 25, viewport.y + viewport.height - 7, { steps: 9 });
  await expect.poll(() => body.evaluate((element) => element.scrollTop)).toBeGreaterThan(scroll + 160);
  await expect.poll(() => history.getByRole("checkbox", { checked: true }).count()).toBeGreaterThan(4);
  await page.mouse.up();
  await expect(start).toHaveAttribute("data-history-selected", "true");
  await expect(history.locator('[data-history-entry-id="history-19"]')).toHaveAttribute(
    "data-history-selected",
    "true",
  );
  await page.screenshot({ path: "test-results/replay-history-selection.png" });
});

test("copies and screenshots only the checked messages, and explains gaps before replay", async ({ context, page }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("button", { name: "回放/分享", exact: true }).click();
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("checkbox", { name: "选择第 18 条消息" }).click();
  await history.getByRole("searchbox").fill("end mark");
  await history.getByRole("checkbox", { name: "选择第 22 条消息" }).click();
  await history.getByRole("button", { name: "复制", exact: true }).click();
  await expect(history.getByText("已复制所选消息")).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied.replaceAll("\r\n", "\n")).toBe("Mio: start mark\n\nMio: end mark");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    history.getByRole("button", { name: "生成截图", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.png$/);
  const png = await readFile((await download.path())!);
  expect(png.subarray(1, 4).toString()).toBe("PNG");
  expect(png.readUInt32BE(20)).toBe(368);
  const preview = page.getByRole("dialog", { name: "截图已生成" });
  await expect(preview.getByRole("img", { name: "截图已生成" })).toBeVisible();
  await expect(preview.locator("code")).toHaveText(download.suggestedFilename());
  await preview.getByRole("button", { name: "关闭" }).click();
  await history.getByRole("button", { name: "回放", exact: true }).click();
  await expect(history.getByText("第 18–22 条，共 5 条")).toBeVisible();
  await expect(history.getByText("回放和视频会包含首尾之间未勾选的消息。")).toBeVisible();
  await history.getByRole("button", { name: "返回多选", exact: true }).click();
  await expect(history.getByText("已选 2 条")).toBeVisible();
});

async function mockWindowCapture(page: Page, dismissFirst = false) {
  await page.evaluate((dismissFirst) => {
    const fixture = (window as any).REPLAY_CUJ;
    fixture.mixedTracks = [];
    const createDestination = AudioContext.prototype.createMediaStreamDestination;
    AudioContext.prototype.createMediaStreamDestination = function () {
      const destination = createDestination.call(this);
      fixture.mixedTracks.push(destination.stream.getAudioTracks()[0]);
      return destination;
    };
    let dismiss = dismissFirst;
    navigator.mediaDevices.getDisplayMedia = async (options) => {
      fixture.systemAudioRequested = options?.audio;
      if (dismiss) {
        dismiss = false;
        throw new DOMException("Dismissed", "NotAllowedError");
      }
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 64;
      const ctx = canvas.getContext("2d")!;
      const stream = canvas.captureStream(24);
      const track = stream.getVideoTracks()[0];
      fixture.captureTrack = track;
      fixture.captureFrames = 0;
      const frame = () => {
        fixture.captureFrames += 1;
        ctx.fillStyle = Math.floor(performance.now() / 100) % 2 ? "#ffffff" : "#0000ff";
        ctx.fillRect(0, 0, 64, 64);
        if (track.readyState === "live") requestAnimationFrame(frame);
      };
      frame();
      return stream;
    };
  }, dismissFirst);
}

test("records the stage mix even when the capture window supplies only video", async ({ page }) => {
  await mockWindowCapture(page, true);
  await page.evaluate(() => {
    const fixture = (window as any).REPLAY_CUJ;
    const tone = (hz: number) => {
      const sampleRate = 16_000;
      const length = sampleRate;
      const buffer = new ArrayBuffer(44 + length * 2);
      const wav = new DataView(buffer);
      wav.setUint32(0, 0x52494646); // RIFF
      wav.setUint32(4, buffer.byteLength - 8, true);
      wav.setUint32(8, 0x57415645); // WAVE
      wav.setUint32(12, 0x666d7420); // fmt
      wav.setUint32(16, 16, true);
      wav.setUint16(20, 1, true);
      wav.setUint16(22, 1, true);
      wav.setUint32(24, sampleRate, true);
      wav.setUint32(28, sampleRate * 2, true);
      wav.setUint16(32, 2, true);
      wav.setUint16(34, 16, true);
      wav.setUint32(36, 0x64617461); // data
      wav.setUint32(40, length * 2, true);
      for (let i = 0; i < length; i += 1) {
        wav.setInt16(44 + i * 2, 6000 * Math.sin((2 * Math.PI * hz * i) / sampleRate), true);
      }
      return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
    };
    fixture.recordingAudio = { bgm: tone(331), voice: tone(607), effect: tone(929) };
  });
  await page.locator(".dialog-toolbar-layer").hover();
  await page.getByRole("button", { name: "打开历史", exact: true }).click();
  const history = page.getByRole("dialog", { name: "对话历史记录" });
  await history.getByRole("button", { name: "回放/分享", exact: true }).click();
  await history.getByRole("searchbox").fill("start mark");
  await history.getByRole("checkbox", { name: "选择第 18 条消息" }).click();
  await history.getByRole("button", { name: "生成视频", exact: true }).click();
  await expect(history.getByText("第 18–18 条，共 1 条")).toBeVisible();
  const record = history.getByRole("button", { name: "选择录制窗口", exact: true });
  await record.click();
  await expect(record).toBeEnabled();
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.started)).toBeNull();
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.mixedTracks[0].readyState)).toBe("ended");
  const pending = page.waitForEvent("download");
  await record.click();
  await expect(page.locator('.chat-stage[data-replay-recording="true"]')).toBeVisible();
  await expect(page.locator(".chat-replay-player")).toHaveCSS("opacity", "0");
  const video = await pending;
  expect(video.suggestedFilename()).toMatch(/\.(mp4|webm)$/);
  expect((await readFile((await video.path())!)).byteLength).toBeGreaterThan(300);
  const preview = page.getByRole("dialog", { name: "视频已生成" });
  await expect(preview.locator("video")).toBeVisible();
  await expect(preview.locator("code")).toHaveText(video.suggestedFilename());
  const amplitudes = await preview.locator("video").evaluate(async (element: HTMLVideoElement) => {
    const bytes = await (await fetch(element.src)).arrayBuffer();
    const decoded = await new OfflineAudioContext(1, 1, 48_000).decodeAudioData(bytes);
    const samples = decoded.getChannelData(0).slice(decoded.sampleRate / 4, decoded.sampleRate * 0.65);
    return [331, 607, 929].map((frequency) => {
      let real = 0;
      let imaginary = 0;
      for (let i = 0; i < samples.length; i += 1) {
        const angle = (2 * Math.PI * frequency * i) / decoded.sampleRate;
        real += samples[i] * Math.cos(angle);
        imaginary += samples[i] * Math.sin(angle);
      }
      return (2 * Math.hypot(real, imaginary)) / samples.length;
    });
  });
  amplitudes.forEach((amplitude) => expect(amplitude).toBeGreaterThan(0.02));
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.systemAudioRequested)).toBe(false);
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.captureTrack.readyState)).toBe("ended");
  expect(await page.evaluate(() => (window as any).REPLAY_CUJ.mixedTracks[1].readyState)).toBe("ended");
  await expect(page.locator('.chat-stage[data-replay-recording="true"]')).toHaveCount(0);
});

for (const stop of ["exiting replay", "ending screen sharing"]) {
  test(`saves the recorded portion when ${stop}`, async ({ page }) => {
    await mockWindowCapture(page);
    await page.locator(".dialog-toolbar-layer").hover();
    await page.getByRole("button", { name: "打开历史", exact: true }).click();
    const history = page.getByRole("dialog", { name: "对话历史记录" });
    await history.getByRole("button", { name: "回放/分享", exact: true }).click();
    await history.getByRole("searchbox").fill("start mark");
    await history.getByRole("checkbox", { name: "选择第 18 条消息" }).click();
    await history.getByRole("searchbox").fill("end mark");
    await history.getByRole("button", { name: "选到此处", exact: true }).click();
    await history.getByRole("button", { name: "生成视频", exact: true }).click();
    await expect(history.getByText("第 18–22 条，共 5 条")).toBeVisible();
    await history.getByRole("button", { name: "选择录制窗口", exact: true }).click();
    await expect(page.locator('.chat-stage[data-replay-recording="true"]')).toBeVisible();
    await expect.poll(() => page.evaluate(() => (window as any).REPLAY_CUJ.captureFrames)).toBeGreaterThan(18);

    const pending = page.waitForEvent("download");
    if (stop === "exiting replay") {
      await page.keyboard.press("Escape");
    } else {
      await page.evaluate(() => {
        const track: MediaStreamTrack = (window as any).REPLAY_CUJ.captureTrack;
        track.stop();
        track.dispatchEvent(new Event("ended"));
      });
    }

    const video = await pending;
    expect(video.suggestedFilename()).toMatch(/\.(mp4|webm)$/);
    const preview = page.getByRole("dialog", { name: "视频已生成" });
    await expect(preview.locator("code")).toHaveText(video.suggestedFilename());
    await expect
      .poll(() => preview.locator("video").evaluate((element: HTMLVideoElement) => element.videoWidth))
      .toBeGreaterThan(0);
    expect(await page.evaluate(() => (window as any).REPLAY_CUJ.mixedTracks[0].readyState)).toBe("ended");
    await expect(page.locator('.chat-stage[data-replay-recording="true"]')).toHaveCount(0);
    if (stop === "exiting replay") await expect(page.locator(".chat-replay-player")).toHaveCount(0);
  });
}
