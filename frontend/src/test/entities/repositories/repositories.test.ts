import { afterEach, describe, expect, it, vi } from "vitest";

import {
  sampleChatSnapshot,
  sampleChatTheme,
  sampleConfig,
  sampleLastLaunch,
  sampleMcpConfig,
  sampleTemplates,
} from "../../../shared/platform/sampleData";
import type { ShinsekaiPlatform } from "../../../shared/platform/types";

async function loadRepositories(platform: Partial<ShinsekaiPlatform>) {
  vi.resetModules();
  window.__SHINSEKAI_IPC__ = platform as ShinsekaiPlatform;
  return {
    background: await import("../../../entities/background/repository"),
    character: await import("../../../entities/character/repository"),
    chat: await import("../../../entities/chat/repository"),
    config: await import("../../../entities/config/repository"),
    effect: await import("../../../entities/effect/repository"),
    files: await import("../../../entities/files/repository"),
    logs: await import("../../../entities/logs/repository"),
    modelAssets: await import("../../../entities/model-assets/repository"),
    musicCover: await import("../../../entities/music-cover/repository"),
    plugin: await import("../../../entities/plugin/repository"),
    template: await import("../../../entities/template/repository"),
    tools: await import("../../../entities/tools/repository"),
  };
}

describe("entity repositories", () => {
  afterEach(() => {
    delete window.__SHINSEKAI_IPC__;
    vi.restoreAllMocks();
  });

  it("delegates config, files, and template operations to the active platform", async () => {
    const apiConfig = sampleConfig.api_config;
    const systemConfig = sampleConfig.system_config;
    const template = sampleTemplates[0];
    const taskOptions = { onTaskUpdate: vi.fn() };
    const platform = {
      config: {
        cancelTtsBundleDownload: vi.fn().mockResolvedValue({ id: "task-1", status: "cancelled" }),
        detectNetworkProxy: vi.fn().mockResolvedValue({
          http_proxy_url: "http://127.0.0.1:7890",
          https_proxy_url: "http://127.0.0.1:7890",
          socks5_proxy_url: "",
          source: "environment",
        }),
        downloadTtsBundle: vi.fn().mockResolvedValue({ path: "/runtime", provider: "genie-tts" }),
        fetchLlmModels: vi.fn().mockResolvedValue([{ id: "deepseek-chat", tags: ["chat"] }]),
        testLlmConnection: vi.fn().mockResolvedValue({ message: "ok" }),
        get: vi.fn().mockResolvedValue(sampleConfig),
        getMemoryStatus: vi.fn().mockResolvedValue({ status: "ready" }),
        getTtsBundleRecommendation: vi.fn().mockResolvedValue({ gpus: [], kind: "genie", platform: "linux" }),
        saveApi: vi.fn().mockResolvedValue(apiConfig),
        saveSystem: vi.fn().mockResolvedValue(systemConfig),
      },
      files: {
        browse: vi.fn().mockResolvedValue({ cwd: "/tmp", entries: [], roots: [] }),
        fileUrl: vi.fn((path: string) => `file://${path}`),
        thumbnailBatch: vi.fn((paths: string[], options?: { size?: number }) =>
          Promise.resolve(Object.fromEntries(paths.map((path) => [path, `batch://${options?.size ?? 0}/${path}`]))),
        ),
        thumbnailUrl: vi.fn((path: string, options?: { size?: number }) => `thumb://${options?.size ?? 0}/${path}`),
        openExternal: vi.fn().mockResolvedValue(undefined),
      },
      templates: {
        generate: vi.fn().mockResolvedValue(template),
        getSession: vi.fn().mockResolvedValue(null),
        list: vi.fn().mockResolvedValue(sampleTemplates),
        save: vi.fn().mockResolvedValue(template),
        saveSession: vi.fn().mockResolvedValue({ characterNames: ["Nanami"], templateId: "default" }),
      },
    };
    const { config, files, template: templates } = await loadRepositories(platform);

    await expect(config.getAppConfig()).resolves.toBe(sampleConfig);
    await config.fetchLlmModels({ apiKey: "key", baseUrl: "https://api.example.test", provider: "Deepseek" });
    await config.testLlmConnection({
      apiKey: "key",
      baseUrl: "https://api.example.test",
      model: "deepseek-chat",
      provider: "Deepseek",
    });
    await config.downloadTtsBundle({ kind: "genie" }, taskOptions);
    await config.cancelTtsBundleDownload("task-1");
    await config.detectNetworkProxy();
    await config.getMemoryStatus();
    await config.getTtsBundleRecommendation();
    await config.saveApiConfig(apiConfig);
    await config.saveSystemConfig(systemConfig);
    await files.browseFiles({ path: "/tmp", showHidden: true });
    expect(files.fileUrl("/tmp/a.png")).toBe("file:///tmp/a.png");
    expect(files.fileThumbnailUrl("/tmp/a.png", 160)).toBe("thumb://160//tmp/a.png");
    await expect(files.fileThumbnailBatch(["/tmp/a.png", "/tmp/a.png"], 160)).resolves.toEqual({
      "/tmp/a.png": "batch://160//tmp/a.png",
    });
    await files.openExternal("https://example.test");
    await templates.listTemplates();
    await templates.saveTemplate(template);
    await templates.generateTemplate({
      backgroundName: "默认房间",
      characters: ["Nanami"],
      name: "新模板",
      scenario: "scene",
    });
    await templates.getTemplateSession();
    await templates.saveTemplateSession({
      background: "默认房间",
      effectNames: [],
      filenameStub: "default",
      historyPath: "",
      initSpritePath: "",
      maxDialogItems: 0,
      maxSpeechChars: 0,
      roomId: "",
      scenario: "scene",
      selectedCharacters: ["Nanami"],
      system: "sys",
      templateFileDropdown: "default",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: true,
      voiceLanguage: "ja",
    });

    expect(platform.config.fetchLlmModels).toHaveBeenCalledWith({
      apiKey: "key",
      baseUrl: "https://api.example.test",
      provider: "Deepseek",
    });
    expect(platform.config.testLlmConnection).toHaveBeenCalledWith({
      apiKey: "key",
      baseUrl: "https://api.example.test",
      model: "deepseek-chat",
      provider: "Deepseek",
    });
    expect(platform.config.downloadTtsBundle).toHaveBeenCalledWith({ kind: "genie" }, taskOptions);
    expect(platform.config.cancelTtsBundleDownload).toHaveBeenCalledWith("task-1");
    expect(platform.config.detectNetworkProxy).toHaveBeenCalledWith();
    expect(platform.files.browse).toHaveBeenCalledWith({ path: "/tmp", showHidden: true });
    expect(platform.files.thumbnailBatch).toHaveBeenCalledWith(["/tmp/a.png"], { delivery: "url", size: 160 });
    expect(platform.files.openExternal).toHaveBeenCalledWith("https://example.test");
    expect(platform.templates.generate).toHaveBeenCalledWith({
      backgroundName: "默认房间",
      characters: ["Nanami"],
      name: "新模板",
      scenario: "scene",
    });
  });

  it("delegates generic model asset checks and downloads", async () => {
    const ref = { assetId: "asr.faster-whisper", variant: "small" };
    const status = {
      ...ref,
      cached: false,
      downloadable: true,
      repoId: "Systran/faster-whisper-small",
      source: "huggingface" as const,
      title: "Whisper ASR",
    };
    const result = { ...status, cached: true, downloaded: true, path: "/cache/small" };
    const options = { onTaskUpdate: vi.fn() };
    const platform = {
      modelAssets: {
        download: vi.fn().mockResolvedValue(result),
        status: vi.fn().mockResolvedValue(status),
      },
    };
    const { modelAssets } = await loadRepositories(platform);

    await expect(modelAssets.getModelAssetStatus(ref)).resolves.toEqual(status);
    await expect(modelAssets.downloadModelAsset(ref, options)).resolves.toEqual(result);
    expect(platform.modelAssets.status).toHaveBeenCalledWith(ref);
    expect(platform.modelAssets.download).toHaveBeenCalledWith(ref, options);
  });

  it("chunks and caches thumbnail batch requests", async () => {
    const paths = Array.from({ length: 130 }, (_, index) => `/tmp/background-${index}.png`);
    const platform = {
      files: {
        browse: vi.fn().mockResolvedValue({ cwd: "/tmp", entries: [], roots: [] }),
        fileUrl: vi.fn((path: string) => `file://${path}`),
        thumbnailBatch: vi.fn((batch: string[], options?: { size?: number }) =>
          Promise.resolve(Object.fromEntries(batch.map((path) => [path, `batch://${options?.size ?? 0}/${path}`]))),
        ),
        thumbnailUrl: vi.fn((path: string, options?: { size?: number }) => `thumb://${options?.size ?? 0}/${path}`),
        openExternal: vi.fn().mockResolvedValue(undefined),
      },
    };
    const { files } = await loadRepositories(platform);

    const firstResult = await files.fileThumbnailBatch(paths, 160);
    const secondResult = await files.fileThumbnailBatch(paths, 160);

    expect(Object.keys(firstResult)).toHaveLength(130);
    expect(secondResult).toEqual(firstResult);
    expect(platform.files.thumbnailBatch).toHaveBeenCalledTimes(2);
    expect(platform.files.thumbnailBatch.mock.calls.map(([batch]) => batch.length)).toEqual([128, 2]);
  });

  it("reports thumbnail batch chunks as they resolve", async () => {
    const paths = ["/tmp/background-a.png", "/tmp/background-b.png"];
    const platform = {
      files: {
        browse: vi.fn().mockResolvedValue({ cwd: "/tmp", entries: [], roots: [] }),
        fileUrl: vi.fn((path: string) => `file://${path}`),
        thumbnailBatch: vi.fn((batch: string[], options?: { delivery?: "data" | "url"; size?: number }) =>
          Promise.resolve(
            Object.fromEntries(
              batch.map((path) => [path, `${options?.delivery ?? "url"}://${options?.size ?? 0}/${path}`]),
            ),
          ),
        ),
        thumbnailUrl: vi.fn((path: string, options?: { size?: number }) => `thumb://${options?.size ?? 0}/${path}`),
        openExternal: vi.fn().mockResolvedValue(undefined),
      },
    };
    const { files } = await loadRepositories(platform);
    const onBatch = vi.fn();

    const result = await files.fileThumbnailBatch(paths, 160, { batchSize: 1, delivery: "data", onBatch });

    expect(result).toEqual({
      "/tmp/background-a.png": "data://160//tmp/background-a.png",
      "/tmp/background-b.png": "data://160//tmp/background-b.png",
    });
    expect(onBatch).toHaveBeenCalledTimes(2);
    expect(onBatch).toHaveBeenNthCalledWith(1, { "/tmp/background-a.png": "data://160//tmp/background-a.png" });
    expect(onBatch).toHaveBeenNthCalledWith(2, { "/tmp/background-b.png": "data://160//tmp/background-b.png" });
    expect(platform.files.thumbnailBatch).toHaveBeenCalledWith(["/tmp/background-a.png"], {
      delivery: "data",
      size: 160,
    });
  });

  it("falls back per thumbnail batch chunk when the platform batch fails", async () => {
    const paths = Array.from({ length: 130 }, (_, index) => `/tmp/background-${index}.png`);
    const platform = {
      files: {
        browse: vi.fn().mockResolvedValue({ cwd: "/tmp", entries: [], roots: [] }),
        fileUrl: vi.fn((path: string) => `file://${path}`),
        thumbnailBatch: vi.fn((batch: string[], options?: { size?: number }) => {
          if (batch.length === 2) {
            return Promise.reject(new Error("batch failed"));
          }
          return Promise.resolve(
            Object.fromEntries(batch.map((path) => [path, `batch://${options?.size ?? 0}/${path}`])),
          );
        }),
        thumbnailUrl: vi.fn((path: string, options?: { size?: number }) => `thumb://${options?.size ?? 0}/${path}`),
        openExternal: vi.fn().mockResolvedValue(undefined),
      },
    };
    const { files } = await loadRepositories(platform);

    const result = await files.fileThumbnailBatch(paths, 160);

    expect(result["/tmp/background-0.png"]).toBe("batch://160//tmp/background-0.png");
    expect(result["/tmp/background-128.png"]).toBe("thumb://160//tmp/background-128.png");
    expect(result["/tmp/background-129.png"]).toBe("thumb://160//tmp/background-129.png");
  });

  it("delegates character and background asset operations", async () => {
    const character = sampleConfig.characters[0];
    const background = sampleConfig.background_list[0];
    const platform = {
      backgrounds: {
        autoLabelImages: vi.fn().mockResolvedValue({}),
        delete: vi.fn().mockResolvedValue(undefined),
        deleteAllBgm: vi.fn().mockResolvedValue(background),
        deleteAllImages: vi.fn().mockResolvedValue(background),
        deleteBgm: vi.fn().mockResolvedValue(background),
        deleteImage: vi.fn().mockResolvedValue(background),
        export: vi.fn().mockResolvedValue("/tmp/room.zip"),
        import: vi.fn().mockResolvedValue([background]),
        list: vi.fn().mockResolvedValue([background]),
        save: vi.fn().mockResolvedValue(background),
        saveBgmTags: vi.fn().mockResolvedValue(background),
        saveImageTags: vi.fn().mockResolvedValue(background),
        translateFields: vi.fn().mockResolvedValue({ bgTags: "tag", bgmTags: "music", name: "Room" }),
        uploadBgm: vi.fn().mockResolvedValue(background),
        uploadImages: vi.fn().mockResolvedValue(background),
      },
      characters: {
        autoLabelSprites: vi.fn().mockResolvedValue({}),
        delete: vi.fn().mockResolvedValue(undefined),
        deleteAllSprites: vi.fn().mockResolvedValue(character),
        deleteMemory: vi.fn().mockResolvedValue({ agentId: "Nanami", count: 0, memories: [] }),
        deleteSprite: vi.fn().mockResolvedValue(character),
        deleteSpriteVoice: vi.fn().mockResolvedValue(character),
        export: vi.fn().mockResolvedValue("/tmp/nanami.zip"),
        generateSetting: vi.fn().mockResolvedValue({ characterSetting: "kind", message: "ok" }),
        getMem0Status: vi.fn().mockResolvedValue({ status: "ready" }),
        import: vi.fn().mockResolvedValue([character]),
        importMemories: vi.fn().mockResolvedValue({
          chunkCount: 1,
          duplicateCount: 0,
          estimatedTotalTokens: 100,
          extractedCount: 1,
          fileCount: 1,
          savedCount: 1,
        }),
        list: vi.fn().mockResolvedValue([character]),
        listMemories: vi.fn().mockResolvedValue({ agentId: "Nanami", count: 0, memories: [] }),
        previewMemoryImport: vi.fn().mockResolvedValue({
          chunkCount: 1,
          dialogueCharacters: 100,
          dialogueLineCount: 2,
          estimatedInputTokens: 80,
          estimatedOutputTokens: 20,
          estimatedTotalTokens: 100,
          fileCount: 1,
          files: [],
          sourceTokens: 25,
          warnings: [],
        }),
        remember: vi.fn().mockResolvedValue({ agentId: "Nanami", count: 1, memories: [] }),
        searchMemories: vi.fn().mockResolvedValue({ agentId: "Nanami", count: 1, memories: [] }),
        save: vi.fn().mockResolvedValue(character),
        saveEmotionTags: vi.fn().mockResolvedValue(character),
        saveSpriteScale: vi.fn().mockResolvedValue(character),
        saveSpriteVoiceText: vi.fn().mockResolvedValue(character),
        saveSpriteVoiceType: vi.fn().mockResolvedValue(character),
        translateFields: vi.fn().mockResolvedValue({ characterSetting: "kind", emotionTags: "happy", name: "Nanami" }),
        uploadSpriteVoice: vi.fn().mockResolvedValue(character),
        uploadSprites: vi.fn().mockResolvedValue(character),
      },
    };
    const { background: backgrounds, character: characters } = await loadRepositories(platform);

    await backgrounds.saveBackground(background, "Old Room");
    await backgrounds.saveBackgroundImageTags({ bgTags: "day", name: "Room" });
    await backgrounds.saveBackgroundBgmTags({ bgmTags: "music", name: "Room" });
    await backgrounds.deleteBackgroundImage("Room", 1);
    await backgrounds.deleteAllBackgroundImages("Room");
    await backgrounds.deleteBackgroundBgm("Room", 2);
    await backgrounds.deleteAllBackgroundBgm("Room");
    await backgrounds.importBackgrounds(["/tmp/room.zip"]);
    await backgrounds.exportBackground("Room");
    await backgrounds.translateBackgroundFields({ bgTags: "day", bgmTags: "music", name: "Room" });
    await backgrounds.uploadBackgroundImages({ bgTags: "day", name: "Room", paths: ["/tmp/a.png"] });
    await backgrounds.uploadBackgroundBgm({ bgmTags: "music", name: "Room", paths: ["/tmp/a.mp3"] });
    await backgrounds.autoLabelBackgroundImages("Room");
    await characters.saveCharacter(character, "Old Nanami");
    await characters.generateCharacterSetting({ name: "Nanami", setting: "kind" });
    await characters.translateCharacterFields({ characterSetting: "kind", emotionTags: "happy", name: "Nanami" });
    await characters.listCharacterMemories("Nanami");
    await characters.searchCharacterMemories({ name: "Nanami", query: "tea" });
    await characters.rememberCharacterMemory("Nanami", "likes tea");
    await characters.deleteCharacterMemory("Nanami", "memory-1");
    const historyFile = new File(["User: hello"], "history.json");
    await characters.previewCharacterMemoryImport("Nanami", [historyFile]);
    await characters.importCharacterMemories("Nanami", [historyFile]);
    await characters.uploadCharacterSprites({ emotionTags: "happy", name: "Nanami", paths: ["/tmp/a.png"] });
    await characters.saveCharacterEmotionTags("Nanami", "happy");
    await characters.deleteCharacterSprite("Nanami", 0);
    await characters.deleteAllCharacterSprites("Nanami");
    await characters.saveSpriteScale("Nanami", 1.2);
    await characters.uploadSpriteVoice({ name: "Nanami", spriteIndex: 0, voicePath: "/tmp/a.wav", voiceText: "hello" });
    await characters.saveSpriteVoiceText("Nanami", 0, "hello");
    await characters.deleteSpriteVoice("Nanami", 0);
    await characters.autoLabelCharacterSprites("Nanami");

    expect(platform.backgrounds.save).toHaveBeenCalledWith(background, "Old Room");
    expect(platform.backgrounds.autoLabelImages).toHaveBeenCalledWith("Room", undefined);
    expect(platform.backgrounds.deleteImage).toHaveBeenCalledWith("Room", 1);
    expect(platform.backgrounds.uploadImages).toHaveBeenCalledWith({
      bgTags: "day",
      name: "Room",
      paths: ["/tmp/a.png"],
    });
    expect(platform.characters.save).toHaveBeenCalledWith(character, "Old Nanami");
    expect(platform.characters.autoLabelSprites).toHaveBeenCalledWith("Nanami", undefined);
    expect(platform.characters.remember).toHaveBeenCalledWith("Nanami", "likes tea");
    expect(platform.characters.previewMemoryImport).toHaveBeenCalledWith("Nanami", [historyFile]);
    expect(platform.characters.importMemories).toHaveBeenCalledWith("Nanami", [historyFile], undefined);
    expect(platform.characters.uploadSpriteVoice).toHaveBeenCalledWith({
      name: "Nanami",
      spriteIndex: 0,
      voicePath: "/tmp/a.wav",
      voiceText: "hello",
    });
  });

  it("delegates plugin, MCP, tool, music cover, and chat operations", async () => {
    const effect = sampleConfig.effect_list[0];
    const taskOptions = { onTaskUpdate: vi.fn() };
    const unsubscribe = vi.fn();
    const platform = {
      chat: {
        close: vi.fn().mockResolvedValue(sampleChatSnapshot),
        command: vi.fn().mockResolvedValue(sampleChatSnapshot),
        getHistory: vi.fn().mockResolvedValue(sampleChatSnapshot.historyEntries ?? []),
        getRuntimeStatus: vi.fn().mockResolvedValue({
          chatProcessRunning: false,
          chatRuntimeClosing: false,
          state: "idle",
        }),
        getSnapshot: vi.fn().mockResolvedValue(sampleChatSnapshot),
        getTheme: vi.fn().mockResolvedValue(sampleChatTheme),
        launch: vi.fn().mockResolvedValue(sampleChatSnapshot),
        resumeLast: vi.fn().mockResolvedValue(sampleChatSnapshot),
        subscribe: vi.fn().mockReturnValue(unsubscribe),
        listThemes: vi.fn().mockResolvedValue([]),
        getThemeManifest: vi.fn().mockResolvedValue({ schema: 1, id: "windborne-adventure", name: {}, tokens: {} }),
        getActiveThemeId: vi.fn().mockResolvedValue("windborne-adventure"),
        setActiveThemeId: vi.fn().mockResolvedValue(undefined),
        uploadTheme: vi.fn().mockResolvedValue({ id: "uploaded", name: {}, source: "user" }),
        saveTheme: vi.fn().mockResolvedValue({ id: "custom", name: {}, source: "user" }),
        deleteTheme: vi.fn().mockResolvedValue(undefined),
        subscribeEvents: vi.fn().mockReturnValue(unsubscribe),
      },
      effects: {
        delete: vi.fn().mockResolvedValue(undefined),
        deleteAllAudio: vi.fn().mockResolvedValue(effect),
        deleteAudio: vi.fn().mockResolvedValue(effect),
        export: vi.fn().mockResolvedValue("/tmp/effect.zip"),
        import: vi.fn().mockResolvedValue([effect]),
        list: vi.fn().mockResolvedValue([effect]),
        save: vi.fn().mockResolvedValue(effect),
        saveAudioTags: vi.fn().mockResolvedValue(effect),
        uploadAudio: vi.fn().mockResolvedValue(effect),
      },
      logs: {
        exportDiagnostics: vi.fn().mockResolvedValue("/tmp/diagnostics.zip"),
        getDefault: vi.fn().mockResolvedValue("default log"),
        import: vi.fn().mockResolvedValue(["/tmp/imported.log"]),
        list: vi.fn().mockResolvedValue(["/tmp/shinsekai.log"]),
      },
      mcp: {
        getConfig: vi.fn().mockResolvedValue(sampleMcpConfig),
        openConfigFile: vi.fn().mockResolvedValue("data/config/mcp.yaml"),
        previewTools: vi.fn().mockResolvedValue([]),
        saveAndApply: vi.fn().mockResolvedValue(sampleMcpConfig),
      },
      musicCover: {
        run: vi.fn().mockResolvedValue({ audioPath: "/tmp/out.wav", message: "ok" }),
        saveConfig: vi.fn().mockResolvedValue({ message: "ok", systemConfig: sampleConfig.system_config }),
        search: vi.fn().mockResolvedValue({ items: [], source: "netease" }),
      },
      plugins: {
        appUpdateInfo: vi.fn().mockResolvedValue({ repo: "myouo/Shinsekai", version: "0.1.0" }),
        appUpdateRun: vi.fn().mockResolvedValue({ message: "ok", version: "0.1.0" }),
        appUpdateTags: vi.fn().mockResolvedValue(["v0.1.0"]),
        catalog: vi.fn().mockResolvedValue([]),
        getUi: vi.fn().mockResolvedValue({ pages: [], pluginId: "core-tools" }),
        install: vi.fn().mockResolvedValue({ id: "core-tools" }),
        list: vi.fn().mockResolvedValue([]),
        repoTags: vi.fn().mockResolvedValue(["v0.1.0"]),
        scanLocal: vi.fn().mockResolvedValue({
          author: "Shinsekai Contributors",
          desc: "Example plugin",
          display_name: "Shinsekai Plugin",
          entry: "plugins.plugin_example.plugin:ExamplePlugin",
          path: "/tmp/plugin-example",
          repo: "https://github.com/shinsekai/plugin-example",
          lowest_shinsekai_version: ">=0.2.0",
          social_link: "https://github.com/shinsekai",
          tags: ["shinsekai"],
          warnings: [],
        }),
        validateSubmission: vi.fn().mockResolvedValue({ errors: [], json: "{}", ok: true }),
        buildSubmissionIssueUrl: vi.fn().mockResolvedValue({
          issueUrl: "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new",
          json: "{}",
          submission: {
            author: "Shinsekai Contributors",
            desc: "Example plugin",
            display_name: "Shinsekai Plugin",
            repo: "https://github.com/shinsekai/plugin-example",
            lowest_shinsekai_version: ">=0.2.0",
            social_link: "",
            tags: ["shinsekai"],
          },
          submitUrl: "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new",
        }),
        copySubmissionJson: vi.fn().mockResolvedValue({
          clipboardText: "{}",
          json: "{}",
          message: "copied",
          submission: {
            author: "Shinsekai Contributors",
            desc: "Example plugin",
            display_name: "Shinsekai Plugin",
            repo: "https://github.com/shinsekai/plugin-example",
            lowest_shinsekai_version: ">=0.2.0",
            social_link: "",
            tags: ["shinsekai"],
          },
        }),
        runUiAction: vi.fn().mockResolvedValue({
          message: "ok",
          page: {
            id: "settings",
            kind: "settings",
            order: 0,
            pluginId: "core-tools",
            pluginVersion: "1.0",
            title: "Settings",
          },
          plugin: { id: "core-tools" },
          result: { reloaded: true },
        }),
        saveUiConfig: vi.fn().mockResolvedValue({ message: "ok", values: {} }),
        setEnabled: vi.fn().mockResolvedValue({ id: "core-tools" }),
        uninstall: vi.fn().mockResolvedValue({ message: "ok" }),
      },
      runtime: {
        installMissingDependency: vi.fn().mockResolvedValue({ message: "installed" }),
      },
      tools: {
        cropSprites: vi.fn().mockResolvedValue({ count: 1, message: "ok" }),
        generateSpritePrompts: vi.fn().mockResolvedValue({ prompts: ["smile"] }),
        generateSprites: vi.fn().mockResolvedValue({ count: 1, message: "ok" }),
        removeSpriteBackground: vi.fn().mockResolvedValue({ count: 1, message: "ok" }),
      },
    };
    const { chat, effect: effects, logs, musicCover, plugin, tools } = await loadRepositories(platform);
    const listener = vi.fn();
    const themeArchive = new File(["theme"], "theme.zip", { type: "application/zip" });

    await chat.getChatSnapshot();
    await chat.getChatRuntimeStatus();
    await chat.closeChat();
    await chat.getChatTheme();
    await chat.launchChat(sampleLastLaunch, taskOptions);
    await chat.installMissingRuntimeDependency({ moduleName: "mem0" }, taskOptions);
    await chat.resumeLastChat(taskOptions);
    await chat.sendChatCommand({ payload: "hi", type: "send-message" });
    await chat.getChatHistory();
    expect(chat.subscribeChat(listener)).toBe(unsubscribe);
    await chat.listChatThemes();
    await chat.getChatThemeManifest("windborne-adventure");
    await chat.getActiveChatThemeId();
    await chat.setActiveChatTheme("uploaded");
    await chat.uploadChatTheme(themeArchive);
    await chat.saveChatTheme({
      baseId: "windborne-adventure",
      manifest: { id: "custom", name: { en: "Custom" }, schema: 1, tokens: {} },
    });
    await chat.deleteChatTheme("uploaded");
    expect(chat.subscribeChatEvents(listener)).toBe(unsubscribe);
    expect(platform.chat.getRuntimeStatus).toHaveBeenCalledTimes(1);
    await effects.listEffects();
    await effects.saveEffect(effect, "Old Effect");
    await effects.saveEffectAudioTags({ audioTags: "spark", name: "Spark" });
    await effects.deleteEffect("Spark");
    await effects.deleteEffectAudio("Spark", 0);
    await effects.deleteAllEffectAudio("Spark");
    await effects.importEffects(["/tmp/effect.zip"]);
    await effects.exportEffect("Spark");
    await effects.uploadEffectAudio({ audioTags: "spark", name: "Spark", paths: ["/tmp/spark.wav"] });
    await logs.getDefaultLog();
    await logs.listLogFiles();
    await logs.exportDiagnosticBundle();
    await logs.importLog(["/tmp/shinsekai.log"]);
    await logs.readLog("/tmp/shinsekai.log");
    await plugin.getPluginUiDetail("core-tools");
    await plugin.savePluginUiConfig("core-tools", "settings", { enabled: true });
    await plugin.runPluginUiAction("core-tools", "settings", "reload", { enabled: true });
    await plugin.listPluginCatalog();
    await plugin.listRepoTags("myouo/Shinsekai");
    await plugin.scanLocalPlugin("/tmp/plugin-example");
    await plugin.validatePluginSubmission({
      author: "Shinsekai Contributors",
      desc: "Example plugin",
      display_name: "Shinsekai Plugin",
      repo: "https://github.com/shinsekai/plugin-example",
      lowest_shinsekai_version: ">=0.2.0",
      social_link: "",
      tags: ["shinsekai"],
    });
    await plugin.buildPluginSubmissionIssueUrl({
      author: "Shinsekai Contributors",
      desc: "Example plugin",
      display_name: "Shinsekai Plugin",
      repo: "https://github.com/shinsekai/plugin-example",
      lowest_shinsekai_version: ">=0.2.0",
      social_link: "",
      tags: ["shinsekai"],
    });
    await plugin.copyPluginSubmissionJson({
      author: "Shinsekai Contributors",
      desc: "Example plugin",
      display_name: "Shinsekai Plugin",
      repo: "https://github.com/shinsekai/plugin-example",
      lowest_shinsekai_version: ">=0.2.0",
      social_link: "",
      tags: ["shinsekai"],
    });
    await plugin.getAppUpdateInfo();
    await plugin.listAppUpdateTags();
    await plugin.runAppUpdate({ refKind: "tag", tagName: "v0.1.0" }, taskOptions);
    await plugin.installPlugin({ source: "repo", tagName: "v0.1.0" }, taskOptions);
    await plugin.setPluginEnabled("core-tools", false);
    await plugin.uninstallPlugin("core-tools");
    await plugin.getMcpConfig();
    await plugin.openMcpConfigFile();
    await plugin.previewMcpTools(sampleMcpConfig, taskOptions);
    await plugin.saveAndApplyMcpConfig(sampleMcpConfig, taskOptions);
    await tools.generateSpritePrompts({ characterName: "Nanami", count: 2 }, taskOptions);
    await tools.generateSprites(
      { characterName: "Nanami", prompts: ["smile"], referenceImage: "/tmp/ref.png" },
      taskOptions,
    );
    await tools.cropSprites({ inputDir: "/tmp/in", ratio: 1.5 }, taskOptions);
    await tools.removeSpriteBackground({ inputDir: "/tmp/in" }, taskOptions);
    await musicCover.saveMusicCoverConfig(sampleConfig.system_config);
    await musicCover.searchMusicCover({ query: "song", source: "youtube" });
    await musicCover.runMusicCover({ pickIndex: 0, query: "song", skipRvc: false, source: "youtube" }, taskOptions);

    expect(platform.chat.close).toHaveBeenCalledTimes(1);
    expect(platform.chat.launch).toHaveBeenCalledWith(sampleLastLaunch, taskOptions);
    expect(platform.chat.resumeLast).toHaveBeenCalledWith(taskOptions);
    expect(platform.runtime.installMissingDependency).toHaveBeenCalledWith({ moduleName: "mem0" }, taskOptions);
    expect(platform.chat.uploadTheme).toHaveBeenCalledWith(themeArchive);
    expect(platform.effects.uploadAudio).toHaveBeenCalledWith({
      audioTags: "spark",
      name: "Spark",
      paths: ["/tmp/spark.wav"],
    });
    expect(platform.logs.import).toHaveBeenCalledWith(["/tmp/shinsekai.log"]);
    expect(platform.logs.import).toHaveBeenCalledTimes(2);
    expect(platform.plugins.appUpdateRun).toHaveBeenCalledWith({ refKind: "tag", tagName: "v0.1.0" }, taskOptions);
    expect(platform.plugins.install).toHaveBeenCalledWith({ source: "repo", tagName: "v0.1.0" }, taskOptions);
    expect(platform.mcp.previewTools).toHaveBeenCalledWith(sampleMcpConfig, taskOptions);
    expect(platform.tools.generateSprites).toHaveBeenCalledWith(
      { characterName: "Nanami", prompts: ["smile"], referenceImage: "/tmp/ref.png" },
      taskOptions,
    );
    expect(platform.musicCover.run).toHaveBeenCalledWith(
      { pickIndex: 0, query: "song", skipRvc: false, source: "youtube" },
      taskOptions,
    );
  });
});
