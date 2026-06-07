import {
  sampleChatSnapshot,
  sampleConfig,
  sampleMcpConfig,
  sampleMcpTools,
  samplePluginCatalog,
  samplePlugins,
  sampleChatTheme,
  sampleTemplates,
} from "./sampleData";
import { DEFAULT_CHARACTER_COLOR } from "../constants";
import type {
  BatchToolResult,
  Background,
  Character,
  CharacterMemoryList,
  ChatSnapshot,
  LogSnapshot,
  MusicCoverRunResult,
  PluginManifest,
  PluginSubmissionInput,
  PluginUIPage,
  ShinsekaiPlatform,
  TemplateLaunchSession,
  SpriteGenerationResult,
  SpritePromptResult,
  TaskProgressOptions,
  TaskSnapshot,
  TemplateSummary,
} from "./types";

function clone<T>(value: T): T {
  return structuredClone(value);
}

function delay<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(clone(value)), ms));
}

function previewTask<TResult>(
  taskId: string,
  patch: Partial<TaskSnapshot<TResult>>,
  options?: TaskProgressOptions<TResult>,
) {
  const now = Date.now();
  options?.onTaskUpdate?.({
    createdAt: now,
    error: "",
    id: taskId,
    kind: "plugin-install",
    logs: [],
    message: "",
    phase: "queued",
    progress: 0,
    result: null,
    status: "queued",
    title: "安装插件",
    updatedAt: now,
    ...patch,
  });
}

function previewFileBrowser(path?: string) {
  const requested = (path || "/home/shinsekai/project").replace(/\\/g, "/").replace(/\/+$/, "") || "/";
  const trees: Record<string, Array<{ kind: "directory" | "file"; name: string }>> = {
    "/": [
      { kind: "directory", name: "home" },
      { kind: "directory", name: "tmp" },
    ],
    "/home": [{ kind: "directory", name: "shinsekai" }],
    "/home/shinsekai": [
      { kind: "directory", name: "Downloads" },
      { kind: "directory", name: "project" },
    ],
    "/home/shinsekai/Downloads": [
      { kind: "file", name: "reference.png" },
      { kind: "file", name: "voice.wav" },
    ],
    "/home/shinsekai/project": [
      { kind: "directory", name: "assets" },
      { kind: "directory", name: "data" },
      { kind: "directory", name: "output" },
      { kind: "directory", name: "plugins" },
      { kind: "file", name: "webui_react.py" },
    ],
    "/home/shinsekai/project/assets": [{ kind: "directory", name: "system" }],
    "/home/shinsekai/project/data": [
      { kind: "directory", name: "bgm" },
      { kind: "directory", name: "config" },
      { kind: "directory", name: "speech" },
      { kind: "directory", name: "sprite" },
      { kind: "directory", name: "tts_bundles" },
    ],
    "/home/shinsekai/project/data/bgm": [
      { kind: "file", name: "cuj-track.mp3" },
      { kind: "file", name: "rain-loop.ogg" },
    ],
    "/home/shinsekai/project/data/config": [
      { kind: "file", name: "api.yaml" },
      { kind: "file", name: "characters.yaml" },
      { kind: "file", name: "system_config.yaml" },
    ],
    "/home/shinsekai/project/data/tts_bundles": [{ kind: "directory", name: "installed" }],
  };
  const cwd = trees[requested] ? requested : "/home/shinsekai/project";
  const parent = cwd === "/" ? "" : cwd.split("/").slice(0, -1).join("/") || "/";
  return {
    cwd,
    entries: (trees[cwd] ?? []).map((entry, index) => ({
      kind: entry.kind,
      modifiedAt: Date.now() / 1000 - index * 60,
      name: entry.name,
      path: `${cwd === "/" ? "" : cwd}/${entry.name}`,
      size: entry.kind === "file" ? 4096 + index * 512 : null,
    })),
    parent,
    roots: [
      { label: "Shinsekai", path: "/home/shinsekai/project" },
      { label: "Data", path: "/home/shinsekai/project/data" },
      { label: "Downloads", path: "/home/shinsekai/Downloads" },
      { label: "Home", path: "/home/shinsekai" },
      { label: "/", path: "/" },
    ],
  };
}

const PREVIEW_PLUGIN_SUBMIT_URL =
  "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new?template=PLUGIN_PUBLISH.yml";

function normalizePreviewPluginSubmission(input: PluginSubmissionInput): PluginSubmissionInput {
  const submission: PluginSubmissionInput = {
    author: input.author.trim(),
    desc: input.desc.trim(),
    display_name: input.display_name.trim(),
    repo: input.repo.trim().replace(/\.git$/i, ""),
    social_link: (input.social_link ?? "").trim(),
    tags: (input.tags ?? [])
      .map((tag) => tag.trim())
      .filter(Boolean)
      .slice(0, 5),
  };
  const shinsekaiVersion = (input.lowest_shinsekai_version ?? "").trim();
  if (shinsekaiVersion) {
    submission.lowest_shinsekai_version = shinsekaiVersion;
  }
  return submission;
}

function previewPluginSubmissionErrors(input: PluginSubmissionInput) {
  const submission = normalizePreviewPluginSubmission(input);
  const errors: string[] = [];
  for (const field of ["display_name", "desc", "author", "repo"] as const) {
    if (!submission[field]) {
      errors.push(`${field} is required`);
    }
  }
  if (submission.desc.length > 200) {
    errors.push("desc must be 200 characters or less");
  }
  if (!/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/i.test(submission.repo)) {
    errors.push("repo must be a GitHub repository URL");
  }
  if ((input.tags ?? []).filter((tag) => tag.trim()).length > 5) {
    errors.push("tags must contain 5 items or fewer");
  }
  return errors;
}

function previewPluginSubmissionJson(input: PluginSubmissionInput) {
  return JSON.stringify(normalizePreviewPluginSubmission(input), null, 2);
}

function previewPluginIssueUrl(input: PluginSubmissionInput) {
  const submission = normalizePreviewPluginSubmission(input);
  const params = new URLSearchParams({
    "plugin-info": ["```json", previewPluginSubmissionJson(submission), "```", ""].join("\n"),
    template: "PLUGIN_PUBLISH.yml",
    title: `[Plugin] ${submission.display_name}`,
  });
  return `${PREVIEW_PLUGIN_SUBMIT_URL.split("?")[0]}?${params.toString()}`;
}

function previewLogSnapshot(): LogSnapshot {
  const lines = [
    "2026-06-03 10:00:01 [INFO] Shinsekai frontend preview started",
    "2026-06-03 10:00:02 [INFO] Bridge transport: browser preview",
    "2026-06-03 10:01:16 [WARN] Preview mode cannot read local runtime logs",
    "2026-06-03 10:02:45 [ERROR] Sample error entry for search filtering",
    "2026-06-03 10:03:12 [INFO] Import a .log or .txt file to inspect real content",
  ];
  const content = lines.join("\n");
  return {
    content,
    modifiedAt: Date.now() / 1000,
    name: "preview.log",
    path: "browser-preview://preview.log",
    size: new Blob([content]).size,
    truncated: false,
  };
}

export function createBrowserPreviewPlatform(): ShinsekaiPlatform {
  const config = clone(sampleConfig);
  let templates = clone(sampleTemplates);
  let plugins = clone(samplePlugins);
  let pluginCatalog = clone(samplePluginCatalog);
  let mcpConfig = clone(sampleMcpConfig);
  let chat = clone(sampleChatSnapshot);
  let templateSession: TemplateLaunchSession | null = null;
  const characterMemories = new Map<string, CharacterMemoryList>();
  const chatListeners = new Set<(snapshot: ChatSnapshot) => void>();

  const emitChat = () => {
    const snapshot = clone(chat);
    chatListeners.forEach((listener) => listener(snapshot));
  };

  return {
    backgrounds: {
      async delete(name) {
        config.background_list = config.background_list.filter((background) => background.name !== name);
      },
      async deleteAllBgm(name) {
        const background = config.background_list.find((item) => item.name === name);
        if (!background) {
          throw new Error("背景组不存在。");
        }
        background.bgm_list = [];
        background.bgm_tags = "";
        return delay(background);
      },
      async deleteAllImages(name) {
        const background = config.background_list.find((item) => item.name === name);
        if (!background) {
          throw new Error("背景组不存在。");
        }
        background.sprites = [];
        background.bg_tags = "";
        return delay(background);
      },
      async deleteBgm(name, index) {
        const background = config.background_list.find((item) => item.name === name);
        if (!background || !background.bgm_list[index]) {
          throw new Error("背景音乐不存在。");
        }
        background.bgm_list = background.bgm_list.filter((_, itemIndex) => itemIndex !== index);
        background.bgm_tags = background.bgm_tags
          .split(/\r?\n/)
          .filter(Boolean)
          .filter((_, itemIndex) => itemIndex !== index)
          .map((line, itemIndex) => `音乐 ${itemIndex + 1}：${line.split(/：|:/).slice(1).join("：")}`)
          .join("\n");
        if (background.bgm_tags) {
          background.bgm_tags += "\n";
        }
        return delay(background);
      },
      async deleteImage(name, index) {
        const background = config.background_list.find((item) => item.name === name);
        if (!background || !background.sprites[index]) {
          throw new Error("背景图片不存在。");
        }
        background.sprites = background.sprites.filter((_, itemIndex) => itemIndex !== index);
        background.bg_tags = background.bg_tags
          .split(/\r?\n/)
          .filter(Boolean)
          .filter((_, itemIndex) => itemIndex !== index)
          .map((line, itemIndex) => `场景 ${itemIndex + 1}：${line.split(/：|:/).slice(1).join("：")}`)
          .join("\n");
        if (background.bg_tags) {
          background.bg_tags += "\n";
        }
        return delay(background);
      },
      export: (name) => delay(`./data/export/${name}.bg`),
      import: async (items) => {
        const imported = items.map<Background>((item, index) => {
          const label = item instanceof File ? item.name : item.split("/").pop() || `background-${index + 1}`;
          return {
            bg_tags: "导入预览背景",
            bgm_list: [],
            bgm_tags: "",
            name: `Imported Background ${index + 1}`,
            sprite_prefix: label.replace(/\W+/g, "_") || "imported_background",
            sprites: [],
          };
        });
        config.background_list.push(...imported);
        return delay(imported);
      },
      list: () => delay(config.background_list),
      async save(background, originalName) {
        const index = config.background_list.findIndex((item) => item.name === (originalName || background.name));
        if (index >= 0) {
          config.background_list[index] = {
            ...config.background_list[index],
            name: background.name,
            sprite_prefix: background.sprite_prefix || "temp",
          };
        } else {
          config.background_list.push({
            bg_tags: "",
            bgm_list: [],
            bgm_tags: "",
            name: background.name,
            sprite_prefix: background.sprite_prefix || "temp",
            sprites: [],
          });
        }
        return delay(config.background_list.find((item) => item.name === background.name) ?? background);
      },
      async saveBgmTags(input) {
        const background = config.background_list.find((item) => item.name === input.name);
        if (!background) {
          throw new Error("背景组不存在。");
        }
        background.bgm_tags = input.bgmTags;
        return delay(background);
      },
      async saveImageTags(input) {
        const background = config.background_list.find((item) => item.name === input.name);
        if (!background) {
          throw new Error("背景组不存在。");
        }
        background.bg_tags = input.bgTags;
        return delay(background);
      },
      async translateFields(input) {
        return delay({ bgTags: input.bgTags, bgmRowTags: input.bgmRowTags, bgmTags: input.bgmTags, name: input.name });
      },
      async uploadBgm(input) {
        const background = config.background_list.find((item) => item.name === input.name);
        if (!background) {
          throw new Error("背景组不存在。");
        }
        background.bgm_list = [...background.bgm_list, ...input.paths];
        background.bgm_tags = `${input.bgmTags || ""}${input.paths.map((_, index) => `音乐 ${background.bgm_list.length - input.paths.length + index + 1}：`).join("\n")}\n`;
        return delay(background);
      },
      async uploadImages(input) {
        const background = config.background_list.find((item) => item.name === input.name);
        if (!background) {
          throw new Error("背景组不存在。");
        }
        background.sprites = [...background.sprites, ...input.paths.map((path) => ({ path }))];
        background.bg_tags = `${input.bgTags || ""}${input.paths.map((_, index) => `场景 ${background.sprites.length - input.paths.length + index + 1}：`).join("\n")}\n`;
        return delay(background);
      },
    },
    chat: {
      async command(command) {
        if (command.type === "send-message") {
          chat = {
            ...chat,
            dialogText: String(command.payload ?? ""),
            inputDraft: "",
            numericInfo: "streaming",
            status: "streaming",
          };
          emitChat();
          window.setTimeout(() => {
            chat = { ...chat, numericInfo: "speaking", status: "speaking" };
            emitChat();
          }, 700);
        }
        if (command.type === "submit-option") {
          chat = {
            ...chat,
            dialogText: `选择：${String(command.payload ?? "")}`,
            status: "generating",
            numericInfo: "generating",
          };
          emitChat();
        }
        if (command.type === "skip-speech") {
          chat = { ...chat, status: "idle", numericInfo: "idle" };
          emitChat();
        }
        if (command.type === "clear-history") {
          chat = { ...chat, dialogText: "浏览器预览历史已清空。", status: "idle", numericInfo: "idle" };
          emitChat();
        }
        if (command.type === "copy-history") {
          return { ...clone(chat), clipboardText: chat.dialogText };
        }
        if (command.type === "open-history") {
          return { ...clone(chat), openedPath: chat.historyPath ?? "./data/chat_history/preview.json" };
        }
        return clone(chat);
      },
      getSnapshot: () => delay(chat),
      getTheme: () => delay(sampleChatTheme),
      async launch(payload) {
        const character = config.characters.find((item) => payload.characters.includes(item.name));
        const background = config.background_list.find((item) => item.name === payload.backgroundName);
        const historyPath = payload.historyPath || chat.historyPath || "./data/chat_history/preview.json";
        chat = {
          ...chat,
          backgroundPath: background?.sprites[0]?.path,
          characterName: character?.name,
          dialogText: `${payload.templateId} 已启动：${historyPath}`,
          historyPath,
          sprites: character?.sprites[0]
            ? [{ id: `${character.name}-0`, label: character.name, path: character.sprites[0].path }]
            : [],
          status: "idle",
        };
        emitChat();
        return delay(chat);
      },
      async resumeLast() {
        const character = config.characters.find((item) => templateSession?.selectedCharacters?.includes(item.name));
        const background = config.background_list.find((item) => item.name === templateSession?.background);
        const historyPath = templateSession?.historyPath || chat.historyPath || "./data/chat_history/preview.json";
        chat = {
          ...chat,
          backgroundPath: background?.sprites[0]?.path ?? chat.backgroundPath,
          characterName: character?.name ?? chat.characterName,
          dialogText: `已恢复上次启动：${historyPath}`,
          historyPath,
          sprites: character?.sprites[0]
            ? [{ id: `${character.name}-0`, label: character.name, path: character.sprites[0].path }]
            : chat.sprites,
          status: "idle",
        };
        emitChat();
        return delay(chat);
      },
      subscribe(listener) {
        chatListeners.add(listener);
        listener(clone(chat));
        return () => chatListeners.delete(listener);
      },
    },
    characters: {
      async delete(name) {
        config.characters = config.characters.filter((character) => character.name !== name);
      },
      async deleteMemory(name, memoryId) {
        const agentId = name || "user";
        const current = characterMemories.get(agentId) ?? { agentId, count: 0, memories: [] };
        const memories = current.memories.filter((memory) => memory.id !== memoryId);
        const next = { agentId, count: memories.length, memories };
        characterMemories.set(agentId, next);
        return delay(next);
      },
      async deleteSpriteVoice(name, spriteIndex) {
        const character = config.characters.find((item) => item.name === name);
        if (!character || !character.sprites[spriteIndex]) {
          throw new Error("立绘不存在。");
        }
        character.sprites[spriteIndex] = {
          ...character.sprites[spriteIndex],
          voice_path: "",
          voice_text: "",
        };
        return delay(character);
      },
      async deleteAllSprites(name) {
        const character = config.characters.find((item) => item.name === name);
        if (!character) {
          throw new Error(`角色不存在：${name}`);
        }
        character.sprites = [];
        character.emotion_tags = "";
        return delay(character);
      },
      async deleteSprite(name, spriteIndex) {
        const character = config.characters.find((item) => item.name === name);
        if (!character || !character.sprites[spriteIndex]) {
          throw new Error("立绘不存在。");
        }
        character.sprites = character.sprites.filter((_, index) => index !== spriteIndex);
        const tags = character.emotion_tags
          .split(/\r?\n/)
          .filter(Boolean)
          .filter((_, index) => index !== spriteIndex)
          .map((line, index) => `立绘 ${index + 1}：${line.split(/：|:/).slice(1).join("：")}`)
          .join("\n");
        character.emotion_tags = tags ? `${tags}\n` : "";
        return delay(character);
      },
      export: (name) => delay(`./data/export/${name}.char`),
      async generateSetting(input) {
        return delay({
          characterSetting: `${input.name || "角色"}的背景信息：\n1. 浏览器预览生成的设定。\n\n语言习惯：\n1. 温和且简洁。`,
          message: "输出成功",
        });
      },
      import: async (items) => {
        const imported = items.map<Character>((item, index) => {
          const label = item instanceof File ? item.name : item.split("/").pop() || `character-${index + 1}`;
          return {
            character_setting: "导入预览角色",
            color: DEFAULT_CHARACTER_COLOR,
            emotion_tags: "",
            name: `Imported ${index + 1}`,
            pronunciation_map: {},
            speech_speed: 1,
            speech_volume: 1,
            sprite_prefix: label.replace(/\W+/g, "_") || "imported",
            sprite_scale: 1,
            sprites: [],
          };
        });
        config.characters.push(...imported);
        return delay(imported);
      },
      list: () => delay(config.characters),
      async listMemories(name) {
        const agentId = name || "user";
        const existing = characterMemories.get(agentId) ?? {
          agentId,
          count: 1,
          memories: [{ id: `${agentId}-preview`, memory: "浏览器预览记忆。" }],
        };
        characterMemories.set(agentId, existing);
        return delay(existing);
      },
      async remember(name, content) {
        const agentId = name || "user";
        const current = characterMemories.get(agentId) ?? { agentId, count: 0, memories: [] };
        const memories = [...current.memories, { id: `${agentId}-${Date.now()}`, memory: content }];
        const next = { agentId, count: memories.length, memories };
        characterMemories.set(agentId, next);
        return delay(next);
      },
      async save(character, originalName) {
        const index = originalName
          ? config.characters.findIndex((item) => item.name === originalName)
          : config.characters.findIndex((item) => item.name === character.name);
        const duplicateIndex = config.characters.findIndex(
          (item, itemIndex) => item.name === character.name && itemIndex !== index,
        );
        if (duplicateIndex >= 0) {
          throw new Error(`名称「${character.name}」已与其他角色重复！`);
        }
        const savedCharacter = {
          ...clone(character),
          color: character.color.trim() || DEFAULT_CHARACTER_COLOR,
          emotion_tags: index >= 0 ? config.characters[index].emotion_tags : "",
          gpt_model_path: character.gpt_model_path?.trim() || "",
          prompt_lang: character.prompt_lang?.trim() || "",
          prompt_text: character.prompt_text?.trim() || "",
          refer_audio_path: character.refer_audio_path?.trim() || "",
          sovits_model_path: character.sovits_model_path?.trim() || "",
          sprite_prefix: character.sprite_prefix.trim() || "temp",
          sprite_scale: index >= 0 ? config.characters[index].sprite_scale : 1,
          sprites: index >= 0 ? config.characters[index].sprites : [],
          character_setting: character.character_setting.trim(),
        };
        if (index >= 0) {
          config.characters[index] = savedCharacter;
        } else {
          config.characters.push(savedCharacter);
        }
        return delay(savedCharacter);
      },
      async saveEmotionTags(name, emotionTags) {
        if (!name) {
          throw new Error("请先选择或创建角色！");
        }
        if (!emotionTags) {
          throw new Error("请输入情绪标注！");
        }
        const character = config.characters.find((item) => item.name === name);
        if (!character) {
          throw new Error(`找不到角色: ${name}`);
        }
        character.emotion_tags = emotionTags;
        return delay(character);
      },
      async saveSpriteScale(name, scale) {
        const character = config.characters.find((item) => item.name === name);
        if (!character) {
          throw new Error(`角色不存在：${name}`);
        }
        character.sprite_scale = scale;
        return delay(character);
      },
      async saveSpriteVoiceText(name, spriteIndex, voiceText) {
        const character = config.characters.find((item) => item.name === name);
        if (!character || !character.sprites[spriteIndex]) {
          throw new Error("立绘不存在。");
        }
        character.sprites[spriteIndex] = { ...character.sprites[spriteIndex], voice_text: voiceText };
        return delay(character);
      },
      async translateFields(input) {
        return delay({
          characterSetting: input.characterSetting,
          emotionTags: input.emotionTags,
          name: input.name,
        });
      },
      async uploadSprites(input) {
        const character = config.characters.find((item) => item.name === input.name);
        if (!character) {
          throw new Error(`角色不存在：${input.name}`);
        }
        const start = character.sprites.length;
        const nextSprites = input.paths.map((path) => ({
          path: `data/sprite/${character.sprite_prefix}/${path.split(/[\\/]/).pop() ?? path}`,
        }));
        character.sprites = [...character.sprites, ...nextSprites];
        const extraTags = input.paths.map((_, index) => `立绘 ${start + index + 1}：`).join("\n");
        character.emotion_tags = `${input.emotionTags || character.emotion_tags || ""}${extraTags ? `${extraTags}\n` : ""}`;
        return delay(character);
      },
      async uploadSpriteVoice(input) {
        const character = config.characters.find((item) => item.name === input.name);
        if (!character || !character.sprites[input.spriteIndex]) {
          throw new Error("立绘不存在。");
        }
        character.sprites[input.spriteIndex] = {
          ...character.sprites[input.spriteIndex],
          voice_path: input.voicePath,
          voice_text: input.voiceText,
        };
        return delay(character);
      },
    },
    config: {
      async cancelTtsBundleDownload(taskId) {
        const now = Date.now();
        return delay({
          createdAt: now,
          error: "",
          id: taskId,
          kind: "tts-bundle",
          logs: [],
          message: "任务已取消，已清理下载内容。",
          phase: "cancelled",
          progress: null,
          result: null,
          status: "cancelled",
          title: "TTS 整合包下载",
          updatedAt: now,
        });
      },
      async downloadTtsBundle(input, options) {
        const taskId = `preview-tts-${Date.now()}`;
        previewTask(
          taskId,
          { message: "正在下载 TTS 整合包。", phase: "download", progress: 0.35, status: "running" },
          options,
        );
        await delay(null, 160);
        previewTask(
          taskId,
          { message: "正在解压整合包。", phase: "extract", progress: 0.82, status: "running" },
          options,
        );
        await delay(null, 160);
        const result = {
          path: `data/tts_bundles/installed/${input.kind}`,
          provider: input.kind === "genie" ? "genie-tts" : "gpt-sovits",
        } as const;
        previewTask(
          taskId,
          { message: "TTS 整合包已就绪。", phase: "completed", progress: 1, result, status: "succeeded" },
          options,
        );
        return delay(result);
      },
      fetchLlmModels: async () => {
        throw new Error(
          "当前页面未连接 Shinsekai Python bridge，无法获取真实模型列表。请使用 start-react 启动，或为 Vite 设置 VITE_SHINSEKAI_API_BASE。",
        );
      },
      testLlmConnection: async () => {
        throw new Error(
          "当前页面未连接 Shinsekai Python bridge，无法进行真实 LLM 连通检测。请使用 start-react 启动，或为 Vite 设置 VITE_SHINSEKAI_API_BASE。",
        );
      },
      get: () => delay(config),
      getTtsBundleRecommendation: () =>
        delay({
          gpus: [{ device: "NVIDIA GeForce RTX 4070", vendor: "NVIDIA", vram_gb: 12 }],
          kind: "gptso",
          platform: "Browser preview",
        }),
      async saveApi(apiConfig) {
        config.api_config = clone(apiConfig);
        return delay(config.api_config);
      },
      async saveSystem(systemConfig) {
        config.system_config = clone(systemConfig);
        return delay(config.system_config);
      },
    },
    files: {
      browse(options) {
        return delay(previewFileBrowser(options?.path));
      },
      fileUrl(path) {
        return path;
      },
      thumbnailBatch(paths, _options) {
        return delay(Object.fromEntries(paths.filter(Boolean).map((path) => [path, path])));
      },
      thumbnailUrl(path) {
        return path;
      },
      async openExternal(url) {
        window.open(url, "_blank", "noopener,noreferrer");
      },
    },
    logs: {
      exportDiagnostics: () =>
        delay({
          downloadUrl: "browser-preview://shinsekai-diagnostics.zip",
          path: "browser-preview://shinsekai-diagnostics.zip",
        }),
      getDefault: () => delay(previewLogSnapshot()),
      async import(items) {
        const first = items[0];
        if (first instanceof File) {
          const content = await first.text();
          return delay({
            content,
            modifiedAt: first.lastModified / 1000,
            name: first.name,
            path: first.name,
            size: first.size,
            truncated: false,
          });
        }
        return delay({
          ...previewLogSnapshot(),
          name:
            String(first || "preview.log")
              .split(/[\\/]/)
              .pop() || "preview.log",
          path: String(first || "browser-preview://preview.log"),
        });
      },
      list: () =>
        delay({
          files: [
            {
              app: "preview",
              modifiedAt: Date.now() / 1000,
              name: "preview.log",
              path: "browser-preview://preview.log",
              relativePath: "logs/preview/preview.log",
              size: previewLogSnapshot().size,
            },
          ],
        }),
    },
    runtime: {
      installMissingDependency: (input) =>
        delay({
          message: `Preview installed ${input.moduleName}`,
          moduleName: input.moduleName,
          packageName: input.moduleName,
          pipCode: 0,
          pipOutput: "",
        }),
    },
    musicCover: {
      async run(input, options) {
        const taskId = `preview-music-cover-${Date.now()}`;
        previewTask<MusicCoverRunResult>(
          taskId,
          {
            kind: "music-cover",
            message: "正在执行翻唱流水线。",
            phase: "run",
            progress: 0.45,
            status: "running",
            title: "音乐翻唱流水线",
          },
          options,
        );
        await delay(null, 180);
        const result = {
          audioPath: `${config.system_config.music_cover_work_dir || "./data/music_cover"}/preview/final_mix.wav`,
          log: [
            `source=${input.source}`,
            `query=${input.query || "(empty)"}`,
            `pick_index=${input.pickIndex}`,
            `skip_rvc=${input.skipRvc}`,
            "浏览器预览模式未执行真实下载、分离或 RVC。",
          ].join("\n"),
        };
        previewTask<MusicCoverRunResult>(
          taskId,
          {
            kind: "music-cover",
            message: "翻唱流水线预览完成。",
            phase: "completed",
            progress: 1,
            result,
            status: "succeeded",
            title: "音乐翻唱流水线",
          },
          options,
        );
        return delay(result);
      },
      async saveConfig(input) {
        config.system_config = {
          ...config.system_config,
          ...input,
          music_cover_ffmpeg_exe: input.music_cover_ffmpeg_exe || "",
          music_cover_rvc_cmd_template: input.music_cover_rvc_cmd_template || "",
          music_cover_rvc_device: input.music_cover_rvc_device || "cuda:0",
          music_cover_rvc_f0_method: input.music_cover_rvc_f0_method || "rmvpe",
          music_cover_rvc_index_path: input.music_cover_rvc_index_path || "",
          music_cover_rvc_model_path: input.music_cover_rvc_model_path || "",
          music_cover_rvc_model_version: input.music_cover_rvc_model_version || "v2",
          music_cover_uvr_cmd_template: input.music_cover_uvr_cmd_template || "",
          music_cover_work_dir: input.music_cover_work_dir || "./data/music_cover",
          music_cover_yt_dlp_exe: input.music_cover_yt_dlp_exe || "",
        };
        return delay({
          message: "音乐翻唱配置已保存。",
          systemConfig: config.system_config,
        });
      },
      search: (input) =>
        delay({
          log: [`source=${input.source}`, `query=${input.query || "(empty)"}`, "1. Preview result - sample song"].join(
            "\n",
          ),
        }),
    },
    plugins: {
      async appUpdateRun(input, options) {
        const taskId = `preview-app-update-${Date.now()}`;
        previewTask(
          taskId,
          { message: "正在下载源码归档。", phase: "download", progress: 0.35, status: "running" },
          options,
        );
        await delay(null, 160);
        previewTask(
          taskId,
          { message: "正在合并到程序目录。", phase: "merge", progress: 0.72, status: "running" },
          options,
        );
        await delay(null, 160);
        const result = {
          message: `已模拟更新到 ${input.refKind === "tag" ? input.tagName || "tag" : input.refKind}。`,
          pipCode: "app_update_skip_pip",
          version: "preview",
        };
        previewTask(
          taskId,
          { message: result.message, phase: "completed", progress: 1, result, status: "succeeded" },
          options,
        );
        return delay(result);
      },
      appUpdateInfo: () => delay({ repo: "RachelForster/Shinsekai", version: "preview" }),
      appUpdateTags: () => delay(["v1.0.0", "v0.9.0"]),
      catalog: () => delay(pluginCatalog),
      getUi(id) {
        const plugin = plugins.find((item) => item.id === id || item.entry === id);
        if (!plugin) {
          return Promise.reject(new Error(`插件不存在：${id}`));
        }
        const settingsPages: PluginUIPage[] = plugin.settingsPages.map((title, index) => ({
          id: `settings-${index}`,
          kind: "settings",
          order: index,
          pluginId: plugin.id,
          pluginVersion: plugin.version,
          title,
          unavailableReason: "浏览器预览没有真实插件设置 schema。",
        }));
        const toolsPages: PluginUIPage[] = plugin.toolsTabs.map((title, index) => ({
          id: `tools-${index}`,
          kind: "tools",
          order: index + settingsPages.length,
          pluginId: plugin.id,
          pluginVersion: plugin.version,
          title,
          unavailableReason: "浏览器预览没有真实插件工具 schema。",
        }));
        return delay({ pages: [...settingsPages, ...toolsPages], plugin });
      },
      async install(input, options) {
        const id = typeof input === "string" ? input : input.source;
        const taskId = `preview-${Date.now()}`;
        previewTask(
          taskId,
          { message: "正在下载插件清单。", phase: "download", progress: 0.25, status: "running" },
          options,
        );
        await delay(null, 180);
        previewTask(taskId, { message: "正在安装依赖。", phase: "pip", progress: 0.72, status: "running" }, options);
        await delay(null, 220);
        const plugin: PluginManifest = {
          author: "Preview",
          description: "浏览器预览安装的插件。",
          directory: "plugins/preview",
          enabled: true,
          entry: id,
          id,
          loaded: true,
          permissions: ["settings"],
          settingsPages: ["预览设置"],
          slots: ["settings-extension"],
          title: id,
          toolsTabs: [],
          version: "preview",
        };
        plugins = [...plugins, plugin];
        pluginCatalog = pluginCatalog.map((item) =>
          item.repo === id || item.entry === id ? { ...item, downloaded: true, installed: true } : item,
        );
        previewTask(
          taskId,
          {
            message: "插件已安装。",
            phase: "completed",
            progress: 1,
            result: plugin,
            status: "succeeded",
          },
          options,
        );
        return delay(plugin, 400);
      },
      list: () => delay(plugins),
      repoTags: () => delay(["v1.0.0", "v0.9.0"]),
      scanLocal(input) {
        const baseName = input.path.split(/[\\/]/).filter(Boolean).pop() || "preview-plugin";
        return delay({
          author: "Shinsekai Contributors",
          desc: "从本地插件目录生成的示例提交信息。",
          display_name: baseName.replace(/[-_]+/g, " "),
          entry: `plugins.${baseName.replace(/[^A-Za-z0-9_]/g, "_")}.plugin:PreviewPlugin`,
          logo: "logo.png",
          path: input.path,
          repo: `https://github.com/shinsekai/${baseName}`,
          requirements: "",
          social_link: "https://github.com/shinsekai",
          tags: ["preview"],
          warnings: ["浏览器预览使用示例元数据，不会读取真实本地文件。"],
        });
      },
      validateSubmission(input) {
        const errors = previewPluginSubmissionErrors(input);
        const submission = normalizePreviewPluginSubmission(input);
        return delay({
          errors,
          json: errors.length ? undefined : previewPluginSubmissionJson(submission),
          ok: errors.length === 0,
          submission: errors.length ? undefined : submission,
        });
      },
      buildSubmissionIssueUrl(input) {
        const errors = previewPluginSubmissionErrors(input);
        if (errors.length) {
          return Promise.reject(new Error(errors.join("; ")));
        }
        const submission = normalizePreviewPluginSubmission(input);
        return delay({
          issueUrl: previewPluginIssueUrl(submission),
          json: previewPluginSubmissionJson(submission),
          submission,
          submitUrl: PREVIEW_PLUGIN_SUBMIT_URL,
        });
      },
      copySubmissionJson(input) {
        const errors = previewPluginSubmissionErrors(input);
        if (errors.length) {
          return Promise.reject(new Error(errors.join("; ")));
        }
        const submission = normalizePreviewPluginSubmission(input);
        const json = previewPluginSubmissionJson(submission);
        if (navigator.clipboard?.writeText) {
          void navigator.clipboard.writeText(json);
        }
        return delay({
          clipboardText: json,
          json,
          message: "Preview plugin submission copied.",
          submission,
        });
      },
      runUiAction(id, pageId, actionId, values) {
        const plugin = plugins.find((item) => item.id === id || item.entry === id);
        if (!plugin) {
          return Promise.reject(new Error(`插件不存在：${id}`));
        }
        return delay({
          message: `操作 ${actionId} 已完成。`,
          page: {
            id: pageId,
            kind: "settings",
            order: 0,
            pluginId: plugin.id,
            pluginVersion: plugin.version,
            schema: [],
            title: pageId,
            values,
          } satisfies PluginUIPage,
          plugin,
          result: {} as Record<string, unknown>,
        });
      },
      saveUiConfig(id, pageId, values) {
        const plugin = plugins.find((item) => item.id === id || item.entry === id);
        if (!plugin) {
          return Promise.reject(new Error(`插件不存在：${id}`));
        }
        return delay({
          message: "插件设置已保存。",
          page: {
            id: pageId,
            kind: "settings",
            order: 0,
            pluginId: plugin.id,
            pluginVersion: plugin.version,
            schema: [],
            title: pageId,
            values,
          } satisfies PluginUIPage,
          plugin,
        });
      },
      async setEnabled(id, enabled) {
        plugins = plugins.map((plugin) => (plugin.id === id || plugin.entry === id ? { ...plugin, enabled } : plugin));
        const plugin = plugins.find((item) => item.id === id || item.entry === id);
        if (!plugin) {
          throw new Error(`插件不存在：${id}`);
        }
        return delay(plugin);
      },
      async uninstall(id) {
        const plugin = plugins.find((item) => item.id === id || item.entry === id);
        if (!plugin) {
          throw new Error(`插件不存在：${id}`);
        }
        plugins = plugins.filter((item) => item.id !== id && item.entry !== id);
        pluginCatalog = pluginCatalog.map((item) =>
          item.entry === id || item.entry === plugin.entry ? { ...item, downloaded: false, installed: false } : item,
        );
        return delay({ message: `${plugin.title} 已卸载。` });
      },
    },
    mcp: {
      getConfig: () => delay(mcpConfig),
      openConfigFile: () => delay(mcpConfig.path ?? "data/config/mcp.yaml"),
      async previewTools(_config, options) {
        const taskId = `mcp-preview-${Date.now()}`;
        previewTask(
          taskId,
          { kind: "mcp-preview", message: "正在连接 MCP 服务。", phase: "probe", progress: 0.4, status: "running" },
          options,
        );
        await delay(null, 220);
        previewTask(
          taskId,
          {
            kind: "mcp-preview",
            message: "工具列表已刷新。",
            phase: "completed",
            progress: 1,
            result: sampleMcpTools,
            status: "succeeded",
          },
          options,
        );
        return delay(sampleMcpTools);
      },
      async saveAndApply(nextConfig, options) {
        const taskId = `mcp-apply-${Date.now()}`;
        previewTask(
          taskId,
          { kind: "mcp-apply", message: "正在写入 MCP 配置。", phase: "write", progress: 0.45, status: "running" },
          options,
        );
        await delay(null, 180);
        mcpConfig = clone({ ...nextConfig, path: nextConfig.path ?? mcpConfig.path });
        previewTask(
          taskId,
          {
            kind: "mcp-apply",
            message: "MCP 配置已应用。",
            phase: "completed",
            progress: 1,
            result: mcpConfig,
            status: "succeeded",
          },
          options,
        );
        return delay(mcpConfig);
      },
    },
    tasks: {
      get: async <TResult = unknown>(id: string): Promise<TaskSnapshot<TResult>> => ({
        createdAt: Date.now(),
        error: "",
        id,
        kind: "preview",
        logs: [],
        message: "浏览器预览没有持久后台任务。",
        phase: "completed",
        progress: 1,
        result: null,
        status: "succeeded",
        title: "预览任务",
        updatedAt: Date.now(),
      }),
    },
    templates: {
      async generate(input) {
        if (input.voiceLanguage) {
          config.system_config.voice_language = input.voiceLanguage;
        }
        const system = `角色：${input.characters.join("、")}\n背景：${input.backgroundName}\n请按剧情向 RPG 风格推进对白。`;
        const template: TemplateSummary = {
          content: [input.scenario, system].filter(Boolean).join("\n\n"),
          id: "",
          name: input.name || "新模板",
          path: "",
          scenario: input.scenario || "",
          system,
          updatedAt: "",
        };
        return delay(template, 600);
      },
      getSession: () => delay(templateSession),
      list: () => delay(templates),
      async save(template) {
        const id = template.id || `${template.name || "new"}.txt`;
        const saved = {
          ...template,
          id,
          path: template.path || `./data/character_templates/${id}`,
          updatedAt: template.updatedAt || "preview",
        };
        templates = templates.map((item) => (item.id === id ? clone(saved) : item));
        if (!templates.some((item) => item.id === id)) {
          templates.push(clone(saved));
        }
        return delay(saved);
      },
      async saveSession(session) {
        templateSession = clone(session);
        return delay(templateSession);
      },
    },
    tools: {
      async cropSprites(input, options) {
        const taskId = `tools-crop-${Date.now()}`;
        const result: BatchToolResult = {
          message: `成功裁剪，输出目录: ${input.outputDir || `${input.inputDir}/cropped_upper_${input.ratio}`}`,
          outputDir: input.outputDir || `${input.inputDir}/cropped_upper_${input.ratio}`,
        };
        previewTask(
          taskId,
          { kind: "tools-crop", message: "正在裁剪立绘。", phase: "crop", progress: 0.6, status: "running" },
          options,
        );
        await delay(null, 180);
        previewTask(
          taskId,
          { kind: "tools-crop", message: result.message, phase: "completed", progress: 1, result, status: "succeeded" },
          options,
        );
        return delay(result);
      },
      async generateSpritePrompts(input, options) {
        const taskId = `tools-prompts-${Date.now()}`;
        const result: SpritePromptResult = {
          prompts: Array.from(
            { length: input.count },
            (_, index) => `Make the character pose ${index + 1}, pure white background.`,
          ),
        };
        previewTask(
          taskId,
          { kind: "tools-prompts", message: "正在生成立绘提示词。", phase: "prompt", progress: 0.4, status: "running" },
          options,
        );
        await delay(null, 220);
        previewTask(
          taskId,
          {
            kind: "tools-prompts",
            message: "提示词已生成。",
            phase: "completed",
            progress: 1,
            result,
            status: "succeeded",
          },
          options,
        );
        return delay(result);
      },
      async generateSprites(input, options) {
        const taskId = `tools-sprites-${Date.now()}`;
        const outputDir = input.outputDir || `data/sprite/${input.characterName || "preview"}`;
        const result: SpriteGenerationResult = {
          files: input.prompts.map((_, index) => `${outputDir}/sprite_${String(index + 1).padStart(3, "0")}.png`),
          message: `已生成 ${input.prompts.length} 张（输出目录: ${outputDir}）`,
          outputDir,
        };
        previewTask(
          taskId,
          { kind: "tools-sprites", message: "正在生成立绘。", phase: "generate", progress: 0.35, status: "running" },
          options,
        );
        await delay(null, 260);
        previewTask(
          taskId,
          {
            kind: "tools-sprites",
            message: result.message,
            phase: "completed",
            progress: 1,
            result,
            status: "succeeded",
          },
          options,
        );
        return delay(result);
      },
      async removeSpriteBackground(input, options) {
        const taskId = `tools-rmbg-${Date.now()}`;
        const outputDir = input.outputDir || `${input.inputDir}/removed_backgrounds`;
        const result: BatchToolResult = {
          message: `成功处理: 3，失败: 0，输出到目录： ${outputDir}`,
          outputDir,
        };
        previewTask(
          taskId,
          {
            kind: "tools-rmbg",
            message: "正在批量抠出立绘。",
            phase: "remove-background",
            progress: 0.5,
            status: "running",
          },
          options,
        );
        await delay(null, 220);
        previewTask(
          taskId,
          { kind: "tools-rmbg", message: result.message, phase: "completed", progress: 1, result, status: "succeeded" },
          options,
        );
        return delay(result);
      },
    },
  };
}
