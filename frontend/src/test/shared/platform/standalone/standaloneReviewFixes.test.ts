import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tauriMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: tauriMocks.invoke,
}));

import { chatStageReducer, emptyChatState } from "../../../../features/chat-stage/chatState";
import { hasTauriNativeHttp, resetTauriNativeHttpStateForTests } from "../../../../shared/desktop/desktopApi";
import { getPlatform, resetPlatformForModeSwitch } from "../../../../shared/platform/platform";
import { saveRemoteBridgeConfig } from "../../../../shared/platform/runtimeTarget";
import { sampleConfig } from "../../../../shared/platform/sampleData";
import type { Character } from "../../../../shared/platform/slices/characterTypes";
import type { ChatStageEvent } from "../../../../shared/platform/slices/chatTypes";
import { createStandalonePlatform, syncCharacterFromRemotePc } from "../../../../shared/platform/standalone";
import type { StandaloneLlmAdapter } from "../../../../shared/platform/standalone/ai/adapters/types";
import { browserSpeechTtsAdapter } from "../../../../shared/platform/standalone/ai/adapters/tts/browserSpeechAdapter";
import { autoCompactIfNeeded } from "../../../../shared/platform/standalone/ai/compactManager";
import { bytesToBase64, standaloneHttpRequest } from "../../../../shared/platform/standalone/ai/httpClient";
import { StandaloneChatTurnDriver } from "../../../../shared/platform/standalone/ai/standaloneChatTurn";
import { exportCharPackage } from "../../../../shared/platform/standalone/packages/charPackageCodec";
import { unzipEntries, zipEntries } from "../../../../shared/platform/standalone/packages/zipCodec";
import {
  clearAllStandaloneStorage,
  idbGetAll,
  idbPut,
} from "../../../../shared/platform/standalone/storage/indexedDbStore";
import { StandaloneSessionStore, type TurnNode } from "../../../../shared/platform/standalone/storage/sessionStore";
import {
  getVfsBlob,
  putVfsBlob,
  resetVfsRegistryForTests,
  stageUploadedFiles,
} from "../../../../shared/platform/standalone/storage/vfsBlobRegistry";

const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]);

describe("standalone PR #435 review fixes", () => {
  const originalFetch = globalThis.fetch;
  const originalSpeech = (window as Window & { speechSynthesis?: unknown }).speechSynthesis;
  const originalUtterance = (globalThis as { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance;

  beforeEach(async () => {
    tauriMocks.invoke.mockReset();
    resetTauriNativeHttpStateForTests();
    resetVfsRegistryForTests();
    await clearAllStandaloneStorage();
    window.localStorage?.clear();
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    globalThis.fetch = originalFetch;
    if (originalSpeech === undefined) {
      Reflect.deleteProperty(window, "speechSynthesis");
    } else {
      Object.defineProperty(window, "speechSynthesis", {
        configurable: true,
        writable: true,
        value: originalSpeech,
      });
    }
    if (originalUtterance === undefined) {
      Reflect.deleteProperty(globalThis, "SpeechSynthesisUtterance");
    } else {
      (globalThis as { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance = originalUtterance;
    }
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
    resetTauriNativeHttpStateForTests();
    resetPlatformForModeSwitch();
  });

  it("C#2: falls back to fetch when standalone_http_request is not registered in Tauri", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    tauriMocks.invoke.mockRejectedValueOnce(new Error("Command standalone_http_request not found"));
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const first = await standaloneHttpRequest({ url: "https://example.com/v1/models", method: "GET" });
    expect(first.ok).toBe(true);
    expect(first.json()).toEqual({ ok: true });
    expect(tauriMocks.invoke).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const second = await standaloneHttpRequest({ url: "https://example.com/v1/models", method: "GET" });
    expect(second.ok).toBe(true);
    // Remembers unsupported native command without retrying invoke repeatedly
    expect(tauriMocks.invoke).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("C#3: uses a single monotonic sequence clock across standalone snapshots, turn events, clear-history and revert", async () => {
    const platform = createStandalonePlatform({ target: "toy" });
    const events: ChatStageEvent[] = [];
    platform.chat.subscribeEvents((event) => events.push(event));

    const launched = await platform.chat.launch({
      templateId: "tpl-seq",
      characters: ["星奈"],
      backgroundName: "星海观测台",
      historyPath: "./data/history/seq.json",
    });
    expect(launched.eventSeq).toBeGreaterThan(0);
    expect(launched.eventSeq!).toBeLessThan(100_000);

    let stageState = chatStageReducer(emptyChatState, {
      type: "hydrate",
      snapshot: launched,
      receivedAt: 0,
    });

    await platform.chat.command({ type: "send-message", payload: "第一句提问" });
    await vi.waitFor(() => expect(events.some((e) => e.type === "reply.finished")).toBe(true));

    await platform.chat.command({ type: "revert-history", payload: { userIndex: 0 } });
    await platform.chat.command({ type: "clear-history" });

    expect(events.length).toBeGreaterThan(3);
    for (let i = 0; i < events.length; i += 1) {
      expect(events[i].seq).toBeLessThan(1_000_000);
      if (i > 0) {
        expect(events[i].seq).toBeGreaterThan(events[i - 1].seq);
      }
      stageState = chatStageReducer(stageState, {
        type: "event",
        event: events[i],
        receivedAt: i,
      });
    }

    expect(stageState.eventSeq).toBe(events[events.length - 1].seq);
    expect(stageState.historyEntries?.length ?? 0).toBeGreaterThan(0);
  });

  it("C#4: resetHistory creates a fresh session & historyPath while preserving previous conversations", async () => {
    const platform = createStandalonePlatform({ target: "web" });
    const first = await platform.chat.launch({
      templateId: "tpl-c4",
      characters: ["星奈"],
      backgroundName: "星海观测台",
      historyPath: "./data/history/c4.json",
      conversationTitle: "第一段旅程",
    });
    await platform.chat.command({ type: "send-message", payload: "只属于第一段的记忆词" });
    await vi.waitFor(async () => {
      const hist = await platform.chat.getHistory();
      expect(hist.some((item) => item.text.includes("只属于第一段的记忆词"))).toBe(true);
    });

    const restarted = await platform.chat.launch({
      templateId: "tpl-c4",
      characters: ["星奈"],
      backgroundName: "星海观测台",
      historyPath: "./data/history/c4.json",
      resetHistory: true,
      conversationTitle: "重新开启",
    });

    expect(restarted.sessionId).not.toBe(first.sessionId);
    expect(restarted.historyPath).not.toBe(first.historyPath);

    const newHistory = await platform.chat.getHistory();
    expect(newHistory.some((item) => item.text.includes("只属于第一段的记忆词"))).toBe(false);
    expect(newHistory.length).toBeGreaterThan(0); // Freshly seeded prologue

    const conversations = await platform.chat.listConversations();
    expect(conversations).toHaveLength(2);
    expect(conversations.some((c) => c.sessionId === first.sessionId)).toBe(true);
    expect(conversations.some((c) => c.sessionId === restarted.sessionId)).toBe(true);
  });

  it("C#5: uploadSprites relocates staged VFS uploads into character VFS storage and resolves usable URLs", async () => {
    const platform = createStandalonePlatform({ target: "web" });
    await platform.characters.list();

    const staged = await stageUploadedFiles([new File([PNG_BYTES], "custom_wink.png", { type: "image/png" })]);
    expect(staged[0]).toMatch(/^vfs:\/\/uploads\//);

    const updated = await platform.characters.uploadSprites({
      name: "星奈",
      paths: staged,
      emotionTags: "",
    });
    const lastSprite = updated.sprites[updated.sprites.length - 1];
    expect(lastSprite.path).toMatch(/^vfs:\/\/characters\/starter_hoshina\/sprites\/custom_wink\.png$/);
    expect(getVfsBlob(staged[0])).toBeUndefined();
    expect(getVfsBlob(lastSprite.path)).toBeDefined();
    expect(platform.files.fileUrl(lastSprite.path)).toMatch(/^blob:/);

    const reloadedPlatform = createStandalonePlatform({ target: "web" });
    const reloadedChars = await reloadedPlatform.characters.list();
    const reloadedChar = reloadedChars.find((c) => c.name === "星奈")!;
    expect(reloadedChar.sprites.some((sp) => sp.path === lastSprite.path)).toBe(true);
  });

  it("C#6: persists canonical vfs:// stageSnapshot references and rehydrates fresh blob URLs on reload", async () => {
    await putVfsBlob("vfs://characters/imported_c6/sprites/happy.png", PNG_BYTES, { mimeType: "image/png" });
    await putVfsBlob("vfs://backgrounds/obs_c6/night.png", PNG_BYTES, { mimeType: "image/png" });

    const platform1 = createStandalonePlatform({ target: "web" });
    await platform1.characters.save({
      name: "VFS测试角色",
      color: "#7dd3fc",
      sprite_prefix: "imported_c6",
      sprites: [{ path: "vfs://characters/imported_c6/sprites/happy.png" }],
      sprite_scale: 1,
      emotion_tags: "立绘 1：开心\n",
      avatar_type: "static",
      avatars: {},
      character_brief: "test",
      character_setting: "test",
      relation_graph: { nodes: [{ key: "VFS测试角色" }], edges: [] },
      speech_speed: 1,
      speech_volume: 1,
      pronunciation_map: {},
    });
    // Set actual VFS sprite on the newly saved character via uploadSprites (since base.save starts sprites empty on create)
    const stagedSprite = await putVfsBlob("vfs://uploads/1700000000000-0-happy.png", PNG_BYTES, {
      mimeType: "image/png",
    });
    expect(stagedSprite).toMatch(/^blob:/);
    await platform1.characters.uploadSprites({
      name: "VFS测试角色",
      paths: ["vfs://uploads/1700000000000-0-happy.png"],
      emotionTags: "",
    });
    await platform1.backgrounds.save({
      name: "VFS夜景",
      sprite_prefix: "obs_c6",
      sprites: [],
      bg_tags: "",
      bgm_list: [],
      bgm_tags: "",
    });
    await platform1.backgrounds.uploadImages({
      name: "VFS夜景",
      paths: ["vfs://backgrounds/obs_c6/night.png"],
      bgTags: "",
    });

    const snap = await platform1.chat.launch({
      templateId: "tpl-c6",
      characters: ["VFS测试角色"],
      backgroundName: "VFS夜景",
      historyPath: "./data/history/c6.json",
    });
    const oldSpriteBlobUrl = snap.sprites[0].path;
    expect(oldSpriteBlobUrl).toMatch(/^blob:/);

    await platform1.chat.command({ type: "send-message", payload: "保存当前舞台快照" });
    await vi.waitFor(async () => {
      const nodes = await idbGetAll<TurnNode>("turn_nodes");
      expect(nodes.some((n) => n.role === "user" && n.plainText === "保存当前舞台快照")).toBe(true);
    });

    const rawNodes = await idbGetAll<TurnNode>("turn_nodes");
    const userNode = rawNodes.find((n) => n.role === "user" && n.plainText === "保存当前舞台快照")!;
    expect(userNode.stageSnapshot?.backgroundPath).toBe("vfs://backgrounds/obs_c6/night.png");
    expect(userNode.stageSnapshot?.sprites[0]?.path).toBe("vfs://characters/imported_c6/sprites/happy.png");

    // Simulate document reload: old blob: URLs vanish and VFS re-hydrates with new object URLs
    resetVfsRegistryForTests();
    const platform2 = createStandalonePlatform({ target: "web" });
    const resumed = await platform2.chat.resumeLast();
    expect(resumed.sprites[0].path).toMatch(/^blob:/);
    expect(resumed.sprites[0].path).not.toBe(oldSpriteBlobUrl);
    expect(resumed.backgroundPath).toMatch(/^blob:/);
  });

  it("C#7: syncCharacterFromRemotePc updates the active standalone platform in memory immediately", async () => {
    await putVfsBlob("vfs://characters/pc_char/sprites/base.png", PNG_BYTES, { mimeType: "image/png" });
    const remoteChar: Character = {
      name: "电脑同步角色",
      color: "#60a5fa",
      sprite_prefix: "pc_char",
      sprites: [{ path: "vfs://characters/pc_char/sprites/base.png" }],
      sprite_scale: 1,
      emotion_tags: "立绘 1：微笑\n",
      avatar_type: "static",
      avatars: {},
      character_brief: "来自电脑端",
      character_setting: "pc sync test",
      relation_graph: { nodes: [{ key: "电脑同步角色" }], edges: [] },
      speech_speed: 1,
      speech_volume: 1,
      pronunciation_map: {},
    };
    const { blob } = await exportCharPackage(remoteChar, { triggerDownload: false });
    const charBytes = await new Promise<Uint8Array>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
      reader.onerror = () => reject(reader.error ?? new Error("Failed to read Blob"));
      reader.readAsArrayBuffer(blob);
    });

    vi.stubEnv("VITE_SHINSEKAI_TARGET", "mobile");
    saveRemoteBridgeConfig({ mode: "standalone", url: "" });
    resetPlatformForModeSwitch();

    const activeBefore = await getPlatform().characters.list();
    expect(activeBefore.some((c) => c.name === "电脑同步角色")).toBe(false);

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/characters/export")) {
        return new Response(JSON.stringify({ path: "exports/pc_char.char" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      const copy = new Uint8Array(charBytes.byteLength);
      copy.set(charBytes);
      return new Response(copy.buffer, { status: 200 });
    }) as typeof fetch;

    const synced = await syncCharacterFromRemotePc({
      bridgeUrl: "http://127.0.0.1:8787",
      characterName: "电脑同步角色",
    });
    expect(synced[0]?.name).toBe("电脑同步角色");

    const activeAfter = await getPlatform().characters.list();
    expect(activeAfter.some((c) => c.name === "电脑同步角色")).toBe(true);
  });

  it("C#8: persists workspace writes on effects, backgrounds.import, and template sessions across reloads", async () => {
    const p1 = createStandalonePlatform({ target: "web" });
    await p1.effects.save({
      name: "星尘雨",
      color: "#a78bfa",
      prompt_text: "轻柔闪烁",
      audio_list: [],
      audio_tags: "",
      image_list: [],
      image_tags: "",
      image_audio_list: [],
    });
    await p1.backgrounds.import(["vfs://uploads/imported_hall.bg"]);
    await p1.templates.saveSession({
      ...(await p1.templates.getSession())!,
      scenario: "持久化的模板场景",
    });

    const p2 = createStandalonePlatform({ target: "web" });
    expect((await p2.effects.list()).some((e) => e.name === "星尘雨")).toBe(true);
    expect((await p2.backgrounds.list()).some((b) => b.name === "Imported Background 1")).toBe(true);
    expect((await p2.templates.getSession())?.scenario).toBe("持久化的模板场景");
  });

  it("C#9: prevents in-flight compaction from writing a stale checkpoint after rollback", async () => {
    const store = new StandaloneSessionStore();
    await store.hydrate();
    const session = await store.ensureSession({
      sessionId: "s-race",
      historyPath: "./data/history/s-race.json",
      title: "压缩竞态测试",
      payload: {
        templateId: "tpl",
        characters: ["星奈"],
        backgroundName: "观测台",
        historyPath: "./data/history/s-race.json",
      },
    });

    for (let i = 1; i <= 10; i += 1) {
      await store.appendTurn(session.sessionId, {
        role: i % 2 === 1 ? "user" : "assistant",
        speaker: i % 2 === 1 ? "" : "星奈",
        plainText: `第${i}轮内容：` + "星海观测站长文本回忆".repeat(14),
      });
    }

    let resolveSummary!: (value: { content: string; usageTokens: number }) => void;
    let capturedSignal: AbortSignal | undefined;
    const deferredAdapter: StandaloneLlmAdapter = {
      id: "deferred",
      label: "deferred",
      browserCors: "supported",
      supportsProvider: () => true,
      complete: vi.fn((req) => {
        capturedSignal = req.signal;
        return new Promise<{ content: string; usageTokens: number }>((resolve) => {
          resolveSummary = resolve;
        });
      }),
      fetchModels: async () => [],
      testConnection: async () => ({ message: "ok" }),
    };

    const compactPromise = autoCompactIfNeeded({
      sessionId: session.sessionId,
      systemPrompt: "SYS",
      sessionStore: store,
      apiConfig: {
        ...sampleConfig.api_config,
        llm_provider: "Deepseek",
        max_context_tokens: 2048,
        compact_threshold: 0.25,
        compact_target_ratio: 0.25,
        history_recent_messages: 4,
      },
      llmAdapter: deferredAdapter,
      httpClient: standaloneHttpRequest,
      apiKey: "sk-test",
      baseUrl: "https://example.com/v1",
      model: "deepseek-chat",
    });

    // Wait until LLM complete is in flight, then roll back before LLM settles (even without signal abort!)
    await vi.waitFor(() => expect(deferredAdapter.complete).toHaveBeenCalledOnce());
    await store.truncateAfter(session.sessionId, 2);

    resolveSummary({ content: "被回滚的过期剧情摘要", usageTokens: 100 });
    const result = await compactPromise;

    expect(result.compacted).toBe(false);
    expect(store.listCheckpoints(session.sessionId)).toHaveLength(0);
    const active = store.buildActiveLlmMessages(session.sessionId, "SYS");
    expect(active.messages.every((m) => !m.content.includes("被回滚的过期剧情摘要"))).toBe(true);
    expect(capturedSignal).toBeUndefined();
  });

  it("C#10: enforces ZIP archive limits on entry count, archive bytes, ratio and streaming inflation", async () => {
    const smallArchive = await zipEntries({
      "a.txt": new TextEncoder().encode("hello"),
      "b.txt": new TextEncoder().encode("world"),
      "c.txt": new TextEncoder().encode("!"),
    });
    await expect(unzipEntries(smallArchive, { maxEntries: 2 })).rejects.toThrow(/entry count/i);
    await expect(unzipEntries(smallArchive, { maxArchiveBytes: 32 })).rejects.toThrow(/maximum size/i);

    if (typeof CompressionStream !== "undefined" && typeof DecompressionStream !== "undefined") {
      const repetitive = new Uint8Array(90_000).fill(65);
      const bombZip = await zipEntries({ "bomb.txt": repetitive });

      // Compression ratio check (>20x)
      await expect(
        unzipEntries(bombZip, {
          maxEntryBytes: 200_000,
          maxTotalUncompressedBytes: 200_000,
          maxCompressionRatio: 10,
        }),
      ).rejects.toThrow(/compression ratio|maximum uncompressed size/i);

      // Spoof CD uncompressedSize to 64 bytes to verify streaming inflate aborts mid-stream at maxEntryBytes
      const view = new DataView(bombZip.buffer, bombZip.byteOffset, bombZip.byteLength);
      const eocdOffset = bombZip.byteLength - 22;
      const cdOffset = view.getUint32(eocdOffset + 16, true);
      view.setUint32(cdOffset + 24, 64, true);

      await expect(
        unzipEntries(bombZip, {
          maxEntryBytes: 1024,
          maxTotalUncompressedBytes: 2048,
          maxCompressionRatio: 10_000,
        }),
      ).rejects.toThrow(/maximum uncompressed size/i);
    }
  });

  it("C#12: cancels browser speechSynthesis on abort, skip, and turn cancellation", async () => {
    const cancelSpy = vi.fn();
    const speakSpy = vi.fn();
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      writable: true,
      value: {
        cancel: cancelSpy,
        speak: speakSpy,
      } as unknown as SpeechSynthesis,
    });
    class MockUtterance {
      rate = 1;
      pitch = 1;
      volume = 1;
      lang = "";
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    }
    (globalThis as { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance =
      MockUtterance as unknown as typeof SpeechSynthesisUtterance;

    const controller = new AbortController();
    await browserSpeechTtsAdapter.synthesize(
      {
        text: "测试语音播报",
        characterName: "星奈",
        apiConfig: sampleConfig.api_config,
        signal: controller.signal,
      },
      {},
      standaloneHttpRequest,
    );
    expect(speakSpy).toHaveBeenCalledOnce();
    const callsBeforeAbort = cancelSpy.mock.calls.length;
    controller.abort();
    expect(cancelSpy).toHaveBeenCalledTimes(callsBeforeAbort + 1);

    const driver = new StandaloneChatTurnDriver({
      getApiConfig: () => sampleConfig.api_config,
      getCharacters: () => sampleConfig.characters,
      getChat: () => ({
        status: "idle",
        dialogText: "",
        inputDraft: "",
        options: [],
        sprites: [],
        stats: [],
      }),
      setChat: () => {},
      emitChat: () => {},
      emitStageEvent: () => {},
      sessionStore: new StandaloneSessionStore(),
      httpClient: standaloneHttpRequest,
      resolveFileUrl: (p) => p,
    });
    driver.cancelActiveTurn();
    driver.handleSkipSpeech();
    expect(cancelSpy.mock.calls.length).toBeGreaterThanOrEqual(callsBeforeAbort + 3);
  });

  it("C#13 & C#14: uses CSPRNG for session IDs and ignores orphan future checkpoints beyond surviving turns", async () => {
    const mathRandomSpy = vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Math.random must not be used for session ID generation");
    });

    const store = new StandaloneSessionStore();
    await store.hydrate();
    const session = await store.ensureSession({
      historyPath: "./data/history/c13.json",
      title: "原子与随机测试",
      payload: {
        templateId: "tpl",
        characters: ["星奈"],
        backgroundName: "观测台",
        historyPath: "./data/history/c13.json",
      },
    });
    expect(session.sessionId).toMatch(/^session-\d+-[0-9a-f]{12}$/);
    expect(mathRandomSpy).not.toHaveBeenCalled();

    await store.appendTurn(session.sessionId, { role: "user", plainText: "U1" });
    await store.appendTurn(session.sessionId, { role: "assistant", speaker: "星奈", plainText: "A1" });

    // Simulate an orphan future checkpoint persisted beyond current surviving turns
    await idbPut("compact_checkpoints", {
      checkpointKey: `${session.sessionId}::main::00000009`,
      checkpointId: "orphan-9",
      sessionId: session.sessionId,
      branchId: "main",
      upToSeq: 9,
      rollingSummary: "不应该被使用的未来摘要",
      createdAtMs: Date.now(),
    });

    const rehydrated = new StandaloneSessionStore();
    await rehydrated.hydrate();
    expect(rehydrated.getLatestCheckpoint(session.sessionId)).toBeNull();
    const active = rehydrated.buildActiveLlmMessages(session.sessionId, "SYS");
    expect(active.messages.some((m) => m.content.includes("不应该被使用的未来摘要"))).toBe(false);
  });

  it("propagates AbortSignal to standalone_http_cancel in Tauri native HTTP without disabling native transport", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    let capturedRequestId = "";
    let rejectInFlight!: (reason?: unknown) => void;
    const cancelCalls: string[] = [];

    tauriMocks.invoke.mockImplementation(async (cmd: string, rawArgs?: Record<string, unknown>) => {
      if (cmd === "standalone_http_request") {
        const req = (rawArgs?.request ?? {}) as { requestId?: string };
        capturedRequestId = req.requestId ?? "";
        return await new Promise((_resolve, reject) => {
          rejectInFlight = reject;
        });
      }
      if (cmd === "standalone_http_cancel") {
        const requestId = String(rawArgs?.requestId ?? "");
        cancelCalls.push(requestId);
        rejectInFlight?.(new Error("HTTP_ABORTED: The operation was aborted."));
        return true;
      }
      throw new Error(`Unexpected invoke: ${cmd}`);
    });

    const controller = new AbortController();
    const reqPromise = standaloneHttpRequest({
      url: "https://api.openai.com/v1/chat/completions",
      method: "POST",
      body: "{}",
      signal: controller.signal,
    });

    await vi.waitFor(() => expect(capturedRequestId).toMatch(/^tauri-http-/));
    controller.abort();

    await expect(reqPromise).rejects.toMatchObject({ name: "AbortError" });
    expect(cancelCalls).toEqual([capturedRequestId]);
    expect(hasTauriNativeHttp()).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("cancels prior in-flight Tauri native LLM request when StandaloneChatTurnDriver starts a new turn / reroll", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    const issuedRequestIds: string[] = [];
    const cancelledRequestIds: string[] = [];
    const pendingById = new Map<string, { reject: (err: unknown) => void }>();

    const replyBodyBase64 = bytesToBase64(
      new TextEncoder().encode(
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  dialog: [
                    { character_name: sampleConfig.characters[0].name, sprite: "01", speech: "这是重掷后的最新回复。" },
                  ],
                }),
              },
            },
          ],
        }),
      ),
    );

    tauriMocks.invoke.mockImplementation(async (cmd: string, rawArgs?: Record<string, unknown>) => {
      if (cmd === "standalone_http_request") {
        const req = (rawArgs?.request ?? {}) as { requestId?: string };
        const reqId = req.requestId ?? "";
        issuedRequestIds.push(reqId);
        if (issuedRequestIds.length === 1) {
          return await new Promise((_resolve, reject) => {
            pendingById.set(reqId, { reject });
          });
        }
        return {
          status: 200,
          headers: { "content-type": "application/json" },
          bodyBase64: replyBodyBase64,
        };
      }
      if (cmd === "standalone_http_cancel") {
        const reqId = String(rawArgs?.requestId ?? "");
        cancelledRequestIds.push(reqId);
        pendingById.get(reqId)?.reject(new Error("HTTP_ABORTED: The operation was aborted."));
        pendingById.delete(reqId);
        return true;
      }
      throw new Error(`Unexpected invoke: ${cmd}`);
    });

    const store = new StandaloneSessionStore();
    await store.hydrate();
    const primaryChar = sampleConfig.characters[0];
    const session = await store.ensureSession({
      historyPath: "./data/history/cancel-reroll.json",
      title: "原生请求取消测试",
      payload: {
        templateId: "tpl-cancel",
        characters: [primaryChar.name],
        backgroundName: sampleConfig.background_list[0]?.name ?? "",
        historyPath: "./data/history/cancel-reroll.json",
      },
    });

    let chatSnapshot = {
      status: "idle" as const,
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      stats: [],
    };
    const driver = new StandaloneChatTurnDriver({
      getApiConfig: () => ({
        ...sampleConfig.api_config,
        llm_provider: "ChatGPT",
        llm_api_key: { ChatGPT: "sk-test-token" },
        llm_base_urls: { ChatGPT: "https://api.openai.com/v1" },
        llm_model: { ChatGPT: "gpt-4o-mini" },
        tts_provider: "none",
      }),
      getCharacters: () => [primaryChar],
      getChat: () => chatSnapshot,
      setChat: (next) => {
        chatSnapshot = next as typeof chatSnapshot;
      },
      emitChat: () => {},
      emitStageEvent: () => {},
      sessionStore: store,
      httpClient: standaloneHttpRequest,
      resolveFileUrl: (p) => p,
    });

    const firstTurn = driver.runTurn({ session, userText: "第一轮提问" });
    await vi.waitFor(() => expect(issuedRequestIds).toHaveLength(1));

    const secondTurn = driver.runTurn({ session, userText: "第二轮重掷" });
    await Promise.all([firstTurn, secondTurn]);

    expect(issuedRequestIds).toHaveLength(2);
    expect(cancelledRequestIds).toEqual([issuedRequestIds[0]]);
    expect(chatSnapshot.dialogText).toContain("这是重掷后的最新回复。");
  });
});
