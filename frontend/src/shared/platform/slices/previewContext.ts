import type { ChatThemePayload } from "../../theme/chatChromeTheme";
import { DEFAULT_CHAT_THEME_ID, type ChatThemeManifest, type ChatThemeSummary } from "../../theme/chatTheme";
import {
  sampleChatSnapshot,
  sampleChatTheme,
  sampleChatThemeManifests,
  sampleChatThemeSummaries,
  sampleConfig,
  sampleTemplates,
} from "../sampleData";
import type { CharacterMemoryImportPreview } from "./characterTypes";
import type { ChatLaunchPayload, ChatSnapshot, ChatStageEvent, ConversationSummary } from "./chatTypes";
import type { AppConfig } from "./configTypes";
import type { TaskProgressOptions, TaskSnapshot } from "./taskTypes";
import type { TemplateLaunchSession, TemplateSummary } from "./workspaceTypes";

const bundledChatThemeAssets = import.meta.glob<string>(
  "../../../../../assets/chat_ui_themes/**/*.{gif,jpeg,jpg,mp3,ogg,otf,png,svg,ttf,wav,webp,woff,woff2}",
  { eager: true, import: "default", query: "?url" },
);
const bundledChatThemeRoot = "../../../../../assets/chat_ui_themes/";
export const previewSpriteUrl = new URL("../../../../../assets/present_example.png", import.meta.url).href;

const builtinChatThemeAssetUrls: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(bundledChatThemeAssets).map(([path, url]) => [
    `data/chat_ui_themes/${path.slice(bundledChatThemeRoot.length)}`,
    url,
  ]),
);

export function clone<T>(value: T): T {
  return structuredClone(value);
}

export function delay<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(clone(value)), ms));
}

export function previewTask<TResult>(
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

export async function previewMemoryImport(items: File[]): Promise<CharacterMemoryImportPreview> {
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

export function previewThemePayloadFromManifest(manifest: ChatThemeManifest): ChatThemePayload {
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

export interface KnowledgePreviewRecord {
  memories: Array<{ id: string; memory: string }>;
  characters: Array<{ name: string; createdAt: string }>;
}

export interface BrowserPreviewContext {
  config: AppConfig;
  getChat: () => ChatSnapshot;
  setChat: (next: ChatSnapshot) => void;
  emitChat: () => void;
  emitTurnState: () => void;
  nextChatEventSeq: () => number;
  chatListeners: Set<(snapshot: ChatSnapshot) => void>;
  chatEventListeners: Set<(event: ChatStageEvent) => void>;
  conversations: Map<string, { summary: ConversationSummary; payload: ChatLaunchPayload }>;
  getTemplates: () => TemplateSummary[];
  setTemplates: (next: TemplateSummary[]) => void;
  getTemplateSession: () => TemplateLaunchSession | null;
  setTemplateSession: (next: TemplateLaunchSession | null) => void;
  cachedModelAssets: Set<string>;
  knowledgeData: Map<string, KnowledgePreviewRecord>;
  getActiveThemeId: () => string;
  setActiveThemeId: (id: string) => void;
  previewThemeManifests: Map<string, ChatThemeManifest>;
  previewThemeSources: Map<string, ChatThemeSummary["source"]>;
  previewThemeAssetBases: Map<string, string>;
  resolvePreviewManifest: (id: string) => ChatThemeManifest | undefined;
  resolvePreviewThemeAssetUrl: (path: string) => string;
  listPreviewThemes: () => ChatThemeSummary[];
}

export function createBrowserPreviewContext(): BrowserPreviewContext {
  const config = clone(sampleConfig);
  let templates = clone(sampleTemplates);
  let chat = clone(sampleChatSnapshot);
  const conversations = new Map<string, { summary: ConversationSummary; payload: ChatLaunchPayload }>();
  let activeThemeId = DEFAULT_CHAT_THEME_ID;
  let templateSession: TemplateLaunchSession | null = null;
  const cachedModelAssets = new Set<string>();
  const knowledgeData = new Map<string, KnowledgePreviewRecord>();
  knowledgeData.set("preview-knowledge", {
    memories: Array.from({ length: 18 }, (_, index) => ({
      id: `knowledge-preview-${index + 1}`,
      memory: `雾港世界设定 ${index + 1}：居民依靠钟声辨认进港的船只。`,
    })),
    characters: config.characters.map((character) => ({ name: character.name, createdAt: "2026-09-14 00:00:00" })),
  });

  const chatListeners = new Set<(snapshot: ChatSnapshot) => void>();
  const chatEventListeners = new Set<(event: ChatStageEvent) => void>();
  let previewChatEventSeq = 0;

  const previewThemeManifests = new Map<string, ChatThemeManifest>(
    Object.entries(sampleChatThemeManifests).map(([id, manifest]) => [id, clone(manifest)]),
  );
  const previewThemeSources = new Map<string, ChatThemeSummary["source"]>(
    sampleChatThemeSummaries.map((theme) => [theme.id, theme.source]),
  );
  const previewThemeAssetBases = new Map<string, string>(
    sampleChatThemeSummaries.filter((theme) => theme.source === "builtin").map((theme) => [theme.id, theme.id]),
  );

  const nextChatEventSeq = () => (previewChatEventSeq += 1);

  const emitChat = () => {
    const snapshot = clone(chat);
    chatListeners.forEach((listener) => listener(snapshot));
    const event: ChatStageEvent = {
      seq: nextChatEventSeq(),
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
      options: clone(chat.turnOptions ?? sampleChatSnapshot.turnOptions!),
      seq: nextChatEventSeq(),
      state: clone(chat.turnState ?? sampleChatSnapshot.turnState!),
      ts: Date.now(),
      type: "chat.turn.state",
      v: 1,
    };
    chatEventListeners.forEach((listener) => listener(event));
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
    config,
    getChat: () => chat,
    setChat: (next) => {
      chat = next;
    },
    emitChat,
    emitTurnState,
    nextChatEventSeq,
    chatListeners,
    chatEventListeners,
    conversations,
    getTemplates: () => templates,
    setTemplates: (next) => {
      templates = next;
    },
    getTemplateSession: () => templateSession,
    setTemplateSession: (next) => {
      templateSession = next;
    },
    cachedModelAssets,
    knowledgeData,
    getActiveThemeId: () => activeThemeId,
    setActiveThemeId: (id) => {
      activeThemeId = id;
    },
    previewThemeManifests,
    previewThemeSources,
    previewThemeAssetBases,
    resolvePreviewManifest,
    resolvePreviewThemeAssetUrl,
    listPreviewThemes,
  };
}
