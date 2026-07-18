import {
  sampleChatSnapshot,
  sampleConfig,
  sampleChatThemeManifests,
  sampleChatThemeSummaries,
  sampleMcpConfig,
  sampleMcpTools,
  samplePluginCatalog,
  samplePlugins,
  sampleChatTheme,
  sampleTemplates,
} from "./sampleData";
import { DEFAULT_CHARACTER_COLOR } from "../constants";
import { numberedTags, tagContents } from "../assets/assetText";
import { runtimeStatusFromSnapshot } from "./chatRuntimeStatus";
import type { ChatThemePayload } from "../theme/chatChromeTheme";
import { DEFAULT_CHAT_THEME_ID, type ChatThemeManifest, type ChatThemeSummary } from "../theme/chatTheme";
import type {
  BatchToolResult,
  Background,
  Character,
  CharacterMemoryImportPreview,
  CharacterMemoryImportResult,
  CharacterMemoryList,
  ChatConversationBranch,
  ChatHistoryEntry,
  ChatSnapshot,
  ChatStageEvent,
  Effect,
  LogSnapshot,
  MusicCoverRunResult,
  PluginCatalogItem,
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

const bundledChatThemeAssets = import.meta.glob<string>(
  "../../../../assets/chat_ui_themes/**/*.{gif,jpeg,jpg,mp3,ogg,otf,png,svg,ttf,wav,webp,woff,woff2}",
  { eager: true, import: "default", query: "?url" },
);
const bundledChatThemeRoot = "../../../../assets/chat_ui_themes/";
const builtinChatThemeAssetUrls: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(bundledChatThemeAssets).map(([path, url]) => [
    `data/chat_ui_themes/${path.slice(bundledChatThemeRoot.length)}`,
    url,
  ]),
);

function clone<T>(value: T): T {
  return structuredClone(value);
}

function delay<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(clone(value)), ms));
}

async function previewMemoryImport(items: File[]): Promise<CharacterMemoryImportPreview> {
  const files = await Promise.all(
    items.map(async (item) => {
      const name = item.name;
      let content = "";
      try {
        content = await item.text();
      } catch {
        content = "";
      }
      const dialogueCharacters = content.length || 3_600;
      const dialogueLineCount = content ? Math.max(1, content.split(/\r?\n/).filter((line) => line.trim()).length) : 40;
      const sourceTokens = Math.max(1, Math.ceil(dialogueCharacters / 4));
      return {
        chunkCount: Math.max(1, Math.ceil(sourceTokens / 2_500)),
        dialogueCharacters,
        dialogueLineCount,
        kind: name.toLowerCase().endsWith(".json") ? "json" : "txt",
        name,
        sourceTokens,
      };
    }),
  );
  const sourceTokens = files.reduce((sum, file) => sum + file.sourceTokens, 0);
  const chunkCount = files.reduce((sum, file) => sum + file.chunkCount, 0);
  const estimatedInputTokens = sourceTokens + chunkCount * 600;
  const estimatedOutputTokens = chunkCount * 350;
  return {
    chunkCount,
    dialogueCharacters: files.reduce((sum, file) => sum + file.dialogueCharacters, 0),
    dialogueLineCount: files.reduce((sum, file) => sum + file.dialogueLineCount, 0),
    estimatedInputTokens,
    estimatedOutputTokens,
    estimatedTotalTokens: estimatedInputTokens + estimatedOutputTokens,
    fileCount: files.length,
    files,
    sourceTokens,
    warnings: files.some((file) => file.kind === "json")
      ? ["JSON history will be converted to plain dialogue before extraction."]
      : [],
  };
}

function looksLikeLocalModelReference(value: string) {
  const normalized = value.replace(/\\/g, "/");
  const slashCount = normalized.split("/").length - 1;
  return (
    value.startsWith(".") ||
    value.startsWith("/") ||
    value.startsWith("\\") ||
    value.startsWith("~") ||
    value.endsWith("/") ||
    value.endsWith("\\") ||
    value.includes("\\") ||
    /^[A-Za-z]:[\\/]/.test(value) ||
    slashCount > 1
  );
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

function previewNormalizePluginKey(value: string | null | undefined) {
  return (value ?? "")
    .trim()
    .replace(/\.git$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function previewModuleToken(value: string | null | undefined) {
  const moduleName = (value ?? "").split(":", 1)[0] ?? "";
  const parts = moduleName.split(".").filter(Boolean);
  if (!parts.length) {
    return "";
  }
  if (parts.at(-1) === "plugin" && parts.length > 1) {
    return parts.at(-2) ?? "";
  }
  return parts.at(-1) ?? "";
}

function previewPluginDirectory(entry: string, fallback: string) {
  const token = previewModuleToken(entry) || previewNormalizePluginKey(fallback) || "preview";
  return `plugins/${token.replace(/[^A-Za-z0-9_]+/g, "_")}`;
}

function previewCatalogKeys(plugin: PluginCatalogItem) {
  return new Set(
    [plugin.id, plugin.name, plugin.displayName, plugin.repo, plugin.entry, previewModuleToken(plugin.entry)]
      .map(previewNormalizePluginKey)
      .filter(Boolean),
  );
}

function previewManifestKeys(plugin: PluginManifest) {
  return new Set(
    [
      plugin.id,
      plugin.title,
      plugin.entry,
      plugin.directory?.split(/[\\/]/).filter(Boolean).at(-1),
      plugin.install?.repo,
      plugin.install?.entry,
      previewModuleToken(plugin.entry),
    ]
      .map(previewNormalizePluginKey)
      .filter(Boolean),
  );
}

function previewCatalogForSource(source: string, catalogItems: PluginCatalogItem[]) {
  const sourceKey = previewNormalizePluginKey(source);
  return catalogItems.find((item) => previewCatalogKeys(item).has(sourceKey));
}

function previewUpsertPlugin(currentPlugins: PluginManifest[], plugin: PluginManifest, catalog?: PluginCatalogItem) {
  const keys = new Set([...previewManifestKeys(plugin), ...(catalog ? previewCatalogKeys(catalog) : [])]);
  let replaced = false;
  const nextPlugins = currentPlugins.map((item) => {
    for (const key of previewManifestKeys(item)) {
      if (keys.has(key)) {
        replaced = true;
        return plugin;
      }
    }
    return item;
  });
  if (!replaced) {
    return [...nextPlugins, plugin];
  }
  return nextPlugins;
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
  const lowestShinsekaiVersion = (input.lowest_shinsekai_version ?? "").trim();
  if (lowestShinsekaiVersion) {
    submission.lowest_shinsekai_version = lowestShinsekaiVersion;
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

function cloneHistoryEntries(entries: ChatHistoryEntry[] | undefined): ChatHistoryEntry[] {
  return (entries ?? []).map((entry) => ({ ...entry }));
}

function isPreviewRealtimeCommand(command: { type: string }) {
  return command.type !== "copy-history" && command.type !== "open-history";
}

function themeBlockQss(block?: {
  background?: string;
  borderColor?: string;
  borderRadius?: string;
  boxShadow?: string;
  color?: string;
}) {
  if (!block) {
    return "";
  }
  return [
    block.background ? `background-color: ${block.background}` : "",
    block.borderColor ? `border-color: ${block.borderColor}` : "",
    block.borderRadius ? `border-radius: ${block.borderRadius}` : "",
    block.boxShadow ? `box-shadow: ${block.boxShadow}` : "",
    block.color ? `color: ${block.color}` : "",
  ]
    .filter(Boolean)
    .join("; ");
}

function previewThemePayloadFromManifest(manifest: ChatThemeManifest): ChatThemePayload {
  return {
    raw: {
      busy_bar_label: {
        extra_qss: themeBlockQss(manifest.tokens.toolbar),
      },
      dialog_label: {
        extra_qss: themeBlockQss(manifest.tokens.dialog),
      },
      dialog_offset_y: manifest.tokens.dialog?.offsetY ?? 0,
      dialog_padding: manifest.tokens.dialog?.padding ?? 40,
      dialog_width_pct: manifest.tokens.dialog?.widthPct ?? 86,
      input_bar: {
        extra_qss: themeBlockQss(manifest.tokens.input),
      },
      option_row: {
        extra_qss: themeBlockQss(manifest.tokens.options),
        hover_extra_qss: themeBlockQss(manifest.tokens.options?.hover),
      },
      options_gap: manifest.tokens.options?.gap ?? 10,
      send_button: {
        extra_qss: themeBlockQss(manifest.tokens.send),
      },
    },
    themeColor: manifest.tokens.global?.themeColor ?? sampleChatTheme.themeColor,
  };
}

export function createBrowserPreviewPlatform(): ShinsekaiPlatform {
  const config = clone(sampleConfig);
  let templates = clone(sampleTemplates);
  let plugins = clone(samplePlugins);
  let pluginCatalog = clone(samplePluginCatalog);
  let mcpConfig = clone(sampleMcpConfig);
  let chat = clone(sampleChatSnapshot);
  let previewBranchCounter = 1;
  const previewBranches = new Map<string, ChatConversationBranch & { historyEntries: ChatHistoryEntry[] }>();
  previewBranches.set("main", {
    id: "main",
    label: "Main",
    parentId: null,
    historyEntries: cloneHistoryEntries(chat.historyEntries),
  });
  let activeThemeId = DEFAULT_CHAT_THEME_ID;
  let templateSession: TemplateLaunchSession | null = null;
  const cachedModelAssets = new Set<string>();
  const characterMemories = new Map<string, CharacterMemoryList>();
  const chatListeners = new Set<(snapshot: ChatSnapshot) => void>();
  const chatEventListeners = new Set<(event: ChatStageEvent) => void>();
  let previewChatEventSeq = 0;
  const pendingChatTimeouts = new Set<number>();
  const previewThemeManifests = new Map<string, ChatThemeManifest>(
    Object.entries(sampleChatThemeManifests).map(([id, manifest]) => [id, clone(manifest)]),
  );
  const previewThemeSources = new Map<string, ChatThemeSummary["source"]>(
    sampleChatThemeSummaries.map((theme) => [theme.id, theme.source]),
  );
  const previewThemeAssetBases = new Map<string, string>(
    sampleChatThemeSummaries.filter((theme) => theme.source === "builtin").map((theme) => [theme.id, theme.id]),
  );

  const emitChat = () => {
    const snapshot = clone(chat);
    chatListeners.forEach((listener) => listener(snapshot));
    const event: ChatStageEvent = {
      seq: (previewChatEventSeq += 1),
      snapshot,
      ts: Date.now(),
      type: "snapshot",
      v: 1,
    };
    chatEventListeners.forEach((listener) => listener(event));
  };

  const emitTurnState = () => {
    const snapshot = clone(chat);
    chatListeners.forEach((listener) => listener(snapshot));
    const event: ChatStageEvent = {
      seq: (previewChatEventSeq += 1),
      state: clone(chat.turnState ?? sampleChatSnapshot.turnState!),
      ts: Date.now(),
      type: "chat.turn.state",
      v: 1,
    };
    chatEventListeners.forEach((listener) => listener(event));
  };

  const previewBranchTree = () => ({
    activeBranchId: chat.conversationTree?.activeBranchId || "main",
    branches: [...previewBranches.values()].map(({ historyEntries: _historyEntries, ...branch }) => ({ ...branch })),
  });

  const savePreviewActiveBranch = () => {
    const activeBranchId = chat.conversationTree?.activeBranchId || "main";
    const branch = previewBranches.get(activeBranchId);
    if (branch) {
      branch.historyEntries = cloneHistoryEntries(chat.historyEntries);
      branch.updatedAt = Date.now();
    }
  };

  const stripPreviewUserPrefix = (value: string) => {
    const parts = value.split(/：|:/);
    return parts.length > 1 ? parts.slice(1).join("：").trim() : value.trim();
  };

  const clearScheduledChatUpdates = () => {
    for (const timeoutId of pendingChatTimeouts) {
      window.clearTimeout(timeoutId);
    }
    pendingChatTimeouts.clear();
  };

  const scheduleChatUpdate = (delayMs: number, patch: (current: ChatSnapshot) => ChatSnapshot) => {
    const timeoutId = window.setTimeout(() => {
      pendingChatTimeouts.delete(timeoutId);
      chat = patch(chat);
      emitChat();
    }, delayMs);
    pendingChatTimeouts.add(timeoutId);
  };

  const resolvePreviewManifest = (id: string) =>
    previewThemeManifests.get(id) ?? previewThemeManifests.get(DEFAULT_CHAT_THEME_ID);

  const resolvePreviewThemeAssetUrl = (path: string) => {
    const direct = builtinChatThemeAssetUrls[path];
    if (direct) {
      return direct;
    }
    const prefix = "data/chat_ui_themes/";
    if (!path.startsWith(prefix)) {
      return path;
    }
    const themePath = path.slice(prefix.length);
    const separator = themePath.indexOf("/");
    if (separator <= 0) {
      return path;
    }
    const themeId = themePath.slice(0, separator);
    const relativeAsset = themePath.slice(separator + 1);
    const assetBaseId = previewThemeAssetBases.get(themeId);
    if (!assetBaseId || assetBaseId === themeId) {
      return path;
    }
    return builtinChatThemeAssetUrls[`${prefix}${assetBaseId}/${relativeAsset}`] ?? path;
  };

  const listPreviewThemes = (): ChatThemeSummary[] =>
    Array.from(previewThemeManifests.values()).map((manifest) => {
      const source = previewThemeSources.get(manifest.id) ?? "user";
      const previewPath = manifest.preview ? `data/chat_ui_themes/${manifest.id}/${manifest.preview}` : "";
      return {
        id: manifest.id,
        name: clone(manifest.name),
        author: manifest.author,
        version: manifest.version,
        previewUrl: source === "builtin" ? builtinChatThemeAssetUrls[previewPath] : undefined,
        source,
      };
    });

  return {
    backgrounds: {
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
    },
    effects: {
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
        effect.audio_list = effect.audio_list.filter((_, itemIndex) => itemIndex !== index);
        effect.audio_tags = effect.audio_tags
          .split(/\r?\n/)
          .filter(Boolean)
          .filter((_, itemIndex) => itemIndex !== index)
          .map((line, itemIndex) => `特效 ${itemIndex + 1}：${line.split(/\：|:/).slice(1).join("：")}`)
          .join("\n");
        if (effect.audio_tags) {
          effect.audio_tags += "\n";
        }
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
      async uploadAudio(input) {
        const effect = config.effect_list.find((item) => item.name === input.name);
        if (!effect) {
          throw new Error("特效方案不存在。");
        }
        effect.audio_list = [...effect.audio_list, ...input.paths];
        effect.audio_tags = `${input.audioTags || ""}${input.paths.map((_, index) => `特效 ${effect.audio_list.length - input.paths.length + index + 1}：`).join("\n")}\n`;
        return delay(effect);
      },
    },
    chat: {
      async close() {
        clearScheduledChatUpdates();
        chat = {
          ...chat,
          chatProcessRunning: false,
          chatRuntimeClosing: false,
          notificationText: "聊天会话已结束。",
          options: [],
          sessionClosedReason: "聊天会话已结束。",
          status: "idle",
        };
        emitChat();
        return delay(chat);
      },
      async command(command) {
        if (isPreviewRealtimeCommand(command) && String(chat.sessionClosedReason ?? "").trim()) {
          chat = {
            ...chat,
            notificationText: "",
            sessionClosedReason: "",
          };
        }
        if (command.type === "update-turn-options") {
          const payload = command.payload as Partial<NonNullable<ChatSnapshot["turnOptions"]>> | undefined;
          const nextOptions = {
            batchEnabled: Boolean(payload?.batchEnabled),
            batchIdleSeconds: Math.min(120, Math.max(0.3, Number(payload?.batchIdleSeconds) || 5)),
            interruptEnabled: payload?.interruptEnabled !== false,
          };
          config.api_config.interrupt_enabled = nextOptions.interruptEnabled;
          config.api_config.is_batch_input_enabled = nextOptions.batchEnabled;
          config.api_config.batch_input_timeout = nextOptions.batchIdleSeconds;
          chat = {
            ...chat,
            turnOptions: nextOptions,
            turnState: {
              ...(chat.turnState ?? sampleChatSnapshot.turnState!),
              enabled: nextOptions.batchEnabled,
            },
          };
          emitTurnState();
        }
        if (command.type === "chat-input-state") {
          const payload = command.payload as { composing?: unknown; hasText?: unknown } | undefined;
          const active = Boolean(payload?.composing || payload?.hasText);
          chat = {
            ...chat,
            turnState: {
              ...(chat.turnState ?? sampleChatSnapshot.turnState!),
              remainingSeconds: active ? null : (chat.turnOptions?.batchIdleSeconds ?? 5),
              scheduled: !active && (chat.turnState?.pendingCount ?? 0) > 0,
              typing: active && (chat.turnState?.pendingCount ?? 0) > 0,
            },
          };
          emitTurnState();
        }
        if (command.type === "flush-input-batch" || command.type === "cancel-input-batch") {
          chat = {
            ...chat,
            turnState: {
              ...(chat.turnState ?? sampleChatSnapshot.turnState!),
              pendingCount: 0,
              remainingSeconds: null,
              scheduled: false,
              typing: false,
            },
          };
          emitTurnState();
        }
        if (command.type === "send-message") {
          if (chat.turnOptions?.batchEnabled) {
            chat = {
              ...chat,
              inputDraft: "",
              turnState: {
                ...(chat.turnState ?? sampleChatSnapshot.turnState!),
                enabled: true,
                pendingCount: (chat.turnState?.pendingCount ?? 0) + 1,
                remainingSeconds: chat.turnOptions.batchIdleSeconds,
                scheduled: true,
                typing: false,
              },
            };
            emitChat();
            return delay(chat);
          }
          clearScheduledChatUpdates();
          const payload = String(command.payload ?? "").trim();
          const userDisplayName = chat.userDisplayName?.trim() || "你";
          const nextUserIndex =
            Math.max(-1, ...cloneHistoryEntries(chat.historyEntries).map((entry) => entry.revertUserIndex ?? -1)) + 1;
          chat = {
            ...chat,
            characterName: userDisplayName,
            dialogText: payload,
            historyEntries: [
              ...cloneHistoryEntries(chat.historyEntries),
              {
                createdAt: Date.now(),
                id: `history-${Date.now()}-user`,
                revertUserIndex: nextUserIndex,
                role: "user",
                text: `${userDisplayName}: ${payload}`,
              },
            ],
            inputDraft: "",
            options: [],
            numericInfo: "streaming",
            status: "streaming",
          };
          emitChat();
          scheduleChatUpdate(700, (current) => ({
            ...current,
            characterName: "Nanami",
            dialogText: `收到：${payload}`,
            historyEntries: [
              ...cloneHistoryEntries(current.historyEntries),
              { id: `history-${Date.now()}-assistant`, role: "assistant", text: `Nanami: 收到：${payload}` },
            ],
            numericInfo: "speaking",
            status: "speaking",
          }));
          scheduleChatUpdate(1400, (current) => ({ ...current, numericInfo: "idle", status: "idle" }));
        }
        if (command.type === "submit-option") {
          clearScheduledChatUpdates();
          const option = String(command.payload ?? "").trim();
          chat = {
            ...chat,
            dialogText: `选择：${option}`,
            historyEntries: [
              ...cloneHistoryEntries(chat.historyEntries),
              { id: `history-${Date.now()}-option`, role: "options", text: `选项: ${option}` },
            ],
            options: [],
            status: "generating",
            numericInfo: "generating",
          };
          emitChat();
          scheduleChatUpdate(650, (current) => ({
            ...current,
            dialogText: `Nanami: 已选择「${option}」`,
            historyEntries: [
              ...cloneHistoryEntries(current.historyEntries),
              { id: `history-${Date.now()}-assistant`, role: "assistant", text: `Nanami: 已选择「${option}」` },
            ],
            numericInfo: "idle",
            status: "idle",
          }));
        }
        if (command.type === "skip-speech" || command.type === "dialog-advance") {
          clearScheduledChatUpdates();
          chat = { ...chat, status: "idle", numericInfo: "idle" };
          emitChat();
        }
        if (command.type === "pause-asr") {
          clearScheduledChatUpdates();
          chat = { ...chat, status: "paused", numericInfo: "paused" };
          emitChat();
        }
        if (command.type === "resume-asr") {
          clearScheduledChatUpdates();
          chat = { ...chat, status: "listening", numericInfo: "listening" };
          emitChat();
        }
        if (command.type === "change-voice-language") {
          const voiceLanguage =
            String(command.payload ?? "")
              .trim()
              .toLowerCase() || "ja";
          config.system_config.voice_language = voiceLanguage;
          chat = { ...chat, numericInfo: "idle", status: "idle", voiceLanguage };
          emitChat();
        }
        if (command.type === "clear-history") {
          clearScheduledChatUpdates();
          chat = {
            ...chat,
            dialogText: "浏览器预览历史已清空。",
            historyEntries: [],
            options: [],
            status: "idle",
            numericInfo: "idle",
          };
          emitChat();
        }
        if (command.type === "revert-history") {
          clearScheduledChatUpdates();
          const revertUserIndex = Number(command.payload);
          const entries = cloneHistoryEntries(chat.historyEntries);
          const userEntryPosition = entries.findIndex(
            (entry) => entry.role === "user" && entry.revertUserIndex === revertUserIndex,
          );
          if (userEntryPosition >= 0) {
            let targetIndex = -1;
            for (let index = userEntryPosition - 1; index >= 0; index -= 1) {
              if (entries[index]?.role !== "user") {
                targetIndex = index;
                break;
              }
            }
            if (targetIndex >= 0) {
              const nextEntries = entries.slice(0, targetIndex + 1);
              const lastEntry = nextEntries[nextEntries.length - 1];
              chat = {
                ...chat,
                dialogText: lastEntry?.text ?? "",
                historyEntries: nextEntries,
                options:
                  lastEntry?.role === "options"
                    ? lastEntry.text
                        .split(/：|:/)
                        .slice(1)
                        .join("：")
                        .split("/")
                        .map((item) => item.trim())
                        .filter(Boolean)
                    : [],
                status: "idle",
                numericInfo: "idle",
              };
              emitChat();
            }
          }
        }
        if (command.type === "fork-history") {
          clearScheduledChatUpdates();
          savePreviewActiveBranch();
          const payload = command.payload;
          const userIndex = Number(
            typeof payload === "object" && payload ? (payload as { userIndex?: unknown }).userIndex : payload,
          );
          const entries = cloneHistoryEntries(chat.historyEntries);
          const userEntryPosition = entries.findIndex(
            (entry) => entry.role === "user" && entry.revertUserIndex === userIndex,
          );
          if (userEntryPosition >= 0) {
            const userEntry = entries[userEntryPosition];
            const userText = stripPreviewUserPrefix(userEntry?.text ?? "");
            const prefixEntries = entries.slice(0, userEntryPosition);
            previewBranchCounter += 1;
            const branchId = `branch-${previewBranchCounter}`;
            previewBranches.set(branchId, {
              createdAt: Date.now(),
              forkedFromEntryId: userEntry?.id,
              forkedFromText: userText,
              historyEntries: cloneHistoryEntries(prefixEntries),
              id: branchId,
              label: `Branch ${previewBranchCounter}`,
              parentId: chat.conversationTree?.activeBranchId || "main",
              updatedAt: Date.now(),
            });
            const nextUserIndex = Math.max(-1, ...prefixEntries.map((entry) => entry.revertUserIndex ?? -1)) + 1;
            chat = {
              ...chat,
              characterName: chat.userDisplayName?.trim() || "你",
              conversationTree: { activeBranchId: branchId, branches: previewBranchTree().branches },
              dialogText: userText,
              historyEntries: [
                ...cloneHistoryEntries(prefixEntries),
                {
                  createdAt: Date.now(),
                  id: `history-${Date.now()}-user`,
                  revertUserIndex: nextUserIndex,
                  role: "user",
                  text: `${chat.userDisplayName?.trim() || "你"}: ${userText}`,
                },
              ],
              options: [],
              numericInfo: "streaming",
              status: "streaming",
            };
            chat.conversationTree = previewBranchTree();
            emitChat();
            scheduleChatUpdate(700, (current) => ({
              ...current,
              characterName: "Nanami",
              dialogText: `分支回复：${userText}`,
              historyEntries: [
                ...cloneHistoryEntries(current.historyEntries),
                { id: `history-${Date.now()}-assistant`, role: "assistant", text: `Nanami: 分支回复：${userText}` },
              ],
              numericInfo: "idle",
              status: "idle",
            }));
          }
        }
        if (command.type === "switch-branch") {
          clearScheduledChatUpdates();
          savePreviewActiveBranch();
          const branchId = String(command.payload ?? "").trim();
          const branch = previewBranches.get(branchId);
          if (branch) {
            chat = {
              ...chat,
              conversationTree: { activeBranchId: branchId, branches: previewBranchTree().branches },
              dialogText: branch.historyEntries.at(-1)?.text ?? "",
              historyEntries: cloneHistoryEntries(branch.historyEntries),
              numericInfo: "idle",
              options: [],
              status: "idle",
            };
            chat.conversationTree = previewBranchTree();
            emitChat();
          }
        }
        if (command.type === "rename-branch") {
          const payload = command.payload;
          const branchId =
            typeof payload === "object" && payload
              ? String((payload as { branchId?: unknown }).branchId ?? "").trim()
              : "";
          const label =
            typeof payload === "object" && payload ? String((payload as { label?: unknown }).label ?? "").trim() : "";
          const branch = previewBranches.get(branchId);
          if (branch && label) {
            branch.label = label.slice(0, 64);
            branch.updatedAt = Date.now();
            chat.conversationTree = previewBranchTree();
            emitChat();
          }
        }
        if (command.type === "copy-history") {
          return {
            ...clone(chat),
            clipboardText: cloneHistoryEntries(chat.historyEntries)
              .map((entry) => entry.text)
              .join("\n"),
          };
        }
        if (command.type === "open-history") {
          return { ...clone(chat), openedPath: chat.historyPath ?? "./data/chat_history/preview" };
        }
        return clone(chat);
      },
      getHistory: () => delay(cloneHistoryEntries(chat.historyEntries)),
      getRuntimeStatus: () => delay(runtimeStatusFromSnapshot(chat)),
      getSnapshot: () => delay(chat),
      getTheme: () =>
        delay(
          previewThemePayloadFromManifest(
            resolvePreviewManifest(activeThemeId) ?? sampleChatThemeManifests[DEFAULT_CHAT_THEME_ID],
          ),
        ),
      async launch(payload, options) {
        const taskId = `preview-chat-init-${Date.now()}`;
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Preparing chat runtime",
            phase: "preparing",
            progress: 0.08,
            status: "running",
            title: "Initialize chat",
          },
          options,
        );
        await delay(null, 80);
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Starting voice services",
            phase: "tts",
            progress: 0.46,
            status: "running",
            title: "Initialize chat",
          },
          options,
        );
        await delay(null, 80);
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Loading chat memory",
            phase: "memory",
            progress: 0.76,
            status: "running",
            title: "Initialize chat",
          },
          options,
        );
        await delay(null, 80);
        const character = config.characters.find((item) => payload.characters.includes(item.name));
        const background = config.background_list.find((item) => item.name === payload.backgroundName);
        const historyPath = payload.historyPath || chat.historyPath || "./data/chat_history/preview";
        chat = {
          ...chat,
          backgroundPath: background?.sprites[0]?.path,
          characterName: character?.name,
          chatProcessRunning: true,
          chatRuntimeClosing: false,
          dialogText: "",
          historyPath,
          sprites: character?.sprites[0]
            ? [{ id: `${character.name}-0`, label: character.name, path: character.sprites[0].path }]
            : [],
          sessionClosedReason: "",
          status: "idle",
          statusMessage: `${payload.templateId || payload.templateName || "预览聊天"} 已启动：${historyPath}`,
        };
        emitChat();
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Chat is ready",
            phase: "completed",
            progress: 1,
            result: clone(chat),
            status: "succeeded",
            title: "Initialize chat",
          },
          options,
        );
        return clone(chat);
      },
      async resumeLast(options) {
        const taskId = `preview-chat-init-${Date.now()}`;
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Preparing the previous chat",
            phase: "preparing",
            progress: 0.12,
            status: "running",
            title: "Initialize chat",
          },
          options,
        );
        await delay(null, 80);
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Restoring chat services",
            phase: "runtime",
            progress: 0.68,
            status: "running",
            title: "Initialize chat",
          },
          options,
        );
        await delay(null, 80);
        const character = config.characters.find((item) => templateSession?.selectedCharacters?.includes(item.name));
        const background = config.background_list.find((item) => item.name === templateSession?.background);
        const historyPath = templateSession?.historyPath || chat.historyPath || "./data/chat_history/preview";
        chat = {
          ...chat,
          backgroundPath: background?.sprites[0]?.path ?? chat.backgroundPath,
          characterName: character?.name ?? chat.characterName,
          chatProcessRunning: true,
          chatRuntimeClosing: false,
          dialogText: "",
          historyPath,
          sprites: character?.sprites[0]
            ? [{ id: `${character.name}-0`, label: character.name, path: character.sprites[0].path }]
            : chat.sprites,
          sessionClosedReason: "",
          status: "idle",
          statusMessage: `已恢复上次启动：${historyPath}`,
        };
        emitChat();
        previewTask<ChatSnapshot>(
          taskId,
          {
            kind: "chat-initialization",
            message: "Chat is ready",
            phase: "completed",
            progress: 1,
            result: clone(chat),
            status: "succeeded",
            title: "Initialize chat",
          },
          options,
        );
        return clone(chat);
      },
      subscribe(listener) {
        chatListeners.add(listener);
        listener(clone(chat));
        return () => chatListeners.delete(listener);
      },
      listThemes: () => delay<ChatThemeSummary[]>(listPreviewThemes()),
      async getThemeManifest(id) {
        const manifest = resolvePreviewManifest(id);
        if (!manifest) {
          throw new Error(`主题不存在：${id}`);
        }
        return delay<ChatThemeManifest>(manifest);
      },
      getActiveThemeId: () => delay(activeThemeId),
      async setActiveThemeId(id) {
        if (!previewThemeManifests.has(id)) {
          throw new Error(`主题不存在：${id}`);
        }
        activeThemeId = id;
      },
      async uploadTheme(file) {
        const id =
          file.name
            .replace(/\.zip$/i, "")
            .trim()
            .replace(/[^\w-]+/g, "-") || "uploaded-theme";
        const base = resolvePreviewManifest(activeThemeId) ?? sampleChatThemeManifests[DEFAULT_CHAT_THEME_ID];
        const manifest: ChatThemeManifest = {
          ...clone(base),
          id,
          name: { zh_CN: file.name, en: file.name, ja: file.name },
          tokens: {
            ...clone(base.tokens),
            global: {
              ...clone(base.tokens.global ?? {}),
              themeColor: "#2fbf9f",
            },
            send: {
              ...clone(base.tokens.send ?? {}),
              background: "#2fbf9f",
            },
          },
        };
        previewThemeManifests.set(id, manifest);
        previewThemeSources.set(id, "user");
        previewThemeAssetBases.delete(id);
        return delay<ChatThemeSummary>({
          id,
          name: clone(manifest.name),
          author: manifest.author,
          version: manifest.version,
          source: "user",
        });
      },
      async saveTheme(input) {
        const manifest = clone(input.manifest);
        const existingSource = previewThemeSources.get(manifest.id);
        const creating = manifest.id !== input.baseId;
        if (existingSource === "builtin") {
          throw new Error("内置主题不可编辑。");
        }
        if (creating && previewThemeManifests.has(manifest.id)) {
          throw new Error(`主题已存在：${manifest.id}`);
        }
        if (!previewThemeManifests.has(manifest.id) && !previewThemeManifests.has(input.baseId)) {
          throw new Error(`基础主题不存在：${input.baseId}`);
        }
        previewThemeManifests.set(manifest.id, manifest);
        previewThemeSources.set(manifest.id, "user");
        if (creating) {
          const assetBaseId = previewThemeAssetBases.get(input.baseId);
          if (assetBaseId) {
            previewThemeAssetBases.set(manifest.id, assetBaseId);
          } else {
            previewThemeAssetBases.delete(manifest.id);
          }
        }
        return delay<ChatThemeSummary>({
          id: manifest.id,
          name: clone(manifest.name),
          author: manifest.author,
          version: manifest.version,
          source: "user",
        });
      },
      async deleteTheme(id) {
        if ((previewThemeSources.get(id) ?? "user") !== "user") {
          throw new Error("内置主题不能删除。");
        }
        previewThemeManifests.delete(id);
        previewThemeSources.delete(id);
        previewThemeAssetBases.delete(id);
        if (activeThemeId === id) {
          activeThemeId = DEFAULT_CHAT_THEME_ID;
        }
      },
      subscribeEvents(listener) {
        chatEventListeners.add(listener);
        listener({
          seq: (previewChatEventSeq += 1),
          snapshot: clone(chat),
          ts: Date.now(),
          type: "snapshot",
          v: 1,
        });
        return () => {
          chatEventListeners.delete(listener);
        };
      },
    },
    characters: {
      async autoLabelSprites(name) {
        const character = config.characters.find((item) => item.name === name);
        if (!character) {
          throw new Error(`Character not found: ${name}`);
        }
        const tags = tagContents(character.emotion_tags, character.sprites.length);
        let annotatedCount = 0;
        tags.forEach((tag, index) => {
          if (!tag.trim()) {
            tags[index] = "微笑，正面站姿，角色立绘";
            annotatedCount += 1;
          }
        });
        character.emotion_tags = numberedTags("立绘", tags);
        return delay({
          annotatedCount,
          failedCount: 0,
          failures: [],
          name,
          scope: "character" as const,
          skippedCount: character.sprites.length - annotatedCount,
          tags: character.emotion_tags,
          totalCount: character.sprites.length,
        });
      },
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
      getMem0Status: () => delay({ status: "ready" as const }),
      async importMemories(name, items, options) {
        const preview = await previewMemoryImport(items);
        const taskId = `memory-import-${Date.now()}`;
        previewTask<CharacterMemoryImportResult>(
          taskId,
          {
            kind: "character-memory-import",
            message: "Preparing dialogue chunks",
            phase: "preparing",
            title: "Import long-term memories",
          },
          options,
        );
        await delay(undefined, 80);
        previewTask<CharacterMemoryImportResult>(
          taskId,
          {
            kind: "character-memory-import",
            message: "Extracting long-term memories",
            phase: "extracting",
            progress: 0.55,
            status: "running",
            title: "Import long-term memories",
          },
          options,
        );
        await delay(undefined, 120);
        const memories = items.map((item, index) => {
          return `Imported memory ${index + 1} from ${item.name}`;
        });
        const agentId = name || "user";
        const current = characterMemories.get(agentId) ?? { agentId, count: 0, memories: [] };
        const nextMemories = [
          ...current.memories,
          ...memories.map((memory, index) => ({ id: `${agentId}-import-${Date.now()}-${index}`, memory })),
        ];
        characterMemories.set(agentId, { agentId, count: nextMemories.length, memories: nextMemories });
        const result: CharacterMemoryImportResult = {
          chunkCount: preview.chunkCount,
          duplicateCount: 0,
          estimatedTotalTokens: preview.estimatedTotalTokens,
          extractedCount: memories.length,
          fileCount: preview.fileCount,
          memories,
          savedCount: memories.length,
        };
        previewTask(
          taskId,
          {
            kind: "character-memory-import",
            message: "Memory import complete",
            phase: "completed",
            progress: 1,
            result,
            status: "succeeded",
            title: "Import long-term memories",
          },
          options,
        );
        return clone(result);
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
      previewMemoryImport: (_name, items) => previewMemoryImport(items),
      async searchMemories({ limit = 200, name, query }) {
        const agentId = name || "user";
        const existing = await this.listMemories(agentId);
        const normalizedQuery = query.trim().toLowerCase();
        const memories = normalizedQuery
          ? existing.memories.filter((memory) => memory.memory.toLowerCase().includes(normalizedQuery))
          : existing.memories;
        const limitedMemories = memories.slice(0, limit);
        return delay({ agentId, count: limitedMemories.length, memories: limitedMemories });
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
      async saveSpriteVoiceType(name, spriteIndex, voiceType) {
        const character = config.characters.find((item) => item.name === name);
        if (!character || !character.sprites[spriteIndex]) {
          throw new Error("立绘不存在。");
        }
        character.sprites[spriteIndex] = {
          ...character.sprites[spriteIndex],
          voice_type: voiceType,
        };
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
          voice_type: input.voiceType,
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
        const bundleRoots = {
          genie: "data/tts_bundles/installed/genie_tts_server/Genie-TTS-Server",
          gptso: "data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro-20250604",
          gptso50: "data/tts_bundles/installed/gpt_sovits_nvidia50/GPT-SoVITS-v2pro-20250604-nvidia50",
        } as const;
        const result = {
          path: bundleRoots[input.kind],
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
      detectNetworkProxy: () =>
        delay({
          http_proxy_url: "",
          https_proxy_url: "",
          socks5_proxy_url: "",
          source: "browser-preview",
        }),
      getMemoryStatus: () => delay({ modelCached: true, status: "ready" as const }),
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
    modelAssets: {
      async download(input, options) {
        const variant = String(
          (input.configured ? config.system_config.asr_whisper_model_size : input.variant) || "small",
        );
        const local = Boolean(input.configured && looksLikeLocalModelReference(variant));
        const key = `${input.assetId}:${variant}`;
        const taskId = `preview-model-${Date.now()}`;
        previewTask(
          taskId,
          {
            kind: "model-download",
            message: `正在下载 ${variant}。`,
            phase: "download",
            progress: 0.42,
            status: "running",
            title: "模型下载",
          },
          options,
        );
        await delay(null, 180);
        const result = {
          assetId: input.assetId,
          cached: true,
          downloadable: !local,
          downloaded: !local,
          path: local ? variant : `preview-cache/${variant}`,
          ...(local ? {} : { repoId: variant.includes("/") ? variant : `Systran/faster-whisper-${variant}` }),
          source: local ? ("local" as const) : ("huggingface" as const),
          title: "Whisper ASR",
          variant,
        };
        if (!local) {
          cachedModelAssets.add(key);
        }
        previewTask(
          taskId,
          {
            kind: "model-download",
            message: `${variant} 已缓存。`,
            phase: "completed",
            progress: 1,
            result,
            status: "succeeded",
            title: "模型下载",
          },
          options,
        );
        return result;
      },
      status(input) {
        const variant = String(
          (input.configured ? config.system_config.asr_whisper_model_size : input.variant) || "small",
        );
        const local = Boolean(input.configured && looksLikeLocalModelReference(variant));
        return delay({
          assetId: input.assetId,
          cached: local || cachedModelAssets.has(`${input.assetId}:${variant}`),
          downloadable: !local,
          ...(local
            ? { path: variant }
            : { repoId: variant.includes("/") ? variant : `Systran/faster-whisper-${variant}` }),
          source: local ? ("local" as const) : ("huggingface" as const),
          title: "Whisper ASR",
          variant,
        });
      },
    },
    files: {
      browse(options) {
        return delay(previewFileBrowser(options?.path));
      },
      fileUrl(path) {
        return resolvePreviewThemeAssetUrl(path);
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
            message: "正在生成翻唱音频。",
            phase: "run",
            progress: 0.45,
            status: "running",
            title: "音乐翻唱",
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
            message: "翻唱音频预览完成。",
            phase: "completed",
            progress: 1,
            result,
            status: "succeeded",
            title: "音乐翻唱",
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
        const catalog = previewCatalogForSource(id, pluginCatalog);
        const entry = catalog?.entry || id;
        const title = catalog?.displayName || catalog?.name || id;
        const repo = catalog?.repo || "";
        const packageSha256 = catalog?.packageSha256 || catalog?.sha256 || "";
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
          author: catalog?.author || "Preview",
          description: "浏览器预览安装的插件。",
          directory: previewPluginDirectory(entry, id),
          enabled: true,
          entry,
          id: catalog?.id || catalog?.name || id,
          install: {
            entry,
            packageSha256,
            packageSize: catalog?.packageSize ?? catalog?.size ?? null,
            packageSource: catalog?.packageSource || (catalog?.packageUrl ? "r2" : ""),
            packageStatus: packageSha256 ? "verified" : "installed",
            packageUrl: catalog?.packageUrl || catalog?.downloadUrl || "",
            repo,
            sourceLabel: catalog?.packageUrl ? "Official package (R2)" : repo ? "GitHub" : "Preview",
            sourceType: catalog?.packageUrl ? "package" : repo ? "github" : "preview",
          },
          loaded: true,
          permissions: ["settings"],
          settingsPages: ["预览设置"],
          slots: ["settings-extension"],
          title,
          toolsTabs: [],
          version: catalog?.version || "preview",
        };
        plugins = previewUpsertPlugin(plugins, plugin, catalog);
        pluginCatalog = pluginCatalog.map((item) =>
          previewCatalogKeys(item).has(previewNormalizePluginKey(id))
            ? { ...item, downloaded: true, installed: true }
            : item,
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
        const scenario =
          input.scenario ||
          `你需要模拟一个RPG剧情对话系统，出场人物有：${input.characters.join("、")} 以及其他相关人物，请根据剧情调度人物。`;
        const system = "";
        const template: TemplateSummary = {
          content: [scenario, system].filter(Boolean).join("\n\n"),
          id: "",
          name: input.name || "新模板",
          path: "",
          scenario,
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
