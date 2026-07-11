import type { ChatThemePayload } from "../theme/chatChromeTheme";
import type { ChatThemeManifest, ChatThemeSummary } from "../theme/chatTheme";
import {
  isTauriDesktop,
  isDesktopBridgeRestarting,
  openDesktopExternalUrl,
  waitForDesktopBridgeRestart,
  writeDesktopRestartDebugLog,
} from "../desktop/desktopApi";
import type {
  ApiConfig,
  AppConfig,
  AppUpdateInfo,
  AppUpdateResult,
  ChatCommand,
  ChatCommandResult,
  ChatHistoryEntry,
  ChatLaunchPayload,
  ChatRuntimeProcessState,
  ChatSnapshot,
  ChatUpstreamCommand,
  BatchToolResult,
  Background,
  BackgroundTranslateResult,
  Character,
  CharacterMemory,
  CharacterMemoryImportPreview,
  CharacterMemoryImportResult,
  CharacterMemoryList,
  CharacterSettingResult,
  Mem0Status,
  CharacterTranslateResult,
  DiagnosticBundleResult,
  Effect,
  FileBrowserSnapshot,
  LogFileList,
  LogSnapshot,
  LlmModelOption,
  LlmConnectionTestResult,
  McpConfig,
  McpToolPreview,
  ModelAssetDownloadResult,
  ModelAssetStatus,
  MusicCoverRunResult,
  MusicCoverSearchResult,
  NetworkProxyDetectionResult,
  PluginCatalogItem,
  PluginConfigActionResult,
  PluginConfigSaveResult,
  PluginManifest,
  PluginLocalScanResult,
  PluginSubmissionClipboardResult,
  PluginSubmissionInput,
  PluginSubmissionIssueResult,
  PluginSubmissionValidationResult,
  PluginUninstallResult,
  PluginUIDetail,
  RuntimeDependencyInstallResult,
  ChatStageEvent,
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

const bridgeAuthTokens = new Map<string, string>();

function normalizedBaseUrl(baseUrl: string) {
  return baseUrl.replace(/\/$/, "");
}

function rememberBridgeAuthToken(baseUrl: string, authToken?: string) {
  const token = authToken?.trim() ?? "";
  const key = normalizedBaseUrl(baseUrl);
  if (token) {
    bridgeAuthTokens.set(key, token);
  } else {
    bridgeAuthTokens.delete(key);
  }
}

function bridgeAuthToken(baseUrl: string) {
  return bridgeAuthTokens.get(normalizedBaseUrl(baseUrl)) ?? "";
}

function bridgeAuthHeaders(baseUrl: string): Record<string, string> {
  const token = bridgeAuthToken(baseUrl);
  return token ? { "X-Shinsekai-Bridge-Token": token } : {};
}

function headersRecord(headers?: HeadersInit): Record<string, string> {
  if (!headers) {
    return {};
  }
  if (typeof Headers !== "undefined" && headers instanceof Headers) {
    const result: Record<string, string> = {};
    headers.forEach((value, key) => {
      result[key] = value;
    });
    return result;
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers.map(([key, value]) => [key, value]));
  }
  return { ...(headers as Record<string, string>) };
}

function appendBridgeAuthQuery(baseUrl: string, pathOrUrl: string) {
  const token = bridgeAuthToken(baseUrl);
  if (!token) {
    return pathOrUrl;
  }
  const separator = pathOrUrl.includes("?") ? "&" : "?";
  return `${pathOrUrl}${separator}shinsekai_bridge_token=${encodeURIComponent(token)}`;
}

function bridgeUrl(baseUrl: string, path: string) {
  const base = new URL(baseUrl);
  const url = new URL(appendBridgeAuthQuery(baseUrl, path), base);
  if (url.origin !== base.origin) {
    throw new Error("Bridge URL must stay on the active bridge origin");
  }
  return url.toString();
}

function normalizeCharacterMemoryRow(row: unknown): CharacterMemory {
  if (row && typeof row === "object") {
    const record = row as Record<string, unknown>;
    return {
      id: String(record.id ?? ""),
      memory: String(record.memory ?? record.content ?? record.text ?? ""),
    };
  }
  return { id: "", memory: String(row ?? "") };
}

function normalizeCharacterMemoryList(payload: unknown, fallbackAgentId: string): CharacterMemoryList {
  const record = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const rawMemories = Array.isArray(record.memories)
    ? record.memories
    : Array.isArray(record.results)
      ? record.results
      : [];
  const memories = rawMemories.map(normalizeCharacterMemoryRow);
  return {
    agentId: String(record.agentId ?? record.agent_id ?? (fallbackAgentId || "user")),
    count: typeof record.count === "number" ? record.count : memories.length,
    memories,
  };
}

function openBridgeWindow(apiBase: string, path: string) {
  const url = bridgeUrl(apiBase, path);
  window.open(url, "_blank", "noopener,noreferrer");
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const requestHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...bridgeAuthHeaders(baseUrl),
    ...headersRecord(init?.headers),
  };
  const requestInit: RequestInit = {
    ...init,
    headers: requestHeaders,
  };
  const response = await fetchWithStartupRetry(`${baseUrl}${path}`, requestInit);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return data as T;
}

async function fetchWithStartupRetry(url: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const retryable = method === "GET" || method === "HEAD";
  const maxRetryAttempts = retryable ? 15 : 1;
  let lastError: unknown;
  let attempt = 0;
  let waitedForBridgeRestart = false;
  for (;;) {
    try {
      return await fetch(url, init);
    } catch (error) {
      lastError = error;
      if (isDesktopBridgeRestarting() && isTransientBridgeError(error) && !waitedForBridgeRestart) {
        waitedForBridgeRestart = true;
        logBridgeRestartRetry(method, url, error);
        await waitForDesktopBridgeRestart();
        continue;
      }
      if (isDesktopRestarting() && isTransientBridgeError(error)) {
        logSuppressedRestartError(method, url, error);
        return waitForRestartExit();
      }
      if (!retryable || !isTransientBridgeError(error)) {
        if (isTransientBridgeError(error)) {
          logThrownBridgeError(method, url, error);
        }
        throw error;
      }
      if (attempt + 1 >= maxRetryAttempts) {
        break;
      }
      attempt += 1;
      await delay(200 + attempt * 150);
    }
  }
  if (isTransientBridgeError(lastError)) {
    logThrownBridgeError(method, url, lastError);
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

function isTransientBridgeError(error: unknown) {
  const message = errorMessage(error);
  return /127\.0\.0\.1|localhost|connection refused|could not connect|failed to fetch|network/i.test(message);
}

async function requestForm<T>(baseUrl: string, path: string, formData: FormData): Promise<T> {
  const url = `${baseUrl}${path}`;
  const headers = bridgeAuthHeaders(baseUrl);
  const init: RequestInit = {
    body: formData,
    method: "POST",
  };
  if (Object.keys(headers).length) {
    init.headers = headers;
  }
  const response = await fetch(url, init).catch(async (error) => {
    if (isDesktopBridgeRestarting() && isTransientBridgeError(error)) {
      logBridgeRestartRetry("POST", url, error);
      await waitForDesktopBridgeRestart();
      return fetch(url, init);
    }
    if (isDesktopRestarting() && isTransientBridgeError(error)) {
      logSuppressedRestartError("POST", url, error);
      return waitForRestartExit();
    }
    throw error;
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
  openBridgeWindow(apiBase, `/api/download?path=${encodeURIComponent(path)}`);
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isDesktopRestarting() {
  return typeof window !== "undefined" && window.__SHINSEKAI_RESTARTING__ === true;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function waitForRestartExit(): Promise<never> {
  return new Promise(() => {});
}

function logSuppressedRestartError(method: string, url: string, error: unknown) {
  void writeDesktopRestartDebugLog(
    `httpPlatform suppressed restart disconnect method=${method} url=${sanitizeRestartLogUrl(url)} error=${errorMessage(
      error,
    )}`,
  );
}

function logThrownBridgeError(method: string, url: string, error: unknown) {
  void writeDesktopRestartDebugLog(
    `httpPlatform throwing bridge error method=${method} url=${sanitizeRestartLogUrl(url)} restarting=${isDesktopRestarting()} error=${errorMessage(
      error,
    )}`,
  );
}

function logBridgeRestartRetry(method: string, url: string, error: unknown) {
  void writeDesktopRestartDebugLog(
    `httpPlatform waiting for bridge restart method=${method} url=${sanitizeRestartLogUrl(url)} error=${errorMessage(
      error,
    )}`,
  );
}

function sanitizeRestartLogUrl(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function buildChatViewerWebSocketUrl(wsUrl: string, sessionId: string, authToken = "") {
  const url = new URL(wsUrl);
  url.searchParams.set("sessionId", sessionId);
  url.searchParams.set("role", "viewer");
  if (authToken.trim()) {
    url.searchParams.set("shinsekai_bridge_token", authToken.trim());
  }
  return url.toString();
}

function isRealtimeChatCommand(command: ChatCommand): command is ChatUpstreamCommand {
  return command.type !== "copy-history" && command.type !== "open-history";
}

function makeChatCommandId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `cmd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const CHAT_WEBSOCKET_HANDSHAKE_TIMEOUT_MS = 1500;

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

export function createHttpPlatform(baseUrl: string, authToken = ""): ShinsekaiPlatform {
  const apiBase = normalizedBaseUrl(baseUrl);
  rememberBridgeAuthToken(apiBase, authToken);

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
    effects: {
      delete: async (name) => {
        await requestJson(apiBase, `/api/effects/${encodePath(name)}`, { method: "DELETE" });
      },
      deleteAllAudio: (name) =>
        requestJson<Effect>(apiBase, "/api/effects/audio/delete-all", {
          body: JSON.stringify({ name }),
          method: "POST",
        }),
      deleteAudio: (name, index) =>
        requestJson<Effect>(apiBase, "/api/effects/audio/delete", {
          body: JSON.stringify({ index, name }),
          method: "POST",
        }),
      export: async (name) => {
        const result = await requestJson<{ downloadUrl: string; path: string }>(apiBase, "/api/effects/export", {
          body: JSON.stringify({ name }),
          method: "POST",
        });
        openDownload(apiBase, result.path);
        return result.path;
      },
      import: (items) => {
        if (isFileList(items)) {
          return uploadFiles<Effect[]>(apiBase, "/api/effects/import-upload", items);
        }
        return requestJson<Effect[]>(apiBase, "/api/effects/import", {
          body: JSON.stringify({ paths: items }),
          method: "POST",
        });
      },
      list: () => requestJson<Effect[]>(apiBase, "/api/effects"),
      save: (effect, originalName) =>
        requestJson<Effect>(apiBase, "/api/effects", {
          body: JSON.stringify({ effect, originalName }),
          method: "POST",
        }),
      saveAudioTags: (input) =>
        requestJson<Effect>(apiBase, "/api/effects/audio-tags", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      uploadAudio: (input) =>
        requestJson<Effect>(apiBase, "/api/effects/audio/upload", {
          body: JSON.stringify(input),
          method: "POST",
        }),
    },
    chat: {
      close: () =>
        requestJson<ChatSnapshot>(apiBase, "/api/chat/close", {
          body: JSON.stringify({}),
          keepalive: true,
          method: "POST",
        }),
      command: async (command: ChatCommand) => {
        const payload =
          isRealtimeChatCommand(command) && !command.cmdId ? { ...command, cmdId: makeChatCommandId() } : command;
        const result = await requestJson<ChatCommandResult>(apiBase, "/api/chat/command", {
          body: JSON.stringify(payload),
          method: "POST",
        });
        if (result.clipboardText != null) {
          await navigator.clipboard.writeText(result.clipboardText);
        }
        if (result.downloadUrl) {
          openBridgeWindow(apiBase, result.downloadUrl);
        }
        return result;
      },
      getHistory: () => requestJson<ChatHistoryEntry[]>(apiBase, "/api/chat/history"),
      getRuntimeStatus: () => requestJson<ChatRuntimeProcessState>(apiBase, "/api/chat/runtime-status"),
      getSnapshot: () => requestJson<ChatSnapshot>(apiBase, "/api/chat/snapshot"),
      getTheme: () => requestJson<ChatThemePayload>(apiBase, "/api/chat/theme"),
      async launch(payload: ChatLaunchPayload, options) {
        const task = await requestJson<TaskSnapshot<ChatSnapshot>>(apiBase, "/api/chat/init", {
          body: JSON.stringify({ mode: "launch", payload }),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      async resumeLast(options) {
        const task = await requestJson<TaskSnapshot<ChatSnapshot>>(apiBase, "/api/chat/init", {
          body: JSON.stringify({ mode: "resume-last" }),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
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
      listThemes: () => requestJson<ChatThemeSummary[]>(apiBase, "/api/chat/themes"),
      getThemeManifest: (id) => requestJson<ChatThemeManifest>(apiBase, `/api/chat/themes/${encodePath(id)}`),
      getActiveThemeId: async () => {
        const result = await requestJson<{ id: string }>(apiBase, "/api/chat/themes/active");
        return result.id ?? "";
      },
      setActiveThemeId: async (id) => {
        await requestJson(apiBase, "/api/chat/themes/active", {
          body: JSON.stringify({ id }),
          method: "POST",
        });
      },
      uploadTheme: (file) => uploadFiles<ChatThemeSummary>(apiBase, "/api/chat/themes/upload", [file]),
      deleteTheme: async (id) => {
        await requestJson(apiBase, `/api/chat/themes/${encodePath(id)}`, { method: "DELETE" });
      },
      subscribeEvents(listener) {
        let stopped = false;
        let timeoutId = 0;
        let connectTimeoutId = 0;
        let seq = 0;
        let socket: WebSocket | null = null;
        let lastEventSeq = 0;

        const emitSnapshot = (snapshot: ChatSnapshot) => {
          const snapshotSeq =
            typeof snapshot.eventSeq === "number" && Number.isFinite(snapshot.eventSeq) ? snapshot.eventSeq : 0;
          const event: ChatStageEvent = {
            seq: Math.max(seq, lastEventSeq, snapshotSeq),
            snapshot,
            ts: Date.now(),
            type: "snapshot",
            v: 1,
          };
          lastEventSeq = Math.max(lastEventSeq, snapshotSeq);
          seq = Math.max(seq, event.seq);
          listener(event);
        };

        const emitTransportState = (
          state: "connected" | "connecting" | "polling" | "reconnecting",
          transport: "snapshot" | "websocket",
        ) => {
          const nextSeq = Math.max(seq, lastEventSeq);
          seq = Math.max(seq, nextSeq);
          listener({
            seq: nextSeq,
            state,
            transport,
            ts: Date.now(),
            type: "transport.state",
            v: 1,
          });
        };

        const closeSocket = () => {
          window.clearTimeout(connectTimeoutId);
          connectTimeoutId = 0;
          if (!socket) {
            return;
          }
          socket.onclose = null;
          socket.onerror = null;
          socket.onmessage = null;
          try {
            socket.close();
          } catch {
            // ignore
          }
          socket = null;
        };

        const connectWebSocket = (snapshot: ChatSnapshot) => {
          const WebSocketCtor = globalThis.WebSocket;
          if (!snapshot.wsUrl || !snapshot.sessionId || typeof WebSocketCtor === "undefined") {
            emitTransportState("polling", "snapshot");
            return false;
          }
          closeSocket();
          let websocketConnected = false;
          const ws = new WebSocketCtor(
            buildChatViewerWebSocketUrl(snapshot.wsUrl, snapshot.sessionId, bridgeAuthToken(apiBase)),
          );
          socket = ws;
          connectTimeoutId = window.setTimeout(() => {
            if (stopped || socket !== ws || websocketConnected) {
              return;
            }
            closeSocket();
            emitTransportState("polling", "snapshot");
            timeoutId = window.setTimeout(poll, 0);
          }, CHAT_WEBSOCKET_HANDSHAKE_TIMEOUT_MS);
          ws.onopen = () => {
            if (websocketConnected) {
              return;
            }
            websocketConnected = true;
            window.clearTimeout(connectTimeoutId);
            connectTimeoutId = 0;
            emitTransportState("connected", "websocket");
          };
          ws.onmessage = (message) => {
            try {
              if (!websocketConnected) {
                websocketConnected = true;
                window.clearTimeout(connectTimeoutId);
                connectTimeoutId = 0;
                emitTransportState("connected", "websocket");
              }
              const parsed = JSON.parse(String(message.data ?? ""));
              if (!parsed || typeof parsed !== "object" || typeof parsed.type !== "string") {
                return;
              }
              if (typeof parsed.seq === "number") {
                if (lastEventSeq > 0 && parsed.seq > lastEventSeq + 1) {
                  void requestJson<ChatSnapshot>(apiBase, "/api/chat/snapshot")
                    .then((nextSnapshot) => {
                      if (!stopped) {
                        emitSnapshot(nextSnapshot);
                      }
                    })
                    .catch(() => {
                      // ignore gap recovery failure; normal reconnect path will retry
                    });
                }
                lastEventSeq = Math.max(lastEventSeq, parsed.seq);
              }
              listener(parsed as ChatStageEvent);
            } catch {
              // ignore malformed websocket payloads
            }
          };
          ws.onerror = () => {
            try {
              ws.close();
            } catch {
              // ignore
            }
          };
          ws.onclose = () => {
            if (socket === ws) {
              socket = null;
            }
            websocketConnected = false;
            window.clearTimeout(connectTimeoutId);
            connectTimeoutId = 0;
            if (!stopped) {
              emitTransportState("reconnecting", "websocket");
              timeoutId = window.setTimeout(connectFromSnapshot, 800);
            }
          };
          return true;
        };

        const poll = async () => {
          try {
            const snapshot = await requestJson<ChatSnapshot>(apiBase, "/api/chat/snapshot");
            if (!stopped) {
              emitSnapshot(snapshot);
              if (connectWebSocket(snapshot)) {
                return;
              }
            }
          } finally {
            if (!stopped && socket == null) {
              emitTransportState("polling", "snapshot");
              timeoutId = window.setTimeout(poll, 1400);
            }
          }
        };

        const connectFromSnapshot = async () => {
          try {
            const snapshot = await requestJson<ChatSnapshot>(apiBase, "/api/chat/snapshot");
            if (stopped) {
              return;
            }
            emitSnapshot(snapshot);
            if (!connectWebSocket(snapshot)) {
              timeoutId = window.setTimeout(poll, 1400);
            }
          } catch {
            if (!stopped) {
              emitTransportState("polling", "snapshot");
              timeoutId = window.setTimeout(poll, 1400);
            }
          }
        };

        void connectFromSnapshot();
        return () => {
          stopped = true;
          window.clearTimeout(timeoutId);
          window.clearTimeout(connectTimeoutId);
          closeSocket();
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
      getMem0Status: () =>
        requestJson<Mem0Status>(apiBase, "/api/characters/memories/status", {
          body: "{}",
          method: "POST",
        }),
      importMemories: async (name, items, options) => {
        const task = await uploadFiles<TaskSnapshot<CharacterMemoryImportResult>>(
          apiBase,
          `/api/characters/memories/import-upload?name=${encodeURIComponent(name)}`,
          items,
        );
        return waitForTask(apiBase, task, options);
      },
      list: () => requestJson<Character[]>(apiBase, "/api/characters"),
      listMemories: (name) =>
        requestJson<CharacterMemoryList>(apiBase, "/api/characters/memories/list", {
          body: JSON.stringify({ name }),
          method: "POST",
        }),
      previewMemoryImport: (name, items) => {
        return uploadFiles<CharacterMemoryImportPreview>(
          apiBase,
          `/api/characters/memories/import-preview-upload?name=${encodeURIComponent(name)}`,
          items,
        );
      },
      searchMemories: async ({ limit = 200, name, query }) => {
        const result = await requestJson<unknown>(apiBase, "/api/memory/search", {
          body: JSON.stringify({ characterName: name, limit, query }),
          method: "POST",
        });
        return normalizeCharacterMemoryList(result, name);
      },
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
      saveSpriteVoiceType: (name, spriteIndex, voiceType) =>
        requestJson<Character>(apiBase, "/api/characters/sprite-voice/voice-type", {
          body: JSON.stringify({ name, spriteIndex, voiceType }),
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
      testLlmConnection: (input) =>
        requestJson<LlmConnectionTestResult>(apiBase, "/api/config/llm-connection-test", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      get: () => requestJson<AppConfig>(apiBase, "/api/config"),
      detectNetworkProxy: () => requestJson<NetworkProxyDetectionResult>(apiBase, "/api/config/network-proxy/detect"),
      getMemoryStatus: (options) =>
        requestJson<Mem0Status>(apiBase, "/api/memory/status", {
          body: JSON.stringify({ startLoading: options?.startLoading ?? true }),
          method: "POST",
        }),
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
    modelAssets: {
      async download(input, options) {
        const task = await requestJson<TaskSnapshot<ModelAssetDownloadResult>>(apiBase, "/api/model-assets/download", {
          body: JSON.stringify(input),
          method: "POST",
        });
        return waitForTask(apiBase, task, options);
      },
      status: (input) =>
        requestJson<ModelAssetStatus>(apiBase, "/api/model-assets/status", {
          body: JSON.stringify(input),
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
        return bridgeUrl(apiBase, `/api/media?path=${encodeURIComponent(path)}`);
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
        }>(apiBase, "/api/media/thumbnails", {
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
                  return [
                    item.path,
                    bridgeUrl(apiBase, `/api/media?path=${encodeURIComponent(item.cachePath)}`),
                  ] as const;
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
        return bridgeUrl(apiBase, `/api/media/thumbnail?${params.toString()}`);
      },
      async openExternal(url) {
        if (isTauriDesktop()) {
          await openDesktopExternalUrl(url);
          return;
        }
        window.open(url, "_blank", "noopener,noreferrer");
      },
    },
    logs: {
      exportDiagnostics: () =>
        requestJson<DiagnosticBundleResult>(apiBase, "/api/logs/diagnostic-bundle", { method: "POST" }),
      getDefault: () => requestJson<LogSnapshot>(apiBase, "/api/logs/default"),
      import: (items) => {
        if (isFileList(items)) {
          return uploadFiles<LogSnapshot>(apiBase, "/api/logs/import-upload", items);
        }
        return requestJson<LogSnapshot>(apiBase, "/api/logs/read", {
          body: JSON.stringify({ path: items[0] ?? "" }),
          method: "POST",
        });
      },
      list: () => requestJson<LogFileList>(apiBase, "/api/logs"),
    },
    runtime: {
      async installMissingDependency(input, options) {
        const task = await requestJson<TaskSnapshot<RuntimeDependencyInstallResult>>(
          apiBase,
          "/api/runtime/install-missing-dependency",
          {
            body: JSON.stringify(input),
            method: "POST",
          },
        );
        return waitForTask(apiBase, task, options);
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
      scanLocal: (input) =>
        requestJson<PluginLocalScanResult>(apiBase, "/api/plugins/publisher/scan", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      validateSubmission: (input: PluginSubmissionInput) =>
        requestJson<PluginSubmissionValidationResult>(apiBase, "/api/plugins/publisher/validate", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      buildSubmissionIssueUrl: (input: PluginSubmissionInput) =>
        requestJson<PluginSubmissionIssueResult>(apiBase, "/api/plugins/publisher/issue-url", {
          body: JSON.stringify(input),
          method: "POST",
        }),
      async copySubmissionJson(input: PluginSubmissionInput) {
        const result = await requestJson<PluginSubmissionClipboardResult>(apiBase, "/api/plugins/publisher/copy-json", {
          body: JSON.stringify(input),
          method: "POST",
        });
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(result.clipboardText);
        }
        return result;
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
