import { numberedTags, tagContents } from "../../assets/assetText";
import { DEFAULT_PLAYER_OPTIONS } from "../../playerCharacterOptions";
import { PlatformRequestError } from "../errors";
import { type BrowserPreviewContext, clone, delay, previewSpriteUrl, previewTask } from "./previewContext";
import type { FilesPlatform, LogSnapshot, LogsPlatform, TaskSnapshot, TasksPlatform } from "./taskTypes";
import type {
  Background,
  BackgroundsPlatform,
  BatchToolResult,
  Effect,
  EffectsPlatform,
  SpriteGenerationResult,
  SpritePromptResult,
  TemplatesPlatform,
  ToolsPlatform,
} from "./workspaceTypes";

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

export function createBackgroundsPreviewPlatform(ctx: BrowserPreviewContext): BackgroundsPlatform {
  const { config } = ctx;

  return {
    async autoLabelImages(name) {
      const background = config.background_list.find((item) => item.name === name);
      if (!background) {
        throw new Error(`Background not found: ${name}`);
      }
      const tags = tagContents(background.bg_tags, background.sprites.length);
      let annotatedCount = 0;
      tags.forEach((tag, index) => {
        if (!tag.trim()) {
          tags[index] = "室内，柔和光线，安静氛围";
          annotatedCount += 1;
        }
      });
      background.bg_tags = numberedTags("场景", tags);
      return delay({
        annotatedCount,
        failedCount: 0,
        failures: [],
        name,
        scope: "background" as const,
        skippedCount: background.sprites.length - annotatedCount,
        tags: background.bg_tags,
        totalCount: background.sprites.length,
      });
    },
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
  };
}

export function createEffectsPreviewPlatform(ctx: BrowserPreviewContext): EffectsPlatform {
  const { config } = ctx;

  return {
    async delete(name) {
      config.effect_list = config.effect_list.filter((effect) => effect.name !== name);
    },
    async deleteAllAudio(name) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect) {
        throw new Error("特效方案不存在。");
      }
      effect.audio_list = [];
      effect.audio_tags = "";
      return delay(effect);
    },
    async deleteAudio(name, index) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect || index < 0 || index >= effect.audio_list.length) {
        throw new Error("特效音频不存在。");
      }
      const tags = tagContents(effect.audio_tags, effect.audio_list.length, true);
      effect.audio_list = effect.audio_list.filter((_, itemIndex) => itemIndex !== index);
      effect.audio_tags = numberedTags(
        "特效",
        tags.filter((_, itemIndex) => itemIndex !== index),
      );
      return delay(effect);
    },
    async deleteImage(name, index) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect || index < 0 || index >= effect.image_list.length) {
        throw new Error("特效图片不存在。");
      }
      const tags = tagContents(effect.image_tags, effect.image_list.length, true);
      effect.image_list = effect.image_list.filter((_, itemIndex) => itemIndex !== index);
      effect.image_audio_list = effect.image_audio_list.filter((_, itemIndex) => itemIndex !== index);
      effect.image_tags = numberedTags(
        "图片",
        tags.filter((_, itemIndex) => itemIndex !== index),
      );
      return delay(effect);
    },
    export: (name) => delay(`./data/export/${name}.ef`),
    import: async (items) => {
      const imported = items.map<Effect>((item, index) => {
        const label = item instanceof File ? item.name : item.split("/").pop() || `effect-${index + 1}`;
        return {
          name: label.replace(/\.ef$/i, ""),
          color: "#5b8def",
          prompt_text: "",
          audio_list: [],
          audio_tags: "",
          image_list: [],
          image_tags: "",
          image_audio_list: [],
        };
      });
      config.effect_list = [...config.effect_list, ...imported];
      return delay(imported);
    },
    list: () => delay(clone(config.effect_list)),
    async save(effect, originalName) {
      if (originalName && originalName !== effect.name) {
        const existing = config.effect_list.find((item) => item.name === originalName);
        if (existing) {
          Object.assign(existing, effect);
          return delay(clone(existing));
        }
      }
      const existing = config.effect_list.find((item) => item.name === effect.name);
      if (existing) {
        Object.assign(existing, effect);
        return delay(clone(existing));
      }
      config.effect_list = [...config.effect_list, clone(effect)];
      return delay(clone(effect));
    },
    async saveAudioTags(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) {
        throw new Error("特效方案不存在。");
      }
      effect.audio_tags = input.audioTags;
      return delay(effect);
    },
    async saveImageTags(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error("特效方案不存在。");
      effect.image_tags = input.imageTags;
      return delay(effect);
    },
    async uploadAudio(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) {
        throw new Error("特效方案不存在。");
      }
      const tags = tagContents(input.audioTags || effect.audio_tags, effect.audio_list.length, true);
      effect.audio_list = [...effect.audio_list, ...input.paths];
      effect.audio_tags = numberedTags("特效", [...tags, ...input.paths.map(() => "")]);
      return delay(effect);
    },
    async uploadImages(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error("特效方案不存在。");
      const tags = tagContents(input.imageTags || effect.image_tags, effect.image_list.length, true);
      effect.image_list = [...effect.image_list, ...input.paths];
      effect.image_audio_list = [...effect.image_audio_list, ...input.paths.map(() => "")];
      effect.image_tags = numberedTags("图片", [...tags, ...input.paths.map(() => "")]);
      return delay(effect);
    },
    async uploadImageAudio(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect || input.index < 0 || input.index >= effect.image_list.length) {
        throw new Error("特效图片不存在。");
      }
      effect.image_audio_list = [...effect.image_audio_list];
      while (effect.image_audio_list.length < effect.image_list.length) effect.image_audio_list.push("");
      effect.image_audio_list[input.index] = input.path;
      return delay(effect);
    },
  };
}

export function createFilesPreviewPlatform(ctx: BrowserPreviewContext): FilesPlatform {
  return {
    async openT2iWorkflowFolder() {
      throw new PlatformRequestError("Bundled workflows require the local app.", 501, "local_app_required");
    },
    modelUrl: () => {
      throw new Error("Models require the local bridge");
    },
    browse(options) {
      return delay(previewFileBrowser(options?.path));
    },
    fileUrl(path) {
      if (path === "/assets/present_example.png") return previewSpriteUrl;
      return ctx.resolvePreviewThemeAssetUrl(path);
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
  };
}

export function createLogsPreviewPlatform(): LogsPlatform {
  return {
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
  };
}

export function createTasksPreviewPlatform(): TasksPlatform {
  return {
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
  };
}

export function createTemplatesPreviewPlatform(ctx: BrowserPreviewContext): TemplatesPlatform {
  const { config, getTemplates, getTemplateSession, setTemplates, setTemplateSession } = ctx;

  return {
    async generate(input) {
      if (input.voiceLanguage) {
        config.system_config.voice_language = input.voiceLanguage;
      }
      const scenario =
        input.scenario ||
        `你需要模拟一个RPG剧情对话系统，出场人物有：${input.characters.join("、")} 以及其他相关人物，请根据剧情调度人物。`;
      const system = "";
      const template = {
        content: [scenario, system].filter(Boolean).join("\n\n"),
        id: "",
        name: input.name || "新模板",
        path: "",
        resolvedCharacters: [...input.characters],
        allowPlayerDialogue: input.allowPlayerDialogue ?? DEFAULT_PLAYER_OPTIONS.allowPlayerDialogue,
        scenario,
        system,
        updatedAt: "",
      };
      return delay(template, 600);
    },
    getSession: () => delay(getTemplateSession()),
    list: () => delay(getTemplates()),
    async save(template) {
      const id = template.id || `${template.name || "new"}.txt`;
      const saved = {
        ...template,
        id,
        path: template.path || `./data/character_templates/${id}`,
        updatedAt: template.updatedAt || "preview",
      };
      const next = getTemplates().map((item) => (item.id === id ? clone(saved) : item));
      if (!next.some((item) => item.id === id)) {
        next.push(clone(saved));
      }
      setTemplates(next);
      return delay(saved);
    },
    async saveSession(session) {
      const next = clone(session);
      setTemplateSession(next);
      return delay(next);
    },
  };
}

export function createToolsPreviewPlatform(): ToolsPlatform {
  return {
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
  };
}
