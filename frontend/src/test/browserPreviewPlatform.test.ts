import { afterEach, describe, expect, it, vi } from "vitest";

import { createBrowserPreviewPlatform } from "../shared/platform/browserPreviewPlatform";

async function resolvePreview<T>(promise: Promise<T>, ms = 2_000) {
  await vi.advanceTimersByTimeAsync(ms);
  return promise;
}

describe("browser preview platform chat themes", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("switches active theme and serves matching manifests and legacy payloads", async () => {
    const platform = createBrowserPreviewPlatform();

    await expect(platform.chat.getActiveThemeId()).resolves.toBe("windborne-adventure");

    const themes = await platform.chat.listThemes();
    expect(themes.map((theme) => theme.id)).toEqual(["windborne-adventure"]);

    const windborneManifest = await platform.chat.getThemeManifest("windborne-adventure");
    expect(windborneManifest.tokens.global?.themeColor).toBe("#f3cf57");
    expect(windborneManifest.tokens.dialog?.chrome).toBe("none");
    expect(windborneManifest.tokens.logs?.code?.background).toBe("rgba(10,19,25,0.88)");

    const windborneTheme = await platform.chat.getTheme();
    expect(windborneTheme.themeColor).toBe("#f3cf57");
    expect(JSON.stringify(windborneTheme.raw)).toContain("rgba(0,0,0,0)");
  });

  it("adds uploaded preview themes as user themes and protects builtins from deletion", async () => {
    const platform = createBrowserPreviewPlatform();

    const uploaded = await platform.chat.uploadTheme(
      new File(["theme"], "mint-breeze.zip", { type: "application/zip" }),
    );
    expect(uploaded.id).toBe("mint-breeze");
    expect(uploaded.source).toBe("user");

    const themes = await platform.chat.listThemes();
    expect(themes.find((theme) => theme.id === "mint-breeze")?.source).toBe("user");

    await expect(platform.chat.deleteTheme("windborne-adventure")).rejects.toThrow("内置主题不能删除。");

    await platform.chat.deleteTheme("mint-breeze");
    const nextThemes = await platform.chat.listThemes();
    expect(nextThemes.find((theme) => theme.id === "mint-breeze")).toBeUndefined();
  });

  it("advances option and message commands through preview runtime states", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const seenStatuses: string[] = [];
    const unsubscribe = platform.chat.subscribe((snapshot) => {
      seenStatuses.push(snapshot.status);
    });

    const optionPromise = platform.chat.command({ payload: "继续", type: "submit-option" });
    await vi.advanceTimersByTimeAsync(120);
    const optionSnapshot = await optionPromise;
    expect(optionSnapshot.status).toBe("generating");
    expect(optionSnapshot.options).toEqual([]);

    await vi.advanceTimersByTimeAsync(650);
    const afterOptionPromise = platform.chat.getSnapshot();
    await vi.advanceTimersByTimeAsync(120);
    const afterOption = await afterOptionPromise;
    expect(afterOption.status).toBe("idle");
    expect(afterOption.dialogText).toContain("已选择");

    const sendPromise = platform.chat.command({ payload: "你好", type: "send-message" });
    await vi.advanceTimersByTimeAsync(120);
    const sendingSnapshot = await sendPromise;
    expect(sendingSnapshot.status).toBe("streaming");
    expect(sendingSnapshot.characterName).toBe("你");
    expect(sendingSnapshot.dialogText).toBe("你好");
    expect(sendingSnapshot.inputDraft).toBe("");

    await vi.advanceTimersByTimeAsync(700);
    expect(seenStatuses).toContain("speaking");

    await vi.advanceTimersByTimeAsync(700);
    const finalSnapshotPromise = platform.chat.getSnapshot();
    await vi.advanceTimersByTimeAsync(120);
    const finalSnapshot = await finalSnapshotPromise;
    expect(finalSnapshot.status).toBe("idle");
    expect(finalSnapshot.characterName).toBe("Nanami");
    expect(finalSnapshot.dialogText).toBe("收到：你好");

    unsubscribe();
  });

  it("clears closed-session markers when preview realtime commands resume interaction", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const seenSnapshots: Array<{ notificationText?: string; sessionClosedReason?: string; status: string }> = [];
    const unsubscribe = platform.chat.subscribe((snapshot) => {
      seenSnapshots.push({
        notificationText: snapshot.notificationText,
        sessionClosedReason: snapshot.sessionClosedReason,
        status: snapshot.status,
      });
    });

    const closePromise = platform.chat.close();
    await vi.advanceTimersByTimeAsync(120);
    const closedSnapshot = await closePromise;
    expect(closedSnapshot.sessionClosedReason).toBe("聊天会话已结束。");
    expect(closedSnapshot.notificationText).toBe("聊天会话已结束。");

    const resumePromise = platform.chat.command({ type: "resume-asr" });
    await vi.advanceTimersByTimeAsync(120);
    const resumedSnapshot = await resumePromise;

    expect(resumedSnapshot.status).toBe("listening");
    expect(resumedSnapshot.sessionClosedReason).toBe("");
    expect(resumedSnapshot.notificationText).toBe("");
    expect(
      seenSnapshots.some(
        (snapshot) =>
          snapshot.status === "idle" &&
          snapshot.sessionClosedReason === "聊天会话已结束。" &&
          snapshot.notificationText === "聊天会话已结束。",
      ),
    ).toBe(true);
    expect(
      seenSnapshots.some(
        (snapshot) =>
          snapshot.status === "listening" && snapshot.sessionClosedReason === "" && snapshot.notificationText === "",
      ),
    ).toBe(true);

    unsubscribe();
  });

  it("mutates preview background and effect assets with import, upload, tag, and delete flows", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();

    const backgrounds = await resolvePreview(platform.backgrounds.list());
    const backgroundName = backgrounds[0].name;

    const uploadedImages = await resolvePreview(
      platform.backgrounds.uploadImages({
        bgTags: backgrounds[0].bg_tags,
        name: backgroundName,
        paths: ["/tmp/day.png", "/tmp/night.png"],
      }),
    );
    expect(uploadedImages.sprites.map((sprite) => sprite.path)).toEqual(
      expect.arrayContaining(["/tmp/day.png", "/tmp/night.png"]),
    );
    expect(uploadedImages.bg_tags).toContain("场景 2");

    const taggedImages = await resolvePreview(
      platform.backgrounds.saveImageTags({ bgTags: "场景 1：白天\n场景 2：夜晚\n", name: backgroundName }),
    );
    expect(taggedImages.bg_tags).toContain("夜晚");

    const afterImageDelete = await resolvePreview(platform.backgrounds.deleteImage(backgroundName, 1));
    expect(afterImageDelete.sprites.some((sprite) => sprite.path === "/tmp/day.png")).toBe(false);

    const uploadedBgm = await resolvePreview(
      platform.backgrounds.uploadBgm({
        bgmTags: backgrounds[0].bgm_tags,
        name: backgroundName,
        paths: ["/tmp/rain.ogg"],
      }),
    );
    expect(uploadedBgm.bgm_list).toContain("/tmp/rain.ogg");

    const taggedBgm = await resolvePreview(
      platform.backgrounds.saveBgmTags({ bgmTags: "音乐 1：安静\n音乐 2：雨声\n", name: backgroundName }),
    );
    expect(taggedBgm.bgm_tags).toContain("雨声");

    const afterBgmDelete = await resolvePreview(platform.backgrounds.deleteBgm(backgroundName, 1));
    expect(afterBgmDelete.bgm_list).not.toContain("/tmp/rain.ogg");

    const savedBackground = await resolvePreview(
      platform.backgrounds.save({ ...backgrounds[0], name: "Preview Room", sprite_prefix: "" }, backgroundName),
    );
    expect(savedBackground.sprite_prefix).toBe("temp");
    expect(await resolvePreview(platform.backgrounds.export(savedBackground.name))).toContain("Preview Room.bg");

    const importedBackgrounds = await resolvePreview(platform.backgrounds.import(["/packs/imported.bg"]));
    expect(importedBackgrounds[0].sprite_prefix).toBe("imported_bg");
    await resolvePreview(platform.backgrounds.deleteAllImages(savedBackground.name));
    await resolvePreview(platform.backgrounds.deleteAllBgm(savedBackground.name));
    await resolvePreview(platform.backgrounds.delete(savedBackground.name));
    await expect(platform.backgrounds.deleteImage("missing", 0)).rejects.toThrow("背景图片不存在");
    await expect(platform.backgrounds.deleteAllBgm("missing")).rejects.toThrow("背景组不存在");

    const effects = await resolvePreview(platform.effects.list());
    const effectName = effects[0].name;
    const savedEffect = await resolvePreview(platform.effects.save({ ...effects[0], name: "Thunder" }, effectName));
    expect(savedEffect.name).toBe("Thunder");

    const uploadedAudio = await resolvePreview(
      platform.effects.uploadAudio({
        audioTags: "特效 1：雷声\n",
        name: "Thunder",
        paths: ["/tmp/thunder.wav", "/tmp/rain.wav"],
      }),
    );
    expect(uploadedAudio.audio_list).toEqual(["/tmp/thunder.wav", "/tmp/rain.wav"]);
    expect(uploadedAudio.audio_tags).toContain("特效 2");

    const taggedAudio = await resolvePreview(
      platform.effects.saveAudioTags({ audioTags: "特效 1：雷声\n特效 2：雨声\n", name: "Thunder" }),
    );
    expect(taggedAudio.audio_tags).toContain("雨声");

    const afterAudioDelete = await resolvePreview(platform.effects.deleteAudio("Thunder", 0));
    expect(afterAudioDelete.audio_list).toEqual(["/tmp/rain.wav"]);

    const clearedAudio = await resolvePreview(platform.effects.deleteAllAudio("Thunder"));
    expect(clearedAudio.audio_list).toEqual([]);

    const importedEffects = await resolvePreview(platform.effects.import([new File(["ef"], "wind.ef")]));
    expect(importedEffects[0].name).toBe("wind");
    expect(await resolvePreview(platform.effects.export("Thunder"))).toContain("Thunder.ef");
    await resolvePreview(platform.effects.delete("Thunder"));
    await expect(platform.effects.deleteAudio("missing", 0)).rejects.toThrow("特效音频不存在");
    await expect(platform.effects.saveAudioTags({ audioTags: "", name: "missing" })).rejects.toThrow("特效方案不存在");
  });

  it("mutates preview characters, sprite voices, and memories", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();

    const characters = await resolvePreview(platform.characters.list());
    const character = characters[0];
    const saved = await resolvePreview(
      platform.characters.save({ ...character, color: "", name: "Mika", sprite_prefix: "" }, character.name),
    );
    expect(saved.color).toBe("#d07d7d");
    expect(saved.sprite_prefix).toBe("temp");

    await resolvePreview(platform.characters.save({ ...saved, name: "Nana" }));
    await expect(platform.characters.save({ ...saved, name: "Mika" }, "Nana")).rejects.toThrow("名称");

    const withSprites = await resolvePreview(
      platform.characters.uploadSprites({
        emotionTags: "立绘 1：微笑\n",
        name: "Mika",
        paths: ["/tmp/happy.png", "/tmp/sad.png"],
      }),
    );
    expect(withSprites.sprites.map((sprite) => sprite.path)).toContain("data/sprite/temp/happy.png");

    const scaled = await resolvePreview(platform.characters.saveSpriteScale("Mika", 1.25));
    expect(scaled.sprite_scale).toBe(1.25);

    const tagged = await resolvePreview(platform.characters.saveEmotionTags("Mika", "立绘 1：开心\n"));
    expect(tagged.emotion_tags).toContain("开心");

    const withVoice = await resolvePreview(
      platform.characters.uploadSpriteVoice({
        name: "Mika",
        spriteIndex: 0,
        voicePath: "/tmp/voice.wav",
        voiceText: "hello",
      }),
    );
    expect(withVoice.sprites[0].voice_path).toBe("/tmp/voice.wav");

    const voiceText = await resolvePreview(platform.characters.saveSpriteVoiceText("Mika", 0, "updated"));
    expect(voiceText.sprites[0].voice_text).toBe("updated");

    const voiceType = await resolvePreview(platform.characters.saveSpriteVoiceType("Mika", 0, "reference"));
    expect(voiceType.sprites[0].voice_type).toBe("reference");

    const voiceDeleted = await resolvePreview(platform.characters.deleteSpriteVoice("Mika", 0));
    expect(voiceDeleted.sprites[0].voice_path).toBe("");

    const spriteDeleted = await resolvePreview(platform.characters.deleteSprite("Mika", 0));
    expect(spriteDeleted.sprites).toHaveLength(2);

    const memories = await resolvePreview(platform.characters.listMemories("Mika"));
    expect(memories.count).toBe(1);
    const remembered = await resolvePreview(platform.characters.remember("Mika", "likes tea"));
    expect(remembered.memories.some((memory) => memory.memory === "likes tea")).toBe(true);
    const afterMemoryDelete = await resolvePreview(platform.characters.deleteMemory("Mika", remembered.memories[0].id));
    expect(afterMemoryDelete.count).toBe(1);

    const generated = await resolvePreview(platform.characters.generateSetting({ name: "Mika" }));
    expect(generated.characterSetting).toContain("Mika");
    const translated = await resolvePreview(
      platform.characters.translateFields({ characterSetting: "setting", emotionTags: "tags", name: "Mika" }),
    );
    expect(translated).toEqual({ characterSetting: "setting", emotionTags: "tags", name: "Mika" });
    expect(await resolvePreview(platform.characters.export("Mika"))).toContain("Mika.char");

    const imported = await resolvePreview(platform.characters.import(["/characters/hero.char"]));
    expect(imported[0].sprite_prefix).toBe("hero_char");
    const cleared = await resolvePreview(platform.characters.deleteAllSprites("Mika"));
    expect(cleared.sprites).toEqual([]);
    await resolvePreview(platform.characters.delete("Mika"));

    await expect(platform.characters.saveEmotionTags("", "tags")).rejects.toThrow("请先选择或创建角色");
    await expect(platform.characters.deleteSpriteVoice("missing", 0)).rejects.toThrow("立绘不存在");
  });

  it("serves preview config, file browsing, logs, music-cover, runtime, and tool tasks", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    vi.spyOn(window, "open").mockImplementation(() => null);
    const taskUpdates: string[] = [];
    const options = {
      onTaskUpdate: (task: { phase: string }) => {
        taskUpdates.push(task.phase);
      },
    };

    const config = await resolvePreview(platform.config.get());
    expect(config.system_config.voice_language).toBe("ja");
    const api = await resolvePreview(platform.config.saveApi({ ...config.api_config, llm_provider: "ChatGPT" }));
    expect(api.llm_provider).toBe("ChatGPT");
    const system = await resolvePreview(platform.config.saveSystem({ ...config.system_config, voice_language: "en" }));
    expect(system.voice_language).toBe("en");
    expect((await resolvePreview(platform.config.detectNetworkProxy())).source).toBe("browser-preview");
    expect((await resolvePreview(platform.config.getTtsBundleRecommendation())).kind).toBe("gptso");
    const bundle = await resolvePreview(platform.config.downloadTtsBundle({ kind: "genie" }, options), 1_000);
    expect(bundle.provider).toBe("genie-tts");
    expect(taskUpdates).toEqual(expect.arrayContaining(["download", "extract", "completed"]));
    expect((await resolvePreview(platform.config.cancelTtsBundleDownload("task-1"))).status).toBe("cancelled");
    await expect(platform.config.fetchLlmModels()).rejects.toThrow("Python bridge");
    await expect(platform.config.testLlmConnection({})).rejects.toThrow("LLM 连通检测");

    const root = await resolvePreview(platform.files.browse({ path: "/" }));
    expect(root.entries.map((entry) => entry.name)).toContain("home");
    const fallback = await resolvePreview(platform.files.browse({ path: "/does/not/exist" }));
    expect(fallback.cwd).toBe("/home/shinsekai/project");
    expect(await resolvePreview(platform.files.thumbnailBatch(["/tmp/a.png", ""], {}))).toEqual({
      "/tmp/a.png": "/tmp/a.png",
    });
    expect(platform.files.thumbnailUrl("/tmp/a.png")).toBe("/tmp/a.png");
    await resolvePreview(platform.files.openExternal("https://example.test"));
    expect(window.open).toHaveBeenCalledWith("https://example.test", "_blank", "noopener,noreferrer");

    const defaultLog = await resolvePreview(platform.logs.getDefault());
    expect(defaultLog.content).toContain("Preview mode");
    expect((await resolvePreview(platform.logs.list())).files[0].relativePath).toContain("preview.log");
    const manualLog = new File(["hello"], "manual.log") as File & { text: () => Promise<string> };
    Object.defineProperty(manualLog, "text", { configurable: true, value: vi.fn().mockResolvedValue("hello") });
    const importedFileLog = await resolvePreview(platform.logs.import([manualLog]));
    expect(importedFileLog.content).toBe("hello");
    const importedPathLog = await resolvePreview(platform.logs.import(["/tmp/runtime.log"]));
    expect(importedPathLog.name).toBe("runtime.log");
    expect((await resolvePreview(platform.logs.exportDiagnostics())).downloadUrl).toContain("diagnostics");

    expect((await resolvePreview(platform.runtime.installMissingDependency({ moduleName: "demo" }))).moduleName).toBe(
      "demo",
    );

    const musicConfig = await resolvePreview(platform.musicCover.saveConfig({ music_cover_work_dir: "/tmp/music" }));
    expect(musicConfig.systemConfig.music_cover_work_dir).toBe("/tmp/music");
    expect((await resolvePreview(platform.musicCover.search({ query: "song", source: "youtube" }))).log).toContain(
      "song",
    );
    const runResult = await resolvePreview(
      platform.musicCover.run({ pickIndex: 1, query: "song", skipRvc: true, source: "youtube" }, options),
      1_000,
    );
    expect(runResult.audioPath).toContain("final_mix.wav");

    expect(
      (await resolvePreview(
        platform.tools.cropSprites({ inputDir: "/tmp/sprites", outputDir: "", ratio: 0.55 }, options),
        1_000,
      )).outputDir,
    ).toContain("cropped_upper_0.55");
    expect(
      (await resolvePreview(
        platform.tools.generateSpritePrompts({ characterName: "Mika", count: 2, scenario: "scene" }, options),
        1_000,
      )).prompts,
    ).toHaveLength(2);
    expect(
      (await resolvePreview(
        platform.tools.generateSprites({ characterName: "Mika", outputDir: "", prompts: ["a", "b"] }, options),
        1_000,
      )).files,
    ).toHaveLength(2);
    expect(
      (await resolvePreview(platform.tools.removeSpriteBackground({ inputDir: "/tmp/sprites", outputDir: "" }, options), 1_000))
        .outputDir,
    ).toContain("removed_backgrounds");
  });

  it("manages preview plugins, MCP config, template sessions, and update tasks", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const progressPhases: string[] = [];
    const options = {
      onTaskUpdate: (task: { phase: string }) => {
        progressPhases.push(task.phase);
      },
    };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });

    expect((await resolvePreview(platform.plugins.catalog())).map((item) => item.id)).toContain("vision-demo");
    const installed = await resolvePreview(platform.plugins.install("vision-demo", options), 1_500);
    expect(installed.id).toBe("vision-demo");
    expect(progressPhases).toEqual(expect.arrayContaining(["download", "pip", "completed"]));
    expect((await resolvePreview(platform.plugins.list())).some((plugin) => plugin.id === "vision-demo")).toBe(true);
    expect((await resolvePreview(platform.plugins.getUi("vision-demo"))).pages[0].title).toBe("预览设置");
    expect((await resolvePreview(platform.plugins.setEnabled("vision-demo", false))).enabled).toBe(false);
    expect(
      (await resolvePreview(platform.plugins.runUiAction("vision-demo", "settings-0", "save", { enabled: true }))).message,
    ).toContain("save");
    expect(
      (await resolvePreview(platform.plugins.saveUiConfig("vision-demo", "settings-0", { enabled: true }))).page.values,
    ).toEqual({ enabled: true });
    const scanned = await resolvePreview(platform.plugins.scanLocal({ path: "/plugins/my-plugin" }));
    expect(scanned.entry).toContain("my_plugin");

    const invalidSubmission = await resolvePreview(
      platform.plugins.validateSubmission({ author: "", desc: "x", display_name: "", repo: "bad", tags: [] }),
    );
    expect(invalidSubmission.ok).toBe(false);

    const submission = {
      author: "A",
      desc: "Useful plugin",
      display_name: "Useful",
      lowest_shinsekai_version: ">=0.2.0",
      repo: "https://github.com/example/useful.git",
      social_link: " https://example.test ",
      tags: [" tools ", "ai"],
    };
    const validSubmission = await resolvePreview(platform.plugins.validateSubmission(submission));
    expect(validSubmission.submission?.repo).toBe("https://github.com/example/useful");
    expect((await resolvePreview(platform.plugins.buildSubmissionIssueUrl(submission))).issueUrl).toContain(
      "PLUGIN_PUBLISH",
    );
    expect((await resolvePreview(platform.plugins.copySubmissionJson(submission))).clipboardText).toContain("Useful");
    await expect(platform.plugins.buildSubmissionIssueUrl({ ...submission, repo: "bad" })).rejects.toThrow("repo");

    expect(await resolvePreview(platform.plugins.repoTags("repo"))).toContain("v1.0.0");
    expect(await resolvePreview(platform.plugins.appUpdateTags())).toContain("v1.0.0");
    expect((await resolvePreview(platform.plugins.appUpdateInfo())).version).toBe("preview");
    expect(
      (await resolvePreview(platform.plugins.appUpdateRun({ refKind: "tag", tagName: "v1.0.0" }, options), 1_000))
        .message,
    ).toContain("v1.0.0");
    expect((await resolvePreview(platform.plugins.uninstall("vision-demo"))).message).toContain("已卸载");
    await expect(platform.plugins.getUi("missing")).rejects.toThrow("插件不存在");

    const mcpConfig = await resolvePreview(platform.mcp.getConfig());
    expect(mcpConfig.enabled).toBe(true);
    expect(await resolvePreview(platform.mcp.openConfigFile())).toContain("mcp.yaml");
    expect((await resolvePreview(platform.mcp.previewTools(mcpConfig, options), 1_000))[0].registered_name).toBe(
      "demo_search",
    );
    const savedMcp = await resolvePreview(platform.mcp.saveAndApply({ ...mcpConfig, enabled: false }, options), 1_000);
    expect(savedMcp.enabled).toBe(false);

    const generated = await resolvePreview(
      platform.templates.generate({ characters: ["Nanami"], name: "Scene", voiceLanguage: "en" }),
      1_000,
    );
    expect(generated.scenario).toContain("Nanami");
    const savedTemplate = await resolvePreview(platform.templates.save({ ...generated, id: "", name: "Scene" }));
    expect(savedTemplate.path).toContain("Scene.txt");
    expect((await resolvePreview(platform.templates.list())).some((template) => template.name === "Scene")).toBe(true);
    expect(await resolvePreview(platform.templates.getSession())).toBeNull();
    await resolvePreview(
      platform.templates.saveSession({
        background: "默认房间",
        historyPath: "/tmp/history.json",
        selectedCharacters: ["Nanami"],
        templateFileDropdown: "Scene",
      }),
    );
    expect((await resolvePreview(platform.templates.getSession()))?.historyPath).toBe("/tmp/history.json");

    const task = await platform.tasks.get("task-1");
    expect(task.status).toBe("succeeded");
  });

  it("handles preview chat branch, history, launch, and event commands", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const events: string[] = [];
    const unsubscribeEvents = platform.chat.subscribeEvents((event) => {
      events.push(event.type);
    });

    expect((await resolvePreview(platform.chat.getHistory())).some((entry) => entry.role === "user")).toBe(true);
    expect((await resolvePreview(platform.chat.command({ type: "pause-asr" }))).status).toBe("paused");
    expect((await resolvePreview(platform.chat.command({ type: "resume-asr" }))).status).toBe("listening");
    expect((await resolvePreview(platform.chat.command({ payload: "en", type: "change-voice-language" }))).voiceLanguage).toBe(
      "en",
    );
    expect((await resolvePreview(platform.chat.command({ type: "dialog-advance" }))).status).toBe("idle");
    expect((await resolvePreview(platform.chat.command({ type: "skip-speech" }))).status).toBe("idle");
    expect((await resolvePreview(platform.chat.command({ type: "open-history" }))).openedPath).toContain("preview");
    expect((await resolvePreview(platform.chat.command({ type: "copy-history" }))).clipboardText).toContain("Nanami");

    const forked = await resolvePreview(platform.chat.command({ payload: { userIndex: 0 }, type: "fork-history" }));
    expect(forked.conversationTree?.activeBranchId).toMatch(/^branch-/);
    const branchId = forked.conversationTree?.activeBranchId ?? "";
    await resolvePreview(platform.chat.command({ payload: { branchId, label: "Alt route" }, type: "rename-branch" }));
    const renamed = await resolvePreview(platform.chat.getSnapshot());
    expect(renamed.conversationTree?.branches.find((branch) => branch.id === branchId)?.label).toBe("Alt route");

    const switchedMain = await resolvePreview(platform.chat.command({ payload: "main", type: "switch-branch" }));
    expect(switchedMain.conversationTree?.activeBranchId).toBe("main");

    const reverted = await resolvePreview(platform.chat.command({ payload: 0, type: "revert-history" }));
    expect(reverted.historyEntries.at(-1)?.role).toBe("system");

    const cleared = await resolvePreview(platform.chat.command({ type: "clear-history" }));
    expect(cleared.historyEntries).toEqual([]);

    const launched = await resolvePreview(
      platform.chat.launch({
        backgroundName: "默认房间",
        characters: ["Nanami"],
        historyPath: "/tmp/session.json",
        templateId: "default",
        templateName: "Default",
      }),
    );
    expect(launched.statusMessage).toContain("/tmp/session.json");

    await resolvePreview(
      platform.templates.saveSession({
        background: "默认房间",
        historyPath: "/tmp/resume.json",
        selectedCharacters: ["Nanami"],
        templateFileDropdown: "default",
      }),
    );
    const resumed = await resolvePreview(platform.chat.resumeLast());
    expect(resumed.statusMessage).toContain("/tmp/resume.json");

    expect(events).toContain("snapshot");
    unsubscribeEvents();
  });
});
