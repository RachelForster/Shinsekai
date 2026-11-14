import { isTauriDesktop, openDesktopExternalUrl } from "../../desktop/desktopApi";
import type { HttpTransport } from "../httpTransport";
import type {
  DiagnosticBundleResult,
  FileBrowserSnapshot,
  FilesPlatform,
  ImageAutoLabelResult,
  LogFileList,
  LogSnapshot,
  LogsPlatform,
  TaskSnapshot,
  TasksPlatform,
} from "./taskTypes";
import type {
  Background,
  BackgroundsPlatform,
  BackgroundTranslateResult,
  BatchToolResult,
  Effect,
  EffectsPlatform,
  SpriteGenerationResult,
  SpritePromptResult,
  TemplateGenerationResult,
  TemplateLaunchSession,
  TemplatesPlatform,
  TemplateSummary,
  ToolsPlatform,
} from "./workspaceTypes";

export function createBackgroundsHttpPlatform(transport: HttpTransport): BackgroundsPlatform {
  const { encodePath, exportPackage, isFileList, requestJson, uploadFiles, waitForTask } = transport;

  return {
    delete: async (name) => {
      await requestJson(`/api/backgrounds/${encodePath(name)}`, { method: "DELETE" });
    },
    autoLabelImages: async (name, options) => {
      const task = await requestJson<TaskSnapshot<ImageAutoLabelResult>>("/api/backgrounds/images/auto-label", {
        body: JSON.stringify({ name }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    deleteAllBgm: (name) =>
      requestJson<Background>("/api/backgrounds/bgm/delete-all", {
        body: JSON.stringify({ name }),
        method: "POST",
      }),
    deleteAllImages: (name) =>
      requestJson<Background>("/api/backgrounds/images/delete-all", {
        body: JSON.stringify({ name }),
        method: "POST",
      }),
    deleteBgm: (name, index) =>
      requestJson<Background>("/api/backgrounds/bgm/delete", {
        body: JSON.stringify({ index, name }),
        method: "POST",
      }),
    deleteImage: (name, index) =>
      requestJson<Background>("/api/backgrounds/images/delete", {
        body: JSON.stringify({ index, name }),
        method: "POST",
      }),
    export: (name) => exportPackage("backgrounds", name),
    import: (items) => {
      if (isFileList(items)) {
        return uploadFiles<Background[]>("/api/backgrounds/import-upload", items);
      }
      return requestJson<Background[]>("/api/backgrounds/import", {
        body: JSON.stringify({ paths: items }),
        method: "POST",
      });
    },
    list: () => requestJson<Background[]>("/api/backgrounds"),
    save: (background, originalName) =>
      requestJson<Background>("/api/backgrounds", {
        body: JSON.stringify({ background, originalName }),
        method: "POST",
      }),
    saveBgmTags: (input) =>
      requestJson<Background>("/api/backgrounds/bgm-tags", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    saveImageTags: (input) =>
      requestJson<Background>("/api/backgrounds/tags", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    translateFields: (input) =>
      requestJson<BackgroundTranslateResult>("/api/backgrounds/translate", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadBgm: (input) =>
      requestJson<Background>("/api/backgrounds/bgm/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadImages: (input) =>
      requestJson<Background>("/api/backgrounds/images/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
  };
}

export function createEffectsHttpPlatform(transport: HttpTransport): EffectsPlatform {
  const { encodePath, exportPackage, isFileList, requestJson, uploadFiles } = transport;

  return {
    delete: async (name) => {
      await requestJson(`/api/effects/${encodePath(name)}`, { method: "DELETE" });
    },
    deleteAllAudio: (name) =>
      requestJson<Effect>("/api/effects/audio/delete-all", {
        body: JSON.stringify({ name }),
        method: "POST",
      }),
    deleteAudio: (name, index) =>
      requestJson<Effect>("/api/effects/audio/delete", {
        body: JSON.stringify({ index, name }),
        method: "POST",
      }),
    deleteImage: (name, index) =>
      requestJson<Effect>("/api/effects/images/delete", {
        body: JSON.stringify({ index, name }),
        method: "POST",
      }),
    export: (name) => exportPackage("effects", name),
    import: (items) => {
      if (isFileList(items)) {
        return uploadFiles<Effect[]>("/api/effects/import-upload", items);
      }
      return requestJson<Effect[]>("/api/effects/import", {
        body: JSON.stringify({ paths: items }),
        method: "POST",
      });
    },
    list: () => requestJson<Effect[]>("/api/effects"),
    save: (effect, originalName) =>
      requestJson<Effect>("/api/effects", {
        body: JSON.stringify({ effect, originalName }),
        method: "POST",
      }),
    saveAudioTags: (input) =>
      requestJson<Effect>("/api/effects/audio-tags", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    saveImageTags: (input) =>
      requestJson<Effect>("/api/effects/image-tags", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadAudio: (input) =>
      requestJson<Effect>("/api/effects/audio/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadImages: (input) =>
      requestJson<Effect>("/api/effects/images/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadImageAudio: (input) =>
      requestJson<Effect>("/api/effects/images/audio/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
  };
}

export function createFilesHttpPlatform(transport: HttpTransport): FilesPlatform {
  const { bridgeUrl, requestJson } = transport;

  return {
    openT2iWorkflowFolder() {
      return requestJson<{ path: string }>("/api/files/t2i-workflows/open", { method: "POST" });
    },
    browse(options) {
      return requestJson<FileBrowserSnapshot>("/api/files/browse", {
        body: JSON.stringify(options ?? {}),
        method: "POST",
      });
    },
    fileUrl(path) {
      if (!path) {
        return "";
      }
      if (path.startsWith("/api/")) return bridgeUrl(path);
      if (/^(?:https?:|blob:|data:|\/assets\/)/.test(path)) {
        return path;
      }
      return bridgeUrl(`/api/media?path=${encodeURIComponent(path)}`);
    },
    modelUrl(modelPath, path) {
      return bridgeUrl(`/api/avatar/file?model_path=${encodeURIComponent(modelPath)}&path=${encodeURIComponent(path)}`);
    },
    async thumbnailBatch(paths, options) {
      const localPaths = paths.filter((path) => path && !/^(?:https?:|blob:|data:|\/assets\/)/.test(path));
      const directEntries = paths
        .filter((path) => /^(?:https?:|blob:|data:|\/assets\/)/.test(path))
        .map((path) => [path, path] as const);
      if (!localPaths.length) {
        return Object.fromEntries(directEntries);
      }
      const response = await requestJson<{
        items: Array<{ cachePath?: string; dataUrl?: string; path: string }>;
      }>("/api/media/thumbnails", {
        body: JSON.stringify({
          mode: options?.delivery === "data" ? "data" : "url",
          paths: [...new Set(localPaths)],
          size: options?.size ?? 160,
        }),
        method: "POST",
      });
      const preferDataUrl = options?.delivery === "data";
      return {
        ...Object.fromEntries(directEntries),
        ...Object.fromEntries(
          response.items
            .map((item) => {
              if (preferDataUrl && item.dataUrl) {
                return [item.path, item.dataUrl] as const;
              }
              if (item.cachePath) {
                return [item.path, bridgeUrl(`/api/media?path=${encodeURIComponent(item.cachePath)}`)] as const;
              }
              if (item.dataUrl) {
                return [item.path, item.dataUrl] as const;
              }
              return null;
            })
            .filter((entry): entry is readonly [string, string] => entry !== null),
        ),
      };
    },
    thumbnailUrl(path, options) {
      if (!path) {
        return "";
      }
      if (/^(?:https?:|blob:|data:|\/assets\/)/.test(path)) {
        return path;
      }
      const params = new URLSearchParams({ path });
      if (options?.size) {
        params.set("size", String(options.size));
      }
      return bridgeUrl(`/api/media/thumbnail?${params.toString()}`);
    },
    async openExternal(url) {
      if (isTauriDesktop()) {
        await openDesktopExternalUrl(url);
        return;
      }
      window.open(url, "_blank", "noopener,noreferrer");
    },
  };
}

export function createLogsHttpPlatform(transport: HttpTransport): LogsPlatform {
  const { isFileList, requestJson, uploadFiles } = transport;

  return {
    exportDiagnostics: () => requestJson<DiagnosticBundleResult>("/api/logs/diagnostic-bundle", { method: "POST" }),
    getDefault: () => requestJson<LogSnapshot>("/api/logs/default"),
    import: (items) => {
      if (isFileList(items)) {
        return uploadFiles<LogSnapshot>("/api/logs/import-upload", items);
      }
      return requestJson<LogSnapshot>("/api/logs/read", {
        body: JSON.stringify({ path: items[0] ?? "" }),
        method: "POST",
      });
    },
    list: () => requestJson<LogFileList>("/api/logs"),
  };
}

export function createTasksHttpPlatform(transport: HttpTransport): TasksPlatform {
  const { encodePath, requestJson } = transport;

  return {
    get: <TResult = unknown>(id: string) => requestJson<TaskSnapshot<TResult>>(`/api/tasks/${encodePath(id)}`),
  };
}

export function createTemplatesHttpPlatform(transport: HttpTransport): TemplatesPlatform {
  const { requestJson } = transport;

  return {
    generate: (input) =>
      requestJson<TemplateGenerationResult>("/api/templates/generate", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    getSession: () => requestJson<TemplateLaunchSession | null>("/api/templates/session"),
    list: () => requestJson<TemplateSummary[]>("/api/templates"),
    save: (template) =>
      requestJson<TemplateSummary>("/api/templates", {
        body: JSON.stringify({ template }),
        method: "POST",
      }),
    saveSession: (session) =>
      requestJson<TemplateLaunchSession>("/api/templates/session", {
        body: JSON.stringify(session),
        method: "POST",
      }),
  };
}

export function createToolsHttpPlatform(transport: HttpTransport): ToolsPlatform {
  const { requestJson, waitForTask } = transport;

  return {
    async cropSprites(input, options) {
      const task = await requestJson<TaskSnapshot<BatchToolResult>>("/api/tools/sprites/crop", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    async generateSpritePrompts(input, options) {
      const task = await requestJson<TaskSnapshot<SpritePromptResult>>("/api/tools/sprite-prompts", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    async generateSprites(input, options) {
      const task = await requestJson<TaskSnapshot<SpriteGenerationResult>>("/api/tools/sprites/generate", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    async removeSpriteBackground(input, options) {
      const task = await requestJson<TaskSnapshot<BatchToolResult>>("/api/tools/sprites/remove-background", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
  };
}
