import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpPlatform } from "../shared/platform/httpPlatform";
import { sampleConfig, sampleMcpConfig, sampleMcpTools, samplePluginCatalog } from "../shared/platform/sampleData";

function mockJsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    json: () => Promise.resolve(body),
    ok,
    status: ok ? 200 : 400,
    statusText: ok ? "OK" : "Bad Request",
  } as Response);
}

describe("http platform", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads app config through the bridge", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(sampleConfig));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787/");
    const config = await platform.config.get();

    expect(config.api_config.llm_provider).toBe("Deepseek");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("sends original names when saving renamed entities", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse(sampleConfig.characters[0]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.characters.save({ ...sampleConfig.characters[0], name: "Renamed" }, "Nanami");

    const [, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      character: { name: "Renamed" },
      originalName: "Nanami",
    });
  });

  it("surfaces bridge errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => mockJsonResponse({ error: "保存失败" }, false)),
    );

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await expect(platform.config.saveApi(sampleConfig.api_config)).rejects.toThrow("保存失败");
  });

  it("fetches LLM model candidates through the bridge", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse([{ id: "provider-returned-model", tags: ["text"] }]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const models = await platform.config.fetchLlmModels({
      apiKey: "sk-test",
      baseUrl: "https://api.deepseek.com/v1",
      provider: "Deepseek",
    });

    expect(models[0].id).toBe("provider-returned-model");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config/llm-models",
      expect.objectContaining({
        body: JSON.stringify({
          apiKey: "sk-test",
          baseUrl: "https://api.deepseek.com/v1",
          provider: "Deepseek",
        }),
        method: "POST",
      }),
    );
  });

  it("starts TTS bundle download tasks through the bridge", async () => {
    const task = {
      createdAt: 1,
      id: "tts-task",
      kind: "tts-bundle",
      message: "done",
      phase: "completed",
      progress: 1,
      result: { path: "/tmp/tts", provider: "genie-tts" },
      status: "succeeded",
      updatedAt: 2,
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(task));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.config.downloadTtsBundle({ kind: "genie" });

    expect(result.path).toBe("/tmp/tts");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config/tts-bundle/download",
      expect.objectContaining({
        body: JSON.stringify({ kind: "genie" }),
        method: "POST",
      }),
    );
  });

  it("uses bridge endpoints for music cover search and run tasks", async () => {
    const runTask = {
      createdAt: 1,
      id: "music-task",
      kind: "music-cover",
      message: "done",
      phase: "completed",
      progress: 1,
      result: { audioPath: "data/music_cover/out/final_mix.wav", log: "ok" },
      status: "succeeded",
      updatedAt: 2,
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/music-cover/search")) {
        return mockJsonResponse({ log: "preview" });
      }
      if (url.endsWith("/api/music-cover/config")) {
        return mockJsonResponse({ message: "音乐翻唱配置已保存。", systemConfig: sampleConfig.system_config });
      }
      return mockJsonResponse(runTask);
    });
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const search = await platform.musicCover.search({ query: "song", source: "youtube" });
    const saved = await platform.musicCover.saveConfig({
      music_cover_ffmpeg_exe: "",
      music_cover_rvc_cmd_template: "",
      music_cover_rvc_device: "cuda:0",
      music_cover_rvc_f0_method: "rmvpe",
      music_cover_rvc_filter_radius: 3,
      music_cover_rvc_index_path: "",
      music_cover_rvc_index_rate: 0.75,
      music_cover_rvc_model_path: "",
      music_cover_rvc_model_version: "v2",
      music_cover_rvc_pitch: 0,
      music_cover_rvc_protect: 0.33,
      music_cover_rvc_resample_sr: 0,
      music_cover_rvc_rms_mix_rate: 0.25,
      music_cover_uvr_cmd_template: "",
      music_cover_work_dir: "./data/music_cover",
      music_cover_yt_dlp_exe: "",
    });
    const run = await platform.musicCover.run({ pickIndex: 2, query: "song", skipRvc: true, source: "youtube" });

    expect(search.log).toBe("preview");
    expect(saved.message).toBe("音乐翻唱配置已保存。");
    expect(run.audioPath).toBe("data/music_cover/out/final_mix.wav");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/music-cover/search",
      expect.objectContaining({
        body: JSON.stringify({ query: "song", source: "youtube" }),
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/music-cover/config",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/music-cover/run",
      expect.objectContaining({
        body: JSON.stringify({ pickIndex: 2, query: "song", skipRvc: true, source: "youtube" }),
        method: "POST",
      }),
    );
  });

  it("uploads browser files without forcing JSON headers", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse(sampleConfig.characters),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.characters.import([new File(["zip"], "nanami.char")]);

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(url).toBe("http://127.0.0.1:8787/api/characters/import-upload");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).toBeUndefined();
  });

  it("browses local folders through the bridge", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse({
        cwd: "/tmp",
        entries: [{ kind: "directory", name: "assets", path: "/tmp/assets", size: null }],
        parent: "/",
        roots: [{ label: "Shinsekai", path: "/tmp" }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const snapshot = await platform.files.browse({ path: "/tmp", showHidden: true });

    expect(snapshot.cwd).toBe("/tmp");
    expect(snapshot.entries[0]?.path).toBe("/tmp/assets");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/files/browse",
      expect.objectContaining({
        body: JSON.stringify({ path: "/tmp", showHidden: true }),
        method: "POST",
      }),
    );
  });

  it("opens bridge downloads after exports", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse({ downloadUrl: "/api/download?path=output/Nanami.char", path: "output/Nanami.char" }),
    );
    const openMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("open", openMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const path = await platform.characters.export("Nanami");

    expect(path).toBe("output/Nanami.char");
    expect(openMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/download?path=output%2FNanami.char",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("calls background translate and upload endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await mockJsonResponse({ bgTags: "translated", bgmTags: "music", name: "Room" }))
      .mockResolvedValueOnce(await mockJsonResponse(sampleConfig.background_list[0]))
      .mockResolvedValueOnce(await mockJsonResponse(sampleConfig.background_list[0]))
      .mockResolvedValueOnce(await mockJsonResponse(sampleConfig.background_list[0]))
      .mockResolvedValueOnce(await mockJsonResponse(sampleConfig.background_list[0]))
      .mockResolvedValueOnce(await mockJsonResponse(sampleConfig.background_list[0]))
      .mockResolvedValueOnce(await mockJsonResponse(sampleConfig.background_list[0]));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.backgrounds.translateFields({ bgTags: "tags", bgmRowTags: ["calm"], bgmTags: "bgm", name: "Room" });
    await platform.backgrounds.uploadImages({ bgTags: "", name: "Room", paths: ["data/source/room.png"] });
    await platform.backgrounds.uploadBgm({ bgmTags: "", name: "Room", paths: ["data/source/room.mp3"] });
    await platform.backgrounds.deleteImage("Room", 0);
    await platform.backgrounds.deleteBgm("Room", 0);
    await platform.backgrounds.deleteAllImages("Room");
    await platform.backgrounds.deleteAllBgm("Room");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/backgrounds/translate",
      "http://127.0.0.1:8787/api/backgrounds/images/upload",
      "http://127.0.0.1:8787/api/backgrounds/bgm/upload",
      "http://127.0.0.1:8787/api/backgrounds/images/delete",
      "http://127.0.0.1:8787/api/backgrounds/bgm/delete",
      "http://127.0.0.1:8787/api/backgrounds/images/delete-all",
      "http://127.0.0.1:8787/api/backgrounds/bgm/delete-all",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      bgmRowTags: ["calm"],
    });
  });

  it("calls character AI and memory endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await mockJsonResponse({ characterSetting: "generated", message: "ok" }))
      .mockResolvedValueOnce(
        await mockJsonResponse({ agentId: "Nanami", count: 1, memories: [{ id: "mem-1", memory: "likes tea" }] }),
      )
      .mockResolvedValueOnce(await mockJsonResponse({ agentId: "Nanami", count: 0, memories: [] }));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.characters.generateSetting({ name: "Nanami", setting: "" });
    await platform.characters.remember("Nanami", "likes tea");
    await platform.characters.deleteMemory("Nanami", "mem-1");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/characters/ai-setting",
      "http://127.0.0.1:8787/api/characters/memories/add",
      "http://127.0.0.1:8787/api/characters/memories/delete",
    ]);
  });

  it("calls sprite voice endpoints and resolves media URLs", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse(sampleConfig.characters[0]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.characters.uploadSpriteVoice({
      name: "Nanami",
      spriteIndex: 0,
      voicePath: "data/speech/nanami/hello.wav",
      voiceText: "hello",
    });
    await platform.characters.saveSpriteVoiceText("Nanami", 0, "updated");
    await platform.characters.deleteSpriteVoice("Nanami", 0);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/characters/sprite-voice/upload",
      "http://127.0.0.1:8787/api/characters/sprite-voice/text",
      "http://127.0.0.1:8787/api/characters/sprite-voice/delete",
    ]);
    expect(platform.files.fileUrl("data/speech/nanami/hello.wav")).toBe(
      "http://127.0.0.1:8787/api/media?path=data%2Fspeech%2Fnanami%2Fhello.wav",
    );
  });

  it("calls character sprite image endpoints", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse(sampleConfig.characters[0]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.characters.uploadSprites({
      emotionTags: "",
      name: "Nanami",
      paths: ["data/source/nanami.png"],
    });
    await platform.characters.saveSpriteScale("Nanami", 1.25);
    await platform.characters.saveEmotionTags("Nanami", "立绘 1：开心");
    await platform.characters.deleteSprite("Nanami", 0);
    await platform.characters.deleteAllSprites("Nanami");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/characters/sprites/upload",
      "http://127.0.0.1:8787/api/characters/sprite-scale",
      "http://127.0.0.1:8787/api/characters/emotion-tags",
      "http://127.0.0.1:8787/api/characters/sprites/delete",
      "http://127.0.0.1:8787/api/characters/sprites/delete-all",
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        body: JSON.stringify({ name: "Nanami", scale: 1.25 }),
        method: "POST",
      }),
    );
    expect(fetchMock.mock.calls[2][1]).toEqual(
      expect.objectContaining({
        body: JSON.stringify({ emotionTags: "立绘 1：开心", name: "Nanami" }),
        method: "POST",
      }),
    );
  });

  it("reads chat theme payload through the bridge", async () => {
    const theme = {
      raw: { dialog_width_pct: 74 },
      themeColor: "rgba(50,50,50,200)",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(theme));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.getTheme();

    expect(result.themeColor).toBe("rgba(50,50,50,200)");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/theme",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("returns launch snapshots from the bridge", async () => {
    const snapshot = {
      backgroundPath: "/assets/bg.png",
      characterName: "Nanami",
      dialogText: "聊天进程已启动！PID: 123",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.launch({
      backgroundName: "默认房间",
      characters: ["Nanami"],
      historyPath: "",
      templateId: "default",
    });

    expect(result.dialogText).toContain("聊天进程已启动");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/launch",
      expect.objectContaining({
        body: JSON.stringify({
          backgroundName: "默认房间",
          characters: ["Nanami"],
          historyPath: "",
          templateId: "default",
        }),
        method: "POST",
      }),
    );
  });

  it("passes inline template launch fields through the bridge", async () => {
    const snapshot = {
      backgroundPath: "",
      characterName: "Nanami",
      dialogText: "聊天进程已启动！PID: 123",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.chat.launch({
      backgroundName: "透明场景",
      characters: ["Nanami"],
      historyPath: "",
      initSpritePath: "data/sprite/nanami/default.png",
      roomId: "12345",
      scenario: "用户情景",
      system: "系统模板",
      templateId: "",
      templateName: "session-only",
      useCg: false,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/launch",
      expect.objectContaining({
        body: JSON.stringify({
          backgroundName: "透明场景",
          characters: ["Nanami"],
          historyPath: "",
          initSpritePath: "data/sprite/nanami/default.png",
          roomId: "12345",
          scenario: "用户情景",
          system: "系统模板",
          templateId: "",
          templateName: "session-only",
          useCg: false,
        }),
        method: "POST",
      }),
    );
  });

  it("reads and saves template launch sessions through the bridge", async () => {
    const session = {
      background: "透明场景",
      filenameStub: "session-only",
      historyPath: "",
      initSpritePath: "",
      maxDialogItems: 0,
      maxSpeechChars: 0,
      roomId: "",
      scenario: "用户情景",
      selectedCharacters: ["Nanami"],
      system: "系统模板",
      templateFileDropdown: "",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: true,
      voiceLanguage: "ja",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(session));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const loaded = await platform.templates.getSession();
    const saved = await platform.templates.saveSession(session);

    expect(loaded?.scenario).toBe("用户情景");
    expect(saved.system).toBe("系统模板");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/templates/session",
      "http://127.0.0.1:8787/api/templates/session",
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        body: JSON.stringify(session),
        method: "POST",
      }),
    );
  });

  it("resumes the last chat through the bridge", async () => {
    const snapshot = {
      backgroundPath: "",
      characterName: "",
      dialogText: "聊天进程已启动！PID: 456",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.resumeLast();

    expect(result.dialogText).toContain("聊天进程已启动");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/resume-last",
      expect.objectContaining({
        body: JSON.stringify({}),
        method: "POST",
      }),
    );
  });

  it("hydrates chat command responses and copies history text", async () => {
    const clipboard = { writeText: vi.fn(() => Promise.resolve()) };
    const snapshot = {
      clipboardText: "Nanami: hello",
      dialogText: "历史记录已复制。",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("navigator", { clipboard });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.command({ type: "copy-history" });

    expect(result.dialogText).toBe("历史记录已复制。");
    expect(clipboard.writeText).toHaveBeenCalledWith("Nanami: hello");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ type: "copy-history" }),
        method: "POST",
      }),
    );
  });

  it("opens chat command download URLs through the bridge", async () => {
    const snapshot = {
      dialogText: "历史文件已打开。",
      downloadUrl: "/api/download?path=data%2Fchat_history%2Fdefault.json",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    const openMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("open", openMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.chat.command({ type: "open-history" });

    expect(openMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/download?path=data%2Fchat_history%2Fdefault.json",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("reads plugin registry catalog through the bridge", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(samplePluginCatalog));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const catalog = await platform.plugins.catalog();

    expect(catalog[0].repo).toBe("RachelForster/Shinsekai-Vision-Demo");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/plugins/registry",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("runs app self-update through task endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await mockJsonResponse({ repo: "RachelForster/Shinsekai", version: "1.0.0" }))
      .mockResolvedValueOnce(await mockJsonResponse({ tags: ["v1.0.0"] }))
      .mockResolvedValueOnce(
        await mockJsonResponse({
          createdAt: 1,
          id: "app-update-task",
          kind: "app-update",
          logs: [],
          message: "done",
          phase: "completed",
          progress: 1,
          result: { message: "updated", pipCode: "pip_skip_no_requirements", version: "1.0.1" },
          status: "succeeded",
          title: "update",
          updatedAt: 2,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const info = await platform.plugins.appUpdateInfo();
    const tags = await platform.plugins.appUpdateTags();
    const result = await platform.plugins.appUpdateRun({ refKind: "tag", tagName: "v1.0.0" });

    expect(info.version).toBe("1.0.0");
    expect(tags).toEqual(["v1.0.0"]);
    expect(result.version).toBe("1.0.1");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/plugins/app-update/info",
      "http://127.0.0.1:8787/api/plugins/app-update/tags",
      "http://127.0.0.1:8787/api/plugins/app-update/run",
    ]);
  });

  it("passes Git refs when installing registry plugins", async () => {
    const plugin = {
      author: "",
      description: "installed",
      enabled: true,
      entry: "plugins.demo.plugin:DemoPlugin",
      id: "plugins.demo.plugin:DemoPlugin",
      permissions: [],
      settingsPages: [],
      slots: ["settings-extension"],
      title: "Demo",
      toolsTabs: [],
      version: "1.0.0",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await mockJsonResponse({ tags: ["v1.0.0"] }))
      .mockResolvedValueOnce(
        await mockJsonResponse({
          createdAt: 1,
          id: "task-ref",
          kind: "plugin-install",
          logs: [],
          message: "done",
          phase: "completed",
          progress: 1,
          result: plugin,
          status: "succeeded",
          title: "install",
          updatedAt: 2,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const tags = await platform.plugins.repoTags("owner/repo");
    const result = await platform.plugins.install({
      overwrite: true,
      refKind: "tag",
      source: "owner/repo",
      tagName: "v1.0.0",
    });

    expect(tags).toEqual(["v1.0.0"]);
    expect(result.title).toBe("Demo");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8787/api/plugins/repo-tags",
      expect.objectContaining({
        body: JSON.stringify({ repo: "owner/repo" }),
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8787/api/plugins/install",
      expect.objectContaining({
        body: JSON.stringify({
          overwrite: true,
          refKind: "tag",
          source: "owner/repo",
          tagName: "v1.0.0",
        }),
        method: "POST",
      }),
    );
  });

  it("polls plugin install tasks and emits progress", async () => {
    const plugin = {
      author: "",
      description: "installed",
      enabled: true,
      entry: "plugins.demo.plugin:DemoPlugin",
      id: "plugins.demo.plugin:DemoPlugin",
      permissions: [],
      settingsPages: [],
      slots: ["settings-extension"],
      title: "Demo",
      toolsTabs: [],
      version: "1.0.0",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        await mockJsonResponse({
          createdAt: 1,
          id: "task-1",
          kind: "plugin-install",
          logs: [],
          message: "queued",
          phase: "queued",
          progress: 0,
          result: null,
          status: "queued",
          title: "install",
          updatedAt: 1,
        }),
      )
      .mockResolvedValueOnce(
        await mockJsonResponse({
          createdAt: 1,
          id: "task-1",
          kind: "plugin-install",
          logs: ["pip ok"],
          message: "done",
          phase: "completed",
          progress: 1,
          result: plugin,
          status: "succeeded",
          title: "install",
          updatedAt: 2,
        }),
      );
    const updates = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.plugins.install("plugins.demo.plugin:DemoPlugin", { onTaskUpdate: updates });

    expect(result.title).toBe("Demo");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8787/api/tasks/task-1",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
    expect(updates).toHaveBeenCalledTimes(2);
    expect(updates).toHaveBeenLastCalledWith(expect.objectContaining({ phase: "completed" }));
  });

  it("uninstalls plugins through the bridge", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse({ message: "removed" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.plugins.uninstall("plugins.demo.plugin:DemoPlugin");

    expect(result.message).toBe("removed");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/plugins/plugins.demo.plugin%3ADemoPlugin",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("reads MCP config through the bridge", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(sampleMcpConfig));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const config = await platform.mcp.getConfig();

    expect(config.path).toBe("data/config/mcp.yaml");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/mcp/config",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("polls MCP preview tasks and returns tool rows", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        await mockJsonResponse({
          createdAt: 1,
          id: "mcp-task-1",
          kind: "mcp-preview",
          logs: [],
          message: "queued",
          phase: "queued",
          progress: 0,
          result: null,
          status: "queued",
          title: "preview",
          updatedAt: 1,
        }),
      )
      .mockResolvedValueOnce(
        await mockJsonResponse({
          createdAt: 1,
          id: "mcp-task-1",
          kind: "mcp-preview",
          logs: [],
          message: "done",
          phase: "completed",
          progress: 1,
          result: sampleMcpTools,
          status: "succeeded",
          title: "preview",
          updatedAt: 2,
        }),
      );
    const updates = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const tools = await platform.mcp.previewTools(sampleMcpConfig, { onTaskUpdate: updates });

    expect(tools[0].registered_name).toBe("demo_search");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8787/api/tasks/mcp-task-1",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
    expect(updates).toHaveBeenCalledTimes(2);
  });
});
