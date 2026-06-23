import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpPlatform } from "../../../shared/platform/httpPlatform";
import {
  sampleConfig,
  sampleMcpConfig,
  sampleMcpTools,
  samplePluginCatalog,
  samplePlugins,
  sampleTemplates,
} from "../../../shared/platform/sampleData";

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
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete window.__SHINSEKAI_BRIDGE_RESTARTING__;
    delete window.__SHINSEKAI_RESTARTING__;
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

  it("sends bridge auth token on requests and generated media URLs", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(sampleConfig));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787", "bridge-secret");
    await platform.config.get();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Shinsekai-Bridge-Token": "bridge-secret",
        }),
      }),
    );
    expect(platform.files.fileUrl("data/speech/nanami/hello.wav")).toBe(
      "http://127.0.0.1:8787/api/media?path=data%2Fspeech%2Fnanami%2Fhello.wav&shinsekai_bridge_token=bridge-secret",
    );
    expect(platform.files.thumbnailUrl("data/speech/nanami/hello.wav", { size: 160 })).toBe(
      "http://127.0.0.1:8787/api/media/thumbnail?path=data%2Fspeech%2Fnanami%2Fhello.wav&size=160&shinsekai_bridge_token=bridge-secret",
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

  it("tests LLM connectivity through a dedicated bridge endpoint", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse({ message: "LLM 连通检测通过。" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.config.testLlmConnection({
      apiKey: "sk-test",
      baseUrl: "http://127.0.0.1:1234/v1",
      model: "local-model",
      provider: "Local",
    });

    expect(result.message).toBe("LLM 连通检测通过。");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config/llm-connection-test",
      expect.objectContaining({
        body: JSON.stringify({
          apiKey: "sk-test",
          baseUrl: "http://127.0.0.1:1234/v1",
          model: "local-model",
          provider: "Local",
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

  it("reads TTS bundle recommendation through the bridge", async () => {
    const recommendation = {
      gpus: [{ device: "GeForce RTX 5090", vendor: "NVIDIA", vram_gb: 32 }],
      kind: "gptso50",
      platform: "Windows 11",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(recommendation));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.config.getTtsBundleRecommendation();

    expect(result.kind).toBe("gptso50");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config/tts-bundle/recommendation",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("detects network proxy settings through the bridge", async () => {
    const detected = {
      http_proxy_url: "http://127.0.0.1:7890",
      https_proxy_url: "http://127.0.0.1:7890",
      socks5_proxy_url: "socks5://127.0.0.1:7891",
      source: "environment",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(detected));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.config.detectNetworkProxy();

    expect(result).toEqual(detected);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/config/network-proxy/detect",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("cancels TTS bundle download tasks through the bridge", async () => {
    const task = {
      createdAt: 1,
      id: "tts-task",
      kind: "tts-bundle",
      logs: [],
      message: "任务已取消，已清理下载内容。",
      phase: "cancelled",
      progress: null,
      result: null,
      status: "cancelled",
      title: "TTS 整合包下载",
      updatedAt: 2,
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(task));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.config.cancelTtsBundleDownload("tts-task");

    expect(result.status).toBe("cancelled");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/tasks/tts-task/cancel",
      expect.objectContaining({
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
    expect(platform.files.thumbnailUrl("data/speech/nanami/hello.wav", { size: 160 })).toBe(
      "http://127.0.0.1:8787/api/media/thumbnail?path=data%2Fspeech%2Fnanami%2Fhello.wav&size=160",
    );
  });

  it("fetches local media thumbnails in one batch", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse({
        items: [
          { cachePath: ".cache/frontend-media-thumbnails/aaa.png", path: "data/backgrounds/a.png" },
          { error: "missing", path: "data/backgrounds/missing.png" },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await expect(
      platform.files.thumbnailBatch!(["data/backgrounds/a.png", "https://example.test/remote.png"], { size: 160 }),
    ).resolves.toEqual({
      "data/backgrounds/a.png": "http://127.0.0.1:8787/api/media?path=.cache%2Ffrontend-media-thumbnails%2Faaa.png",
      "https://example.test/remote.png": "https://example.test/remote.png",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/media/thumbnails",
      expect.objectContaining({
        body: JSON.stringify({ mode: "url", paths: ["data/backgrounds/a.png"], size: 160 }),
        method: "POST",
      }),
    );
  });

  it("can request embedded thumbnail data for eager image batches", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      mockJsonResponse({
        items: [
          {
            cachePath: ".cache/frontend-media-thumbnails/aaa.png",
            dataUrl: "data:image/png;base64,AAA",
            path: "data/backgrounds/a.png",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await expect(
      platform.files.thumbnailBatch!(["data/backgrounds/a.png"], { delivery: "data", size: 160 }),
    ).resolves.toEqual({
      "data/backgrounds/a.png": "data:image/png;base64,AAA",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/media/thumbnails",
      expect.objectContaining({
        body: JSON.stringify({ mode: "data", paths: ["data/backgrounds/a.png"], size: 160 }),
        method: "POST",
      }),
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
      dialogText: "",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
      statusMessage: "聊天进程已启动！PID: 123",
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

    expect(result.dialogText).toBe("");
    expect(result.statusMessage).toContain("聊天进程已启动");
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
      dialogText: "",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
      statusMessage: "聊天进程已启动！PID: 123",
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
      effectNames: [],
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
      dialogText: "",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
      statusMessage: "聊天进程已启动！PID: 456",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.resumeLast();

    expect(result.dialogText).toBe("");
    expect(result.statusMessage).toContain("聊天进程已启动");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/resume-last",
      expect.objectContaining({
        body: JSON.stringify({}),
        method: "POST",
      }),
    );
  });

  it("closes the live chat session through the bridge with keepalive enabled", async () => {
    const snapshot = {
      dialogText: "聊天会话已结束。",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sessionClosedReason: "聊天会话已结束。",
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.close();

    expect(result.sessionClosedReason).toBe("聊天会话已结束。");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/close",
      expect.objectContaining({
        body: JSON.stringify({}),
        keepalive: true,
        method: "POST",
      }),
    );
  });

  it("subscribes to chat events over websocket when the snapshot exposes a session", async () => {
    const snapshot = {
      backgroundPath: "",
      characterName: "Nanami",
      dialogText: "聊天已连接。",
      eventSeq: 0,
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sessionId: "session-1",
      sprites: [],
      status: "idle",
      wsUrl: "ws://127.0.0.1:8788/ws",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    class FakeWebSocket {
      static instances: FakeWebSocket[] = [];

      onclose: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      url: string;
      close = vi.fn(() => undefined);

      constructor(url: string) {
        this.url = url;
        FakeWebSocket.instances.push(this);
      }
    }

    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const platform = createHttpPlatform("http://127.0.0.1:8787", "bridge-secret");
    const listener = vi.fn();
    const unsubscribe = platform.chat.subscribeEvents(listener);

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/snapshot",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Shinsekai-Bridge-Token": "bridge-secret",
        }),
      }),
    );
    expect(FakeWebSocket.instances[0]?.url).toBe(
      "ws://127.0.0.1:8788/ws?sessionId=session-1&role=viewer&shinsekai_bridge_token=bridge-secret",
    );
    expect(listener).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        snapshot,
        type: "snapshot",
        v: 1,
      }),
    );

    FakeWebSocket.instances[0]?.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          seq: 7,
          text: "正在回复……",
          ts: 123,
          type: "notification.change",
          v: 1,
        }),
      }),
    );

    expect(listener).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        state: "connected",
        transport: "websocket",
        type: "transport.state",
        v: 1,
      }),
    );
    expect(listener).toHaveBeenNthCalledWith(
      3,
      expect.objectContaining({
        seq: 7,
        text: "正在回复……",
        type: "notification.change",
        v: 1,
      }),
    );

    FakeWebSocket.instances[0]?.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          cmdId: "cmd-1",
          commandType: "resume-asr",
          ok: true,
          seq: 8,
          ts: 124,
          type: "cmd.ack",
          v: 1,
        }),
      }),
    );

    expect(listener).toHaveBeenNthCalledWith(
      4,
      expect.objectContaining({
        cmdId: "cmd-1",
        commandType: "resume-asr",
        ok: true,
        seq: 8,
        type: "cmd.ack",
        v: 1,
      }),
    );

    unsubscribe();
    expect(FakeWebSocket.instances[0]?.close).toHaveBeenCalled();
  });

  it("recovers by reloading snapshot when websocket event seq has a gap", async () => {
    const initialSnapshot = {
      backgroundPath: "",
      characterName: "Nanami",
      dialogText: "聊天已连接。",
      eventSeq: 2,
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sessionId: "session-1",
      sprites: [],
      status: "idle",
      wsUrl: "ws://127.0.0.1:8788/ws",
    };
    const recoveredSnapshot = {
      ...initialSnapshot,
      dialogText: "Recovered from gap",
      eventSeq: 5,
      options: ["继续"],
    };
    const fetchMock = vi
      .fn()
      .mockImplementationOnce((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(initialSnapshot))
      .mockImplementationOnce((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(recoveredSnapshot));
    vi.stubGlobal("fetch", fetchMock);

    class FakeWebSocket {
      static instances: FakeWebSocket[] = [];

      onclose: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      url: string;
      close = vi.fn(() => undefined);

      constructor(url: string) {
        this.url = url;
        FakeWebSocket.instances.push(this);
      }
    }

    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const listener = vi.fn();
    const unsubscribe = platform.chat.subscribeEvents(listener);

    await new Promise((resolve) => setTimeout(resolve, 0));

    FakeWebSocket.instances[0]?.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          seq: 5,
          text: "gap event",
          ts: 123,
          type: "notification.change",
          v: 1,
        }),
      }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(listener).toHaveBeenLastCalledWith(
        expect.objectContaining({
          snapshot: recoveredSnapshot,
          type: "snapshot",
          v: 1,
        }),
      ),
    );

    unsubscribe();
  });

  it("falls back to snapshot polling when websocket handshake stays pending", async () => {
    vi.useFakeTimers();

    const snapshot = {
      backgroundPath: "",
      characterName: "Nanami",
      dialogText: "聊天已连接。",
      eventSeq: 0,
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sessionId: "session-1",
      sprites: [],
      status: "idle",
      wsUrl: "ws://127.0.0.1:8788/ws",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);

    class FakeWebSocket {
      static instances: FakeWebSocket[] = [];

      onclose: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onopen: ((event: Event) => void) | null = null;
      url: string;
      close = vi.fn(() => undefined);

      constructor(url: string) {
        this.url = url;
        FakeWebSocket.instances.push(this);
      }
    }

    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const listener = vi.fn();
    const unsubscribe = platform.chat.subscribeEvents(listener);

    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(0);

    expect(
      listener.mock.calls.some(
        ([event]) =>
          event &&
          typeof event === "object" &&
          "type" in event &&
          event.type === "transport.state" &&
          "state" in event &&
          event.state === "polling" &&
          "transport" in event &&
          event.transport === "snapshot",
      ),
    ).toBe(true);
    expect(FakeWebSocket.instances.length).toBeGreaterThan(0);
    expect(FakeWebSocket.instances[0]?.close).toHaveBeenCalled();

    unsubscribe();
  });

  it("falls back to polling transport state when websocket is unavailable", async () => {
    const snapshot = {
      backgroundPath: "",
      characterName: "Nanami",
      dialogText: "聊天已连接。",
      eventSeq: 0,
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", undefined);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const listener = vi.fn();
    const unsubscribe = platform.chat.subscribeEvents(listener);

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(listener).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        snapshot,
        type: "snapshot",
        v: 1,
      }),
    );
    expect(listener).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        state: "polling",
        transport: "snapshot",
        type: "transport.state",
        v: 1,
      }),
    );

    unsubscribe();
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

  it("adds cmdId to realtime chat commands before posting to the bridge", async () => {
    const snapshot = {
      dialogText: "语音识别已恢复。",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "listening",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-fixed-1") });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.chat.command({ type: "resume-asr" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ type: "resume-asr", cmdId: "cmd-fixed-1" }),
        method: "POST",
      }),
    );
  });

  it("returns reopened chat snapshots from realtime commands after a closed session", async () => {
    const reopenedSnapshot = {
      dialogText: "语音识别已恢复。",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      notificationText: "",
      options: [],
      sessionClosedReason: "",
      sprites: [],
      status: "listening",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(reopenedSnapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-fixed-reopen") });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.command({ type: "resume-asr" });

    expect(result).toMatchObject({
      dialogText: "语音识别已恢复。",
      notificationText: "",
      sessionClosedReason: "",
      status: "listening",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ type: "resume-asr", cmdId: "cmd-fixed-reopen" }),
        method: "POST",
      }),
    );
  });

  it("retries realtime chat commands after a desktop bridge restart finishes", async () => {
    const snapshot = {
      dialogText: "已继续生成。",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "generating",
    };
    let calls = 0;
    const fetchMock = vi.fn(async () => {
      calls += 1;
      if (calls === 1) {
        throw new Error("Failed to fetch http://127.0.0.1:8787/api/chat/command");
      }
      return mockJsonResponse(snapshot);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-fixed-restart") });
    window.__SHINSEKAI_BRIDGE_RESTARTING__ = true;

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const commandPromise = platform.chat.command({ type: "resume-asr" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    window.__SHINSEKAI_BRIDGE_RESTARTING__ = false;
    window.dispatchEvent(new Event("shinsekai:bridge-restart-finished"));

    await expect(commandPromise).resolves.toMatchObject({
      dialogText: "已继续生成。",
      status: "generating",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ type: "resume-asr", cmdId: "cmd-fixed-restart" }),
        method: "POST",
      }),
    );
  });

  it("treats dialog-advance as a realtime chat command and adds cmdId", async () => {
    const snapshot = {
      dialogText: "Ready",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-fixed-2") });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.chat.command({ type: "dialog-advance" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ type: "dialog-advance", cmdId: "cmd-fixed-2" }),
        method: "POST",
      }),
    );
  });

  it("treats change-voice-language as a realtime chat command and adds cmdId", async () => {
    const snapshot = {
      dialogText: "Ready",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
      voiceLanguage: "en",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-fixed-3") });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.chat.command({ payload: "en", type: "change-voice-language" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ payload: "en", type: "change-voice-language", cmdId: "cmd-fixed-3" }),
        method: "POST",
      }),
    );
  });

  it("treats revert-history as a realtime chat command and adds cmdId", async () => {
    const snapshot = {
      dialogText: "Ready",
      historyEntries: [{ id: "history-0", role: "assistant", text: "Mio: Ready" }],
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(snapshot));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "cmd-fixed-4") });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.chat.command({ payload: 1, type: "revert-history" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/command",
      expect.objectContaining({
        body: JSON.stringify({ payload: 1, type: "revert-history", cmdId: "cmd-fixed-4" }),
        method: "POST",
      }),
    );
  });

  it("loads runtime chat history through the bridge", async () => {
    const history = [
      { id: "history-0", role: "assistant", text: "Mio: Ready" },
      { id: "history-1", revertUserIndex: 0, role: "user", text: "你: hello" },
    ];
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(history));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.chat.getHistory();

    expect(result).toEqual(history);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/chat/history",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
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

    expect(catalog).toContainEqual(
      expect.objectContaining({
        repo: "RachelForster/Shinsekai-Vision-Demo",
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/plugins/registry",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("reads and saves plugin UI config through the bridge", async () => {
    const detail = {
      pages: [
        {
          id: "demo-page",
          kind: "settings",
          order: 1,
          pluginId: "plugins.demo.plugin:DemoPlugin",
          pluginVersion: "1.0.0",
          schema: [
            {
              fields: [{ key: "enabled", label: "Enabled", type: "boolean" }],
              id: "main",
              title: "Main",
            },
          ],
          title: "Demo page",
          values: { enabled: true },
        },
      ],
      plugin: {
        author: "",
        description: "demo",
        enabled: true,
        entry: "plugins.demo.plugin:DemoPlugin",
        id: "plugins.demo.plugin:DemoPlugin",
        loaded: true,
        permissions: [],
        settingsPages: ["Demo page"],
        slots: ["settings-extension"],
        title: "Demo",
        toolsTabs: [],
        version: "1.0.0",
      },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(await mockJsonResponse(detail))
      .mockResolvedValueOnce(
        await mockJsonResponse({ message: "saved", page: detail.pages[0], plugin: detail.plugin }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const ui = await platform.plugins.getUi("plugins.demo.plugin:DemoPlugin");
    const result = await platform.plugins.saveUiConfig("plugins.demo.plugin:DemoPlugin", "demo-page", {
      enabled: false,
    });

    expect(ui.pages[0]?.title).toBe("Demo page");
    expect(result.message).toBe("saved");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8787/api/plugins/plugins.demo.plugin%3ADemoPlugin/ui",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8787/api/plugins/plugins.demo.plugin%3ADemoPlugin/ui/demo-page/config",
      expect.objectContaining({
        body: JSON.stringify({ values: { enabled: false } }),
        method: "POST",
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

  it("runs plugin UI actions through the bridge", async () => {
    const actionResult = {
      message: "操作 Reload 已完成。",
      page: {
        id: "demo-page",
        kind: "settings",
        order: 1,
        pluginId: "demo.plugin",
        pluginVersion: "1.0.0",
        schema: [],
        title: "Demo page",
        values: { enabled: true },
      },
      plugin: {
        author: "",
        description: "demo",
        enabled: true,
        entry: "demo.plugin",
        id: "demo.plugin",
        loaded: true,
        permissions: [],
        settingsPages: ["Demo page"],
        slots: ["settings-extension"],
        title: "Demo",
        toolsTabs: [],
        version: "1.0.0",
      },
      result: { reloaded: true },
    };
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => mockJsonResponse(actionResult));
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const result = await platform.plugins.runUiAction("demo.plugin", "demo-page", "reload", { enabled: true });

    expect(result.message).toContain("Reload");
    expect(result.result).toEqual({ reloaded: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/plugins/demo.plugin/ui/demo-page/actions/reload",
      expect.objectContaining({
        body: JSON.stringify({ values: { enabled: true } }),
        method: "POST",
      }),
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

  it("maps effect CRUD, import, export, and audio endpoints to bridge requests", async () => {
    const openMock = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/effects") && !init?.method) {
        return mockJsonResponse(sampleConfig.effect_list);
      }
      if (url.endsWith("/api/effects/export")) {
        return mockJsonResponse({ downloadUrl: "/api/download?path=output/Fx.effect", path: "output/Fx.effect" });
      }
      if (url.endsWith("/api/effects/import")) {
        return mockJsonResponse(sampleConfig.effect_list);
      }
      return mockJsonResponse(sampleConfig.effect_list[0]);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("open", openMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.effects.list();
    await platform.effects.save({ ...sampleConfig.effect_list[0], name: "Fx" }, "Old Fx");
    await platform.effects.saveAudioTags({ audioTags: "Audio 1: pop\n", name: "Fx" });
    await platform.effects.uploadAudio({ audioTags: "", name: "Fx", paths: ["D:/fx.wav"] });
    await platform.effects.deleteAudio("Fx", 1);
    await platform.effects.deleteAllAudio("Fx");
    await platform.effects.import(["D:/fx.effect"]);
    await platform.effects.delete("Fx");
    await expect(platform.effects.export("Fx")).resolves.toBe("output/Fx.effect");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/effects",
      "http://127.0.0.1:8787/api/effects",
      "http://127.0.0.1:8787/api/effects/audio-tags",
      "http://127.0.0.1:8787/api/effects/audio/upload",
      "http://127.0.0.1:8787/api/effects/audio/delete",
      "http://127.0.0.1:8787/api/effects/audio/delete-all",
      "http://127.0.0.1:8787/api/effects/import",
      "http://127.0.0.1:8787/api/effects/Fx",
      "http://127.0.0.1:8787/api/effects/export",
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        body: JSON.stringify({ effect: { ...sampleConfig.effect_list[0], name: "Fx" }, originalName: "Old Fx" }),
        method: "POST",
      }),
    );
    expect(fetchMock.mock.calls[7][1]).toEqual(expect.objectContaining({ method: "DELETE" }));
    expect(openMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/download?path=output%2FFx.effect",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("maps background list, save, import, delete, export, and tag endpoints", async () => {
    const openMock = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/backgrounds") && !init?.method) {
        return mockJsonResponse(sampleConfig.background_list);
      }
      if (url.endsWith("/api/backgrounds/export")) {
        return mockJsonResponse({ downloadUrl: "/api/download?path=output/Room.bg", path: "output/Room.bg" });
      }
      if (url.endsWith("/api/backgrounds/import")) {
        return mockJsonResponse(sampleConfig.background_list);
      }
      return mockJsonResponse(sampleConfig.background_list[0]);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("open", openMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.backgrounds.list();
    await platform.backgrounds.save({ ...sampleConfig.background_list[0], name: "Room" }, "Old Room");
    await platform.backgrounds.saveImageTags({ bgTags: "day", name: "Room" });
    await platform.backgrounds.saveBgmTags({ bgmTags: "music", name: "Room" });
    await platform.backgrounds.import(["D:/room.bg"]);
    await platform.backgrounds.delete("Room");
    await expect(platform.backgrounds.export("Room")).resolves.toBe("output/Room.bg");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/backgrounds",
      "http://127.0.0.1:8787/api/backgrounds",
      "http://127.0.0.1:8787/api/backgrounds/tags",
      "http://127.0.0.1:8787/api/backgrounds/bgm-tags",
      "http://127.0.0.1:8787/api/backgrounds/import",
      "http://127.0.0.1:8787/api/backgrounds/Room",
      "http://127.0.0.1:8787/api/backgrounds/export",
    ]);
    expect(fetchMock.mock.calls[5][1]).toEqual(expect.objectContaining({ method: "DELETE" }));
    expect(openMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/download?path=output%2FRoom.bg",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("maps log endpoints and uploads imported log files with bridge auth headers", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/logs")) {
        return mockJsonResponse({ files: [{ label: "app.log", path: "/tmp/app.log" }] });
      }
      if (url.endsWith("/api/logs/diagnostic-bundle")) {
        return mockJsonResponse({ path: "output/diagnostics.zip" });
      }
      return mockJsonResponse({ content: "line", path: "/tmp/app.log" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787", "bridge-secret");
    await platform.logs.list();
    await platform.logs.getDefault();
    await platform.logs.import(["/tmp/app.log"]);
    await platform.logs.exportDiagnostics();
    await platform.logs.import([new File(["line"], "app.log")]);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/logs",
      "http://127.0.0.1:8787/api/logs/default",
      "http://127.0.0.1:8787/api/logs/read",
      "http://127.0.0.1:8787/api/logs/diagnostic-bundle",
      "http://127.0.0.1:8787/api/logs/import-upload",
    ]);
    expect(fetchMock.mock.calls[4][1]).toEqual(
      expect.objectContaining({
        body: expect.any(FormData),
        headers: { "X-Shinsekai-Bridge-Token": "bridge-secret" },
        method: "POST",
      }),
    );
  });

  it("returns direct media URLs and opens external browser links outside Tauri", async () => {
    const openMock = vi.fn();
    vi.stubGlobal("open", openMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");

    expect(platform.files.fileUrl("")).toBe("");
    expect(platform.files.fileUrl("https://example.test/a.png")).toBe("https://example.test/a.png");
    expect(platform.files.thumbnailUrl("", { size: 160 })).toBe("");
    expect(platform.files.thumbnailUrl("data:image/png;base64,AAA")).toBe("data:image/png;base64,AAA");
    await expect(platform.files.thumbnailBatch!(["/assets/system/picture/shinsekai.png"])).resolves.toEqual({
      "/assets/system/picture/shinsekai.png": "/assets/system/picture/shinsekai.png",
    });
    await platform.files.openExternal("https://example.test/community");

    expect(openMock).toHaveBeenCalledWith("https://example.test/community", "_blank", "noopener,noreferrer");
  });

  it("maps template list, generate, and save endpoints", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/templates") && !init?.method) {
        return mockJsonResponse(sampleTemplates);
      }
      return mockJsonResponse(sampleTemplates[0]);
    });
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await platform.templates.list();
    await platform.templates.generate({
      backgroundName: "Room",
      characters: ["Nanami"],
      name: "Custom",
      scenario: "scene",
    });
    await platform.templates.save({ ...sampleTemplates[0], name: "Custom" });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/templates",
      "http://127.0.0.1:8787/api/templates/generate",
      "http://127.0.0.1:8787/api/templates",
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        body: JSON.stringify({ backgroundName: "Room", characters: ["Nanami"], name: "Custom", scenario: "scene" }),
        method: "POST",
      }),
    );
  });

  it("maps plugin listing, enabled state, publisher, clipboard, and task endpoints", async () => {
    const clipboard = { writeText: vi.fn(() => Promise.resolve()) };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/plugins")) {
        return mockJsonResponse(samplePlugins);
      }
      if (url.endsWith("/enabled")) {
        return mockJsonResponse({ ...samplePlugins[0], enabled: false });
      }
      if (url.endsWith("/scan")) {
        return mockJsonResponse({ manifest: samplePlugins[0], packagePath: "/tmp/pkg.zip" });
      }
      if (url.endsWith("/validate")) {
        return mockJsonResponse({ errors: [], warnings: [] });
      }
      if (url.endsWith("/issue-url")) {
        return mockJsonResponse({ url: "https://github.com/RachelForster/Shinsekai/issues/new" });
      }
      if (url.endsWith("/copy-json")) {
        return mockJsonResponse({ clipboardText: '{"id":"core-tools"}' });
      }
      return mockJsonResponse({ id: "task-1", result: { ok: true }, status: "succeeded" });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("navigator", { clipboard });

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    const submission = {
      author: "Shinsekai Contributors",
      desc: "Core tools",
      display_name: "Core Tools",
      lowest_shinsekai_version: ">=0.2.0",
      repo: "https://github.com/example/core-tools",
      social_link: "",
      tags: ["tools"],
    };
    await platform.plugins.list();
    await platform.plugins.setEnabled("core-tools", false);
    await platform.plugins.scanLocal({ path: "/tmp/plugin" });
    await platform.plugins.validateSubmission(submission);
    await platform.plugins.buildSubmissionIssueUrl(submission);
    await platform.plugins.copySubmissionJson(submission);
    await platform.tasks.get("task-1");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/plugins",
      "http://127.0.0.1:8787/api/plugins/core-tools/enabled",
      "http://127.0.0.1:8787/api/plugins/publisher/scan",
      "http://127.0.0.1:8787/api/plugins/publisher/validate",
      "http://127.0.0.1:8787/api/plugins/publisher/issue-url",
      "http://127.0.0.1:8787/api/plugins/publisher/copy-json",
      "http://127.0.0.1:8787/api/tasks/task-1",
    ]);
    expect(clipboard.writeText).toHaveBeenCalledWith('{"id":"core-tools"}');
  });

  it("maps runtime, MCP apply, and tool task endpoints", async () => {
    const completedTask = (id: string, result: unknown) => ({
      createdAt: 1,
      id,
      kind: id,
      logs: [],
      message: "done",
      phase: "completed",
      progress: 1,
      result,
      status: "succeeded",
      title: id,
      updatedAt: 2,
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/mcp/config/open")) {
        return mockJsonResponse({ path: "/tmp/mcp.json" });
      }
      if (url.endsWith("/api/mcp/config/apply")) {
        return mockJsonResponse(completedTask("mcp-apply", sampleMcpConfig));
      }
      if (url.endsWith("/api/runtime/install-missing-dependency")) {
        return mockJsonResponse(completedTask("runtime-dep", { installed: true }));
      }
      if (url.endsWith("/api/tools/sprites/crop")) {
        return mockJsonResponse(completedTask("crop", { failed: [], items: [] }));
      }
      if (url.endsWith("/api/tools/sprite-prompts")) {
        return mockJsonResponse(completedTask("prompts", { prompts: ["smile"] }));
      }
      if (url.endsWith("/api/tools/sprites/generate")) {
        return mockJsonResponse(completedTask("generate", { images: ["sprite.png"] }));
      }
      return mockJsonResponse(completedTask("remove-bg", { failed: [], items: [] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const platform = createHttpPlatform("http://127.0.0.1:8787");
    await expect(platform.mcp.openConfigFile()).resolves.toBe("/tmp/mcp.json");
    await platform.mcp.saveAndApply(sampleMcpConfig);
    await platform.runtime.installMissingDependency({ moduleName: "mem0ai" });
    await platform.tools.cropSprites({ inputDir: "/tmp/sprites", ratio: 1 });
    await platform.tools.generateSpritePrompts({ characterName: "Nanami", count: 1 });
    await platform.tools.generateSprites({
      characterName: "Nanami",
      prompts: ["smile"],
      referenceImage: "/tmp/ref.png",
    });
    await platform.tools.removeSpriteBackground({ inputDir: "/tmp/sprites" });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8787/api/mcp/config/open",
      "http://127.0.0.1:8787/api/mcp/config/apply",
      "http://127.0.0.1:8787/api/runtime/install-missing-dependency",
      "http://127.0.0.1:8787/api/tools/sprites/crop",
      "http://127.0.0.1:8787/api/tools/sprite-prompts",
      "http://127.0.0.1:8787/api/tools/sprites/generate",
      "http://127.0.0.1:8787/api/tools/sprites/remove-background",
    ]);
  });
});
