import type { ChatThemePayload } from "../theme/chatChromeTheme";
import type {
  ApiConfig,
  AppConfig,
  AppUpdateInfo,
  AppUpdateResult,
  ChatCommand,
  ChatCommandResult,
  ChatLaunchPayload,
  ChatSnapshot,
  BatchToolResult,
  Background,
  BackgroundTranslateResult,
  Character,
  CharacterMemoryList,
  CharacterSettingResult,
  CharacterTranslateResult,
  FileBrowserSnapshot,
  LlmModelOption,
  McpConfig,
  McpToolPreview,
  MusicCoverRunResult,
  MusicCoverSearchResult,
  PluginCatalogItem,
  PluginConfigActionResult,
  PluginConfigSaveResult,
  PluginManifest,
  PluginUninstallResult,
  PluginUIDetail,
  ShinsekaiPlatform,
  SpriteGenerationResult,
  SpritePromptResult,
  SystemConfig,
  TaskProgressOptions,
  TaskSnapshot,
  TemplateLaunchSession,
  TemplateSummary,
  TtsBundleDownloadResult,
  TtsBundleRecommendation,
} from "./types";

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return data as T;
}

async function requestForm<T>(baseUrl: string, path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    body: formData,
    method: "POST",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return data as T;
}

function encodePath(value: string) {
  return encodeURIComponent(value);
}

function isFileList(items: File[] | string[]): items is File[] {
  return items.some((item) => item instanceof File);
}

function uploadFiles<T>(apiBase: string, path: string, files: File[]): Promise<T> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file, file.name);
  }
  return requestForm<T>(apiBase, path, formData);
}

function openDownload(apiBase: string, path: string) {
  const url = `${apiBase}/api/download?path=${encodeURIComponent(path)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isTaskRunning(task: TaskSnapshot) {
  return task.status === "queued" || task.status === "running";
}

async function waitForTask<TResult>(
  apiBase: string,
  initialTask: TaskSnapshot<TResult>,
  options?: TaskProgressOptions<TResult>,
): Promise<TResult> {
  let task = initialTask;
  options?.onTaskUpdate?.(task);

  while (isTaskRunning(task)) {
    await delay(450);
    task = await requestJson<TaskSnapshot<TResult>>(apiBase, `/api/tasks/${encodePath(task.id)}`);
    options?.onTaskUpdate?.(task);
  }

  if (task.status === "failed") {
    throw new Error(task.error || task.message || "任务失败。");
  }
  if (task.status === "cancelled") {
    const error = new Error(task.message || "任务已取消。");
    error.name = "TaskCancelledError";
    throw error;
  }
  if (!task.result) {
    throw new Error(task.message || "任务完成但没有返回结果。");
  }
  return task.result;
}

export function createHttpPlatform(baseUrl: string): ShinsekaiPlatform {
  const apiBase = baseUrl.replace(/\/$/, "");

  return {
    backgrounds: {
      delete: async (name) => {
        await requestJson(apiBase, `/api/backgrounds/${encodePath(name)}`, { method: "DELETE" });
      },
      deleteAllBgm: (name) =>
        requestJson<Background>(apiBase, "/api/backgrounds/bgm/delete-all", {
          body: JSON.stringify({ name }),
          method: "POST",
        }),
      deleteAllImages: (name) =>
        requestJson<Background>(apiBase, "/api/backgrounds/images/delete-all", {
          body: JSON.stringify({ name }),
          method: "POST",
        }),
      deleteBgm: (name, index) =>
        requestJson<Background>(apiBase, "/api/backgrounds/bgm/delete", {
          body: JSON.stringify({ index, name }),
          method: "POST",
        }),
      deleteImage: (name, index) =>
        requestJson<Background>(apiBase, "/api/backgrounds/images/delete", {
          body: JSON.stringify({ index, name }),
          method: "POST",
        }),
      export: async (name) => {
        const result = await requestJson<{ downloadUrl: string; path: string }>(apiBase, "/api/backgrounds/export", {
          body: JSON.stringify({ name }),
          method: "POST",
        });
        openDownload(apiBase, result.path);
        return result.path;
      },
      import: (items) => {
        if (isFileList(items)) {
          return uploadFiles<Background[]>(apiBase, "/api/backgrounds/import-upload", items);
        }
        return requestJson<Background[]>(apiBase, "/api/backgrounds/import", {
          body: JSON.stringify({ paths: items }),
          method: "POST",
        });
      },
      list: () => requestJson<Background[]>(apiBase, "/api/backgrounds"),
      save: (background, originalName) =>
        requestJson<Background>(apiBase, "/api/backgrounds", {
          body: JSON.stringify({ background, originalName }),
          method: "POST",
        }),
      saveBgmTags: (input) =>
        requestJson<Background>(apiBase, "/api/backgrounds/bgm-tags", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      saveImageTags: (input) =>
        requestJson<Background>(apiBase, "/api/backgrounds/tags", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      translateFields: (input) =>
        requestJson<BackgroundTranslateResult>(apiBase, "/api/backgrounds/translate", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      uploadBgm: (input) =>
        requestJson<Background>(apiBase, "/api/backgrounds/bgm/upload", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      uploadImages: (input) =>
        requestJson<Background>(apiBase, "/api/backgrounds/images/upload", {
          body: JSON.stringify(input),
          method: "POST",
        }),
    },
    chat: {
      command: async (command: ChatCommand) => {
        const result = await requestJson<ChatCommandResult>(apiBase, "/api/chat/command", {
          body: JSON.stringify(command),
          method: "POST",
        });
        if (result.clipboardText != null) {
          await navigator.clipboard.writeText(result.clipboardText);
        }
        if (result.downloadUrl) {
          window.open(`${apiBase}${result.downloadUrl}`, "_blank", "noopener,noreferrer");
        }
        return result;
      },
      getSnapshot: () => requestJson<ChatSnapshot>(apiBase, "/api/chat/snapshot"),
      getTheme: () => requestJson<ChatThemePayload>(apiBase, "/api/chat/theme"),
      launch: (payload: ChatLaunchPayload) =>
        requestJson<ChatSnapshot>(apiBase, "/api/chat/launch", {
          body: JSON.stringify(payload),
          method: "POST",
        }),
      resumeLast: () =>
        requestJson<ChatSnapshot>(apiBase, "/api/chat/resume-last", {
          body: JSON.stringify({}),
          method: "POST",
        }),
      subscribe(listener) {
        let stopped = false;
        let timeoutId = 0;

        const poll = async () => {
          try {
            const snapshot = await requestJson<ChatSnapshot>(apiBase, "/api/chat/snapshot");
            if (!stopped) {
              listener(snapshot);
            }
          } finally {
            if (!stopped) {
              timeoutId = window.setTimeout(poll, 1400);
            }
          }
        };

        poll();
        return () => {
          stopped = true;
          window.clearTimeout(timeoutId);
        };
      },
    },
    characters: {
      delete: async (name) => {
        await requestJson(apiBase, `/api/characters/${encodePath(name)}`, { method: "DELETE" });
      },
      deleteMemory: (name, memoryId) =>
        requestJson<CharacterMemoryList>(apiBase, "/api/characters/memories/delete", {
          body: JSON.stringify({ memoryId, name }),
          method: "POST",
        }),
      deleteSpriteVoice: (name, spriteIndex) =>
        requestJson<Character>(apiBase, "/api/characters/sprite-voice/delete", {
          body: JSON.stringify({ name, spriteIndex }),
          method: "POST",
        }),
      deleteAllSprites: (name) =>
        requestJson<Character>(apiBase, "/api/characters/sprites/delete-all", {
          body: JSON.stringify({ name }),
          method: "POST",
        }),
      deleteSprite: (name, spriteIndex) =>
        requestJson<Character>(apiBase, "/api/characters/sprites/delete", {
          body: JSON.stringify({ name, spriteIndex }),
          method: "POST",
        }),
      export: async (name) => {
        const result = await requestJson<{ downloadUrl: string; path: string }>(apiBase, "/api/characters/export", {
          body: JSON.stringify({ name }),
          method: "POST",
        });
        openDownload(apiBase, result.path);
        return result.path;
      },
      generateSetting: (input) =>
        requestJson<CharacterSettingResult>(apiBase, "/api/characters/ai-setting", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      import: (items) => {
        if (isFileList(items)) {
          return uploadFiles<Character[]>(apiBase, "/api/characters/import-upload", items);
        }
        return requestJson<Character[]>(apiBase, "/api/characters/import", {
          body: JSON.stringify({ paths: items }),
          method: "POST",
        });
      },
      list: () => requestJson<Character[]>(apiBase, "/api/characters"),
      listMemories: (name) =>
        requestJson<CharacterMemoryList>(apiBase, "/api/characters/memories/list", {
          body: JSON.stringify({ name }),
          method: "POST",
        }),
      remember: (name, content) =>
        requestJson<CharacterMemoryList>(apiBase, "/api/characters/memories/add", {
          body: JSON.stringify({ content, name }),
          method: "POST",
        }),
      save: (character, originalName) =>
        requestJson<Character>(apiBase, "/api/characters", {
          body: JSON.stringify({ character, originalName }),
          method: "POST",
        }),
      saveEmotionTags: (name, emotionTags) =>
        requestJson<Character>(apiBase, "/api/characters/emotion-tags", {
          body: JSON.stringify({ emotionTags, name }),
          method: "POST",
        }),
      saveSpriteScale: (name, scale) =>
        requestJson<Character>(apiBase, "/api/characters/sprite-scale", {
          body: JSON.stringify({ name, scale }),
          method: "POST",
        }),
      saveSpriteVoiceText: (name, spriteIndex, voiceText) =>
        requestJson<Character>(apiBase, "/api/characters/sprite-voice/text", {
          body: JSON.stringify({ name, spriteIndex, voiceText }),
          method: "POST",
        }),
      translateFields: (input) =>
        requestJson<CharacterTranslateResult>(apiBase, "/api/characters/translate", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      uploadSprites: (input) =>
        requestJson<Character>(apiBase, "/api/characters/sprites/upload", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      uploadSpriteVoice: (input) =>
        requestJson<Character>(apiBase, "/api/characters/sprite-voice/upload", {
          body: JSON.stringify(input),
          method: "POST",
        }),
    },
    config: {
      cancelTtsBundleDownload: (taskId) =>
        requestJson<TaskSnapshot<TtsBundleDownloadResult>>(apiBase, `/api/tasks/${encodePath(taskId)}/cancel`, {
          method: "POST",
        }),
      async downloadTtsBundle(input, options) {
        const task = await requestJson<TaskSnapshot<TtsBundleDownloadResult>>(
          apiBase,
          "/api/config/tts-bundle/download",
          {
            body: JSON.stringify(input),
            method: "POST",
          },
        );
        return waitForTask(apiBase, task, options);
      },
      fetchLlmModels: (input) =>
        requestJson<LlmModelOption[]>(apiBase, "/api/config/llm-models", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      get: () => requestJson<AppConfig>(apiBase, "/api/config"),
      getTtsBundleRecommendation: () =>
        requestJson<TtsBundleRecommendation>(apiBase, "/api/config/tts-bundle/recommendation"),
      saveApi: (config: ApiConfig) =>
        requestJson<ApiConfig>(apiBase, "/api/config/api", {
          body: JSON.stringify(config),
          method: "POST",
        }),
      saveSystem: (config: SystemConfig) =>
        requestJson<SystemConfig>(apiBase, "/api/config/system", {
          body: JSON.stringify(config),
          method: "POST",
        }),
    },
    files: {
      browse(options) {
        return requestJson<FileBrowserSnapshot>(apiBase, "/api/files/browse", {
          body: JSON.stringify(options ?? {}),
          method: "POST",
        });
      },
      fileUrl(path) {
        if (!path) {
          return "";
        }
        if (/^(?:https?:|blob:|data:|\/assets\/)/.test(path)) {
          return path;
        }
        return `${apiBase}/api/media?path=${encodeURIComponent(path)}`;
      },
      async openExternal(url) {
        window.open(url, "_blank", "noopener,noreferrer");
      },
    },
    musicCover: {
      async run(input, options) {
        const task = await requestJson<TaskSnapshot<MusicCoverRunResult>>(apiBase, "/api/music-cover/run", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      saveConfig: (input) =>
        requestJson(apiBase, "/api/music-cover/config", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      search: (input) =>
        requestJson<MusicCoverSearchResult>(apiBase, "/api/music-cover/search", {
          body: JSON.stringify(input),
          method: "POST",
        }),
    },
    plugins: {
      async appUpdateRun(input, options) {
        const task = await requestJson<TaskSnapshot<AppUpdateResult>>(apiBase, "/api/plugins/app-update/run", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      appUpdateInfo: () => requestJson<AppUpdateInfo>(apiBase, "/api/plugins/app-update/info"),
      async appUpdateTags() {
        const result = await requestJson<{ tags: string[] }>(apiBase, "/api/plugins/app-update/tags", {
          method: "POST",
        });
        return result.tags;
      },
      catalog: () => requestJson<PluginCatalogItem[]>(apiBase, "/api/plugins/registry"),
      async install(input, options) {
        const body = typeof input === "string" ? { id: input } : input;
        const task = await requestJson<TaskSnapshot<PluginManifest>>(apiBase, "/api/plugins/install", {
          body: JSON.stringify(body),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      getUi: (id) => requestJson<PluginUIDetail>(apiBase, `/api/plugins/${encodePath(id)}/ui`),
      list: () => requestJson<PluginManifest[]>(apiBase, "/api/plugins"),
      async repoTags(repo) {
        const result = await requestJson<{ tags: string[] }>(apiBase, "/api/plugins/repo-tags", {
          body: JSON.stringify({ repo }),
          method: "POST",
        });
        return result.tags;
      },
      runUiAction: (id, pageId, actionId, values) =>
        requestJson<PluginConfigActionResult>(
          apiBase,
          `/api/plugins/${encodePath(id)}/ui/${encodePath(pageId)}/actions/${encodePath(actionId)}`,
          { body: JSON.stringify({ values }), method: "POST" },
        ),
      saveUiConfig: (id, pageId, values) =>
        requestJson<PluginConfigSaveResult>(apiBase, `/api/plugins/${encodePath(id)}/ui/${encodePath(pageId)}/config`, {
          body: JSON.stringify({ values }),
          method: "POST",
        }),
      setEnabled: (id, enabled) =>
        requestJson<PluginManifest>(apiBase, `/api/plugins/${encodePath(id)}/enabled`, {
          body: JSON.stringify({ enabled }),
          method: "POST",
        }),
      uninstall: (id) =>
        requestJson<PluginUninstallResult>(apiBase, `/api/plugins/${encodePath(id)}`, {
          method: "DELETE",
        }),
    },
    mcp: {
      getConfig: () => requestJson<McpConfig>(apiBase, "/api/mcp/config"),
      async openConfigFile() {
        const result = await requestJson<{ path: string }>(apiBase, "/api/mcp/config/open", {
          body: JSON.stringify({}),
          method: "POST",
        });
        return result.path;
      },
      async previewTools(config, options) {
        const task = await requestJson<TaskSnapshot<McpToolPreview[]>>(apiBase, "/api/mcp/preview", {
          body: JSON.stringify({ config }),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      async saveAndApply(config, options) {
        const task = await requestJson<TaskSnapshot<McpConfig>>(apiBase, "/api/mcp/config/apply", {
          body: JSON.stringify({ config }),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
    },
    tasks: {
      get: <TResult = unknown>(id: string) =>
        requestJson<TaskSnapshot<TResult>>(apiBase, `/api/tasks/${encodePath(id)}`),
    },
    templates: {
      generate: (input) =>
        requestJson<TemplateSummary>(apiBase, "/api/templates/generate", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      getSession: () => requestJson<TemplateLaunchSession | null>(apiBase, "/api/templates/session"),
      list: () => requestJson<TemplateSummary[]>(apiBase, "/api/templates"),
      save: (template) =>
        requestJson<TemplateSummary>(apiBase, "/api/templates", {
          body: JSON.stringify({ template }),
          method: "POST",
        }),
      saveSession: (session) =>
        requestJson<TemplateLaunchSession>(apiBase, "/api/templates/session", {
          body: JSON.stringify(session),
          method: "POST",
        }),
    },
    tools: {
      async cropSprites(input, options) {
        const task = await requestJson<TaskSnapshot<BatchToolResult>>(apiBase, "/api/tools/sprites/crop", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      async generateSpritePrompts(input, options) {
        const task = await requestJson<TaskSnapshot<SpritePromptResult>>(apiBase, "/api/tools/sprite-prompts", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      async generateSprites(input, options) {
        const task = await requestJson<TaskSnapshot<SpriteGenerationResult>>(apiBase, "/api/tools/sprites/generate", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      async removeSpriteBackground(input, options) {
        const task = await requestJson<TaskSnapshot<BatchToolResult>>(apiBase, "/api/tools/sprites/remove-background", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
    },
  };
}
