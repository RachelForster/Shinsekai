import { numberedTags, tagContents } from "../../assets/assetText";
import {
  TAG_PREFIX_AMBIENT,
  TAG_PREFIX_EFFECT,
  TAG_PREFIX_IMAGE,
  TAG_PREFIX_MUSIC,
  TAG_PREFIX_SCENE,
} from "../../constants";
import { translateRuntimeMessage } from "../../i18n/runtimeLanguage";
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
  const tr = (key: Parameters<typeof translateRuntimeMessage>[0], values?: Record<string, string | number>) =>
    translateRuntimeMessage(key, values, config.system_config.ui_language);

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
          tags[index] = tr("plat.preview.bg.defaultTag");
          annotatedCount += 1;
        }
      });
      background.bg_tags = numberedTags(TAG_PREFIX_SCENE, tags);
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
        throw new Error(tr("plat.preview.bg.notFound"));
      }
      background.bgm_list = [];
      background.bgm_tags = "";
      return delay(background);
    },
    async deleteAllImages(name) {
      const background = config.background_list.find((item) => item.name === name);
      if (!background) {
        throw new Error(tr("plat.preview.bg.notFound"));
      }
      background.sprites = [];
      background.bg_tags = "";
      return delay(background);
    },
    async deleteBgm(name, index) {
      const background = config.background_list.find((item) => item.name === name);
      if (!background || !background.bgm_list[index]) {
        throw new Error(tr("plat.preview.bg.musicNotFound"));
      }
      background.bgm_list = background.bgm_list.filter((_, itemIndex) => itemIndex !== index);
      background.bgm_tags = background.bgm_tags
        .split(/\r?\n/)
        .filter(Boolean)
        .filter((_, itemIndex) => itemIndex !== index)
        .map((line, itemIndex) => `${TAG_PREFIX_MUSIC} ${itemIndex + 1}：${line.split(/：|:/).slice(1).join("：")}`)
        .join("\n");
      if (background.bgm_tags) {
        background.bgm_tags += "\n";
      }
      return delay(background);
    },
    async deleteImage(name, index) {
      const background = config.background_list.find((item) => item.name === name);
      if (!background || !background.sprites[index]) {
        throw new Error(tr("plat.preview.bg.imageNotFound"));
      }
      background.sprites = background.sprites.filter((_, itemIndex) => itemIndex !== index);
      background.bg_tags = background.bg_tags
        .split(/\r?\n/)
        .filter(Boolean)
        .filter((_, itemIndex) => itemIndex !== index)
        .map((line, itemIndex) => `${TAG_PREFIX_SCENE} ${itemIndex + 1}：${line.split(/：|:/).slice(1).join("：")}`)
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
          bg_tags: tr("plat.preview.bg.importedTag"),
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
      const idIndex = background.id ? config.background_list.findIndex((item) => item.id === background.id) : -1;
      const index =
        idIndex >= 0
          ? idIndex
          : config.background_list.findIndex((item) => item.name === (originalName || background.name));
      if (index >= 0) {
        config.background_list[index] = {
          ...config.background_list[index],
          ...(background.bg_tags !== undefined ? { bg_tags: background.bg_tags } : {}),
          ...(background.bgm_tags !== undefined ? { bgm_tags: background.bgm_tags } : {}),
          name: background.name,
          sprite_prefix: background.sprite_prefix || "temp",
        };
      } else {
        config.background_list.push({
          ...(background.id ? { id: background.id } : {}),
          bg_tags: background.bg_tags ?? "",
          bgm_list: background.bgm_list ?? [],
          bgm_tags: background.bgm_tags ?? "",
          name: background.name,
          sprite_prefix: background.sprite_prefix || "temp",
          sprites: background.sprites ?? [],
        });
      }
      return delay(
        (background.id ? config.background_list.find((item) => item.id === background.id) : undefined) ??
          config.background_list.find((item) => item.name === background.name) ??
          background,
      );
    },
    async saveBgmTags(input) {
      const background = config.background_list.find((item) => item.name === input.name);
      if (!background) {
        throw new Error(tr("plat.preview.bg.notFound"));
      }
      background.bgm_tags = input.bgmTags;
      return delay(background);
    },
    async saveImageTags(input) {
      const background = config.background_list.find((item) => item.name === input.name);
      if (!background) {
        throw new Error(tr("plat.preview.bg.notFound"));
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
        throw new Error(tr("plat.preview.bg.notFound"));
      }
      background.bgm_list = [...background.bgm_list, ...input.paths];
      background.bgm_tags = `${input.bgmTags || ""}${input.paths.map((_, index) => `${TAG_PREFIX_MUSIC} ${background.bgm_list.length - input.paths.length + index + 1}：`).join("\n")}\n`;
      return delay(background);
    },
    async uploadImages(input) {
      const background = config.background_list.find((item) => item.name === input.name);
      if (!background) {
        throw new Error(tr("plat.preview.bg.notFound"));
      }
      background.sprites = [...background.sprites, ...input.paths.map((path) => ({ path }))];
      background.bg_tags = `${input.bgTags || ""}${input.paths.map((_, index) => `${TAG_PREFIX_SCENE} ${background.sprites.length - input.paths.length + index + 1}：`).join("\n")}\n`;
      return delay(background);
    },
  };
}

export function createEffectsPreviewPlatform(ctx: BrowserPreviewContext): EffectsPlatform {
  const { config } = ctx;
  const tr = (key: Parameters<typeof translateRuntimeMessage>[0], values?: Record<string, string | number>) =>
    translateRuntimeMessage(key, values, config.system_config.ui_language);

  return {
    async delete(name) {
      config.effect_list = config.effect_list.filter((effect) => effect.name !== name);
    },
    async deleteAllAudio(name) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect) {
        throw new Error(tr("plat.preview.effect.notFound"));
      }
      effect.audio_list = [];
      effect.audio_tags = "";
      return delay(effect);
    },
    async deleteAudio(name, index) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect || index < 0 || index >= effect.audio_list.length) {
        throw new Error(tr("plat.preview.effect.audioNotFound"));
      }
      const tags = tagContents(effect.audio_tags, effect.audio_list.length, true);
      effect.audio_list = effect.audio_list.filter((_, itemIndex) => itemIndex !== index);
      effect.audio_tags = numberedTags(
        TAG_PREFIX_EFFECT,
        tags.filter((_, itemIndex) => itemIndex !== index),
      );
      return delay(effect);
    },
    async deleteImage(name, index) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect || index < 0 || index >= effect.image_list.length) {
        throw new Error(tr("plat.preview.effect.imageNotFound"));
      }
      const tags = tagContents(effect.image_tags, effect.image_list.length, true);
      effect.image_list = effect.image_list.filter((_, itemIndex) => itemIndex !== index);
      effect.image_audio_list = effect.image_audio_list.filter((_, itemIndex) => itemIndex !== index);
      effect.image_tags = numberedTags(
        TAG_PREFIX_IMAGE,
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
          ambient_list: [],
          ambient_tags: "",
          ambient_audio_list: [],
          ambient_layers: [],
        };
      });
      config.effect_list = [...config.effect_list, ...imported];
      return delay(imported);
    },
    list: () => delay(clone(config.effect_list)),
    async save(effect, originalName) {
      const mergeExistingEffect = (target: Effect) => {
        const layers =
          Array.isArray(effect.ambient_layers) && effect.ambient_layers.length === target.ambient_list.length
            ? effect.ambient_layers
            : target.ambient_layers;
        Object.assign(target, effect, {
          ...(target.id ? { id: target.id } : {}),
          audio_list: target.audio_list,
          image_audio_list: target.image_audio_list,
          image_list: target.image_list,
          ambient_list: target.ambient_list,
          ambient_audio_list: target.ambient_audio_list,
          ambient_layers: layers,
        });
        return delay(clone(target));
      };
      const idMatch = effect.id ? config.effect_list.find((item) => item.id === effect.id) : undefined;
      if (idMatch) {
        return mergeExistingEffect(idMatch);
      }
      if (originalName && originalName !== effect.name) {
        const existing = config.effect_list.find((item) => item.name === originalName);
        if (existing) {
          return mergeExistingEffect(existing);
        }
      }
      const existing = config.effect_list.find((item) => item.name === effect.name);
      if (existing) {
        return mergeExistingEffect(existing);
      }
      config.effect_list = [...config.effect_list, clone(effect)];
      return delay(clone(effect));
    },
    async saveAudioTags(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) {
        throw new Error(tr("plat.preview.effect.notFound"));
      }
      effect.audio_tags = input.audioTags;
      return delay(effect);
    },
    async saveImageTags(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error(tr("plat.preview.effect.notFound"));
      effect.image_tags = input.imageTags;
      return delay(effect);
    },
    async uploadAudio(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) {
        throw new Error(tr("plat.preview.effect.notFound"));
      }
      const tags = tagContents(input.audioTags || effect.audio_tags, effect.audio_list.length, true);
      effect.audio_list = [...effect.audio_list, ...input.paths];
      effect.audio_tags = numberedTags(TAG_PREFIX_EFFECT, [...tags, ...input.paths.map(() => "")]);
      return delay(effect);
    },
    async uploadImages(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error(tr("plat.preview.effect.notFound"));
      const tags = tagContents(input.imageTags || effect.image_tags, effect.image_list.length, true);
      effect.image_list = [...effect.image_list, ...input.paths];
      effect.image_audio_list = [...effect.image_audio_list, ...input.paths.map(() => "")];
      effect.image_tags = numberedTags(TAG_PREFIX_IMAGE, [...tags, ...input.paths.map(() => "")]);
      return delay(effect);
    },
    async uploadImageAudio(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect || input.index < 0 || input.index >= effect.image_list.length) {
        throw new Error(tr("plat.preview.effect.imageNotFound"));
      }
      effect.image_audio_list = [...effect.image_audio_list];
      while (effect.image_audio_list.length < effect.image_list.length) effect.image_audio_list.push("");
      effect.image_audio_list[input.index] = input.path;
      return delay(effect);
    },
    async uploadAmbient(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error(tr("plat.preview.effect.notFound"));
      const tags = tagContents(input.ambientTags || effect.ambient_tags, effect.ambient_list.length, true);
      effect.ambient_list = [...effect.ambient_list, ...input.paths];
      effect.ambient_audio_list = [...effect.ambient_audio_list, ...input.paths.map(() => "")];
      effect.ambient_layers = [...effect.ambient_layers, ...input.paths.map(() => "back")];
      effect.ambient_tags = numberedTags(TAG_PREFIX_AMBIENT, [...tags, ...input.paths.map(() => "")]);
      return delay(effect);
    },
    async deleteAmbient(name, index) {
      const effect = config.effect_list.find((item) => item.name === name);
      if (!effect || index < 0 || index >= effect.ambient_list.length) {
        throw new Error(tr("plat.preview.effect.ambientNotFound"));
      }
      effect.ambient_list = effect.ambient_list.filter((_, itemIndex) => itemIndex !== index);
      effect.ambient_audio_list = effect.ambient_audio_list.filter((_, itemIndex) => itemIndex !== index);
      effect.ambient_layers = effect.ambient_layers.filter((_, itemIndex) => itemIndex !== index);
      const tags = tagContents(effect.ambient_tags, effect.ambient_list.length + 1, true);
      effect.ambient_tags = numberedTags(
        TAG_PREFIX_AMBIENT,
        tags.filter((_, itemIndex) => itemIndex !== index),
      );
      return delay(effect);
    },
    async saveAmbientTags(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error(tr("plat.preview.effect.notFound"));
      effect.ambient_tags = input.ambientTags;
      return delay(effect);
    },
    async saveAmbientLayers(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect) throw new Error(tr("plat.preview.effect.notFound"));
      effect.ambient_layers = effect.ambient_list.map((_, index) =>
        input.layers[index] === "front" ? "front" : "back",
      );
      return delay(effect);
    },
    async uploadAmbientAudio(input) {
      const effect = config.effect_list.find((item) => item.name === input.name);
      if (!effect || input.index < 0 || input.index >= effect.ambient_list.length) {
        throw new Error(tr("plat.preview.effect.ambientNotFound"));
      }
      effect.ambient_audio_list = [...effect.ambient_audio_list];
      while (effect.ambient_audio_list.length < effect.ambient_list.length) {
        effect.ambient_audio_list.push("");
      }
      effect.ambient_audio_list[input.index] = input.path;
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
      message: translateRuntimeMessage("plat.preview.task.noPersistentTasks"),
      phase: "completed",
      progress: 1,
      result: null,
      status: "succeeded",
      title: translateRuntimeMessage("plat.preview.task.title"),
      updatedAt: Date.now(),
    }),
  };
}

export function createTemplatesPreviewPlatform(ctx: BrowserPreviewContext): TemplatesPlatform {
  const {
    config,
    getTemplates,
    getTemplateSession,
    getUserPromptPresets,
    setTemplates,
    setTemplateSession,
    setUserPromptPresets,
  } = ctx;
  const tr = (key: Parameters<typeof translateRuntimeMessage>[0], values?: Record<string, string | number>) =>
    translateRuntimeMessage(key, values, config.system_config.ui_language);

  return {
    async generate(input) {
      if (input.voiceLanguage) {
        config.system_config.voice_language = input.voiceLanguage;
      }
      const scenario =
        input.scenario ||
        tr("plat.preview.template.defaultScenario", {
          characters: input.characters.join(tr("plat.preview.template.sep")),
        });
      const system = "";
      const template = {
        content: [scenario, system].filter(Boolean).join("\n\n"),
        id: "",
        name: input.name || tr("plat.preview.template.defaultName"),
        path: "",
        resolvedCharacters: [...input.characters],
        allowPlayerDialogue: input.allowPlayerDialogue ?? DEFAULT_PLAYER_OPTIONS.allowPlayerDialogue,
        scenario,
        system,
        updatedAt: "",
      };
      return delay(template, 600);
    },
    getPresets: () => delay(getUserPromptPresets()),
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
    async savePresets(library) {
      const next = clone(library);
      setUserPromptPresets(next);
      return delay(next);
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
      const outputDir = input.outputDir || `${input.inputDir}/cropped_upper_${input.ratio}`;
      const result: BatchToolResult = {
        message: translateRuntimeMessage("plat.preview.tools.cropDone", { dir: outputDir }),
        outputDir,
      };
      previewTask(
        taskId,
        {
          kind: "tools-crop",
          message: translateRuntimeMessage("plat.preview.tools.cropping"),
          phase: "crop",
          progress: 0.6,
          status: "running",
        },
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
        {
          kind: "tools-prompts",
          message: translateRuntimeMessage("plat.preview.tools.generatingPrompts"),
          phase: "prompt",
          progress: 0.4,
          status: "running",
        },
        options,
      );
      await delay(null, 220);
      previewTask(
        taskId,
        {
          kind: "tools-prompts",
          message: translateRuntimeMessage("plat.preview.tools.promptsGenerated"),
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
        message: translateRuntimeMessage("plat.preview.tools.generatedCount", {
          count: input.prompts.length,
          dir: outputDir,
        }),
        outputDir,
      };
      previewTask(
        taskId,
        {
          kind: "tools-sprites",
          message: translateRuntimeMessage("plat.preview.tools.generatingSprites"),
          phase: "generate",
          progress: 0.35,
          status: "running",
        },
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
        message: translateRuntimeMessage("plat.preview.tools.rmbgDone", { dir: outputDir }),
        outputDir,
      };
      previewTask(
        taskId,
        {
          kind: "tools-rmbg",
          message: translateRuntimeMessage("plat.preview.tools.removingBg"),
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
