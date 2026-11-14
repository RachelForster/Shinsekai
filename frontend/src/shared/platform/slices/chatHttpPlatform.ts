import type { ChatThemePayload } from "../../theme/chatChromeTheme";
import type { ChatThemeManifest, ChatThemeSummary } from "../../theme/chatTheme";
import { currentChatRendererId } from "../chatRenderer";
import type { HttpTransport } from "../httpTransport";
import type { StorySuggestion } from "../storyEditorTypes";
import type {
  ChatAttachmentInput,
  ChatCommand,
  ChatCommandResult,
  ChatHistoryEntry,
  ChatLaunchPayload,
  ChatPlatform,
  ChatReplaySnapshot,
  ChatReplayVoice,
  ChatRuntimeProcessState,
  ChatSnapshot,
  ChatStageEvent,
  ChatUpstreamCommand,
  StoryPlatform,
} from "./chatTypes";
import type { StoryGenerationTask } from "./storyTypes";
import type { TaskSnapshot } from "./taskTypes";

const CHAT_WEBSOCKET_HANDSHAKE_TIMEOUT_MS = 1500;

function buildChatViewerWebSocketUrl(wsUrl: string, sessionId: string, authToken = "") {
  const url = new URL(wsUrl);
  url.searchParams.set("sessionId", sessionId);
  url.searchParams.set("role", "viewer");
  url.searchParams.set("rendererId", currentChatRendererId());
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

function chatSnapshotPath(claimRenderer = true) {
  if (!claimRenderer) return "/api/chat/snapshot";
  return `/api/chat/snapshot?rendererId=${encodeURIComponent(currentChatRendererId())}`;
}

export function createChatHttpPlatform(transport: HttpTransport): ChatPlatform {
  const { authToken, bridgeUrl, encodePath, openBridgeWindow, requestJson, uploadFiles, waitForTask } = transport;

  return {
    close: (options) =>
      requestJson<ChatSnapshot>("/api/chat/close", {
        body: JSON.stringify({ expectedSessionId: options?.expectedSessionId }),
        keepalive: true,
        method: "POST",
      }),
    command: async (command: ChatCommand) => {
      let payload: ChatCommand =
        isRealtimeChatCommand(command) && !command.cmdId ? { ...command, cmdId: makeChatCommandId() } : command;
      if (payload.type === "audio-playback-signal" && payload.payload && typeof payload.payload === "object") {
        payload = {
          ...payload,
          payload: {
            ...payload.payload,
            rendererId: currentChatRendererId(),
          },
        };
      }
      const result = await requestJson<ChatCommandResult>("/api/chat/command", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      if (result.clipboardText != null) {
        await navigator.clipboard.writeText(result.clipboardText);
      }
      if (result.downloadUrl) {
        openBridgeWindow(result.downloadUrl);
      }
      return result;
    },
    getHistory: () => requestJson<ChatHistoryEntry[]>("/api/chat/history"),
    prepareReplay: async () => {
      const snapshot = await requestJson<ChatReplaySnapshot>("/api/chat/replay", {
        method: "POST",
        body: "{}",
      });
      // Persisted checkpoints contain portable API paths, never old host tokens.
      const rebase = (value: unknown): unknown => {
        if (typeof value === "string" && value.startsWith("/api/")) return bridgeUrl(value);
        if (Array.isArray(value)) return value.map(rebase);
        if (value && typeof value === "object")
          return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, rebase(v)]));
        return value;
      };
      return rebase(snapshot) as ChatReplaySnapshot;
    },
    getReplay: (id) => requestJson(`/api/chat/replay/${encodePath(id)}`),
    startReplay: async (id, startKey, endKey, generate) => {
      await requestJson(`/api/chat/replay/${encodePath(id)}/start`, {
        method: "POST",
        body: JSON.stringify({ startKey, endKey, generate }),
      });
    },
    generateReplayVoice: async (id, key, signal) => {
      const voice = await requestJson<ChatReplayVoice>(`/api/chat/replay/${encodePath(id)}/voice/${encodePath(key)}`, {
        method: "POST",
        body: "{}",
        signal,
      });
      return { ...voice, voiceUrls: voice.voiceUrls.map((url) => bridgeUrl(url)) };
    },
    cancelReplay: async (id) => {
      await requestJson(`/api/chat/replay/${encodePath(id)}`, { method: "DELETE" });
    },
    controlReplay: async (id, control) => {
      await requestJson(`/api/chat/replay/${encodePath(id)}/control`, {
        method: "POST",
        body: JSON.stringify(control),
      });
    },
    getHistoryVoice: async (voiceId) => {
      const { segmentCount } = await requestJson<{ segmentCount: number }>(
        `/api/chat/history-voice/${encodePath(voiceId)}`,
      );
      return Array.from({ length: segmentCount }, (_, index) =>
        bridgeUrl(`/api/chat/history-voice-file?voiceId=${encodeURIComponent(voiceId)}&segment=${index}`),
      );
    },
    listConversations: () => requestJson("/api/chat/conversations"),
    deleteConversation: async (id) => {
      await requestJson(`/api/chat/conversations/${encodePath(id)}`, { method: "DELETE" });
    },
    getCurrentConversation: () => requestJson("/api/chat/conversations/current"),
    async reconfigureConversation(conversationId, payload, options) {
      const task = await requestJson<TaskSnapshot<ChatSnapshot>>("/api/chat/init", {
        body: JSON.stringify({ mode: "reconfigure", conversationId, payload }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    prepareConversation: (id) => requestJson(`/api/chat/conversations/${encodePath(id)}/launch-payload`),
    renameConversation: (id, title) =>
      requestJson(`/api/chat/conversations/${encodePath(id)}/rename`, {
        method: "POST",
        body: JSON.stringify({ title }),
      }),
    getRuntimeStatus: () => requestJson<ChatRuntimeProcessState>("/api/chat/runtime-status"),
    getSnapshot: (options) => requestJson<ChatSnapshot>(chatSnapshotPath(options?.claimRenderer)),
    getTheme: () => requestJson<ChatThemePayload>("/api/chat/theme"),
    async launch(payload: ChatLaunchPayload, options) {
      const task = await requestJson<TaskSnapshot<ChatSnapshot>>("/api/chat/init", {
        body: JSON.stringify({ mode: "launch", payload }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    async resumeLast(options, overrides) {
      const task = await requestJson<TaskSnapshot<ChatSnapshot>>("/api/chat/init", {
        body: JSON.stringify({ mode: "resume-last", enableMobileAccess: overrides?.enableMobileAccess }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    subscribe(listener) {
      let stopped = false;
      let timeoutId = 0;

      const poll = async () => {
        try {
          const snapshot = await requestJson<ChatSnapshot>(chatSnapshotPath());
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
    listThemes: async () => {
      const themes = await requestJson<ChatThemeSummary[]>("/api/chat/themes");
      return themes.map((theme) => ({
        ...theme,
        previewUrl: theme.previewUrl ? bridgeUrl(theme.previewUrl) : undefined,
      }));
    },
    getThemeManifest: (id) => requestJson<ChatThemeManifest>(`/api/chat/themes/${encodePath(id)}`),
    getActiveThemeId: async () => {
      const result = await requestJson<{ id: string }>("/api/chat/themes/active");
      return result.id ?? "";
    },
    setActiveThemeId: async (id) => {
      await requestJson("/api/chat/themes/active", {
        body: JSON.stringify({ id }),
        method: "POST",
      });
    },
    uploadTheme: (file) => uploadFiles<ChatThemeSummary>("/api/chat/themes/upload", [file]),
    uploadAttachments: (files) =>
      uploadFiles<{ attachments: ChatAttachmentInput[] }>("/api/chat/attachments/upload", files),
    saveTheme: (input) =>
      requestJson<ChatThemeSummary>("/api/chat/themes/save", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    deleteTheme: async (id) => {
      await requestJson(`/api/chat/themes/${encodePath(id)}`, { method: "DELETE" });
    },
    subscribeEvents(listener) {
      let stopped = false;
      let timeoutId = 0;
      let connectTimeoutId = 0;
      let seq = 0;
      let socket: WebSocket | null = null;
      let lastEventSeq = 0;
      let currentSessionId = "";

      const emitSnapshot = (snapshot: ChatSnapshot) => {
        if (snapshot.sessionId && snapshot.sessionId !== currentSessionId) {
          currentSessionId = snapshot.sessionId;
          seq = 0;
          lastEventSeq = 0;
        }
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
        transportKind: "snapshot" | "websocket",
      ) => {
        const nextSeq = Math.max(seq, lastEventSeq);
        seq = Math.max(seq, nextSeq);
        listener({
          seq: nextSeq,
          state,
          transport: transportKind,
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
        const ws = new WebSocketCtor(buildChatViewerWebSocketUrl(snapshot.wsUrl, snapshot.sessionId, authToken()));
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
                void requestJson<ChatSnapshot>(chatSnapshotPath())
                  .then((nextSnapshot) => {
                    if (!stopped && socket === ws) {
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
          const snapshot = await requestJson<ChatSnapshot>(chatSnapshotPath());
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
          const snapshot = await requestJson<ChatSnapshot>(chatSnapshotPath());
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
  };
}

export function createStoryHttpPlatform(transport: HttpTransport): StoryPlatform {
  const { encodePath, requestJson, waitForTask } = transport;

  return {
    readDocument: (storyPath) =>
      requestJson("/api/story/editor/read", {
        body: JSON.stringify({ storyPath }),
        method: "POST",
      }),
    saveDocument: (input) =>
      requestJson("/api/story/editor/save", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    async suggestGraph(input) {
      const task = await requestJson<TaskSnapshot<StorySuggestion>>("/api/story/editor/suggest", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task);
    },
    list: () => requestJson("/api/story/library"),
    delete: async (storyPath) => {
      await requestJson("/api/story/library/delete", {
        body: JSON.stringify({ storyPath }),
        method: "POST",
      });
    },
    prepareLaunch: (storyPath, historyPath = "") =>
      requestJson("/api/story/launch-payload", {
        body: JSON.stringify({ storyPath, historyPath }),
        method: "POST",
      }),
    getPreview: (id) => requestJson(`/api/story/generation/${encodePath(id)}/preview`),
    startSession: (storyPath) =>
      requestJson("/api/story/start", {
        body: JSON.stringify({ storyPath }),
        method: "POST",
      }),
    cancelGeneration: (id) =>
      requestJson<StoryGenerationTask>(`/api/story/generation/${encodePath(id)}/cancel`, {
        body: JSON.stringify({}),
        method: "POST",
      }),
    getGeneration: (id) => requestJson<StoryGenerationTask>(`/api/story/generation/${encodePath(id)}`),
    async regenerateGeneration(id, stage, options) {
      const task = await requestJson<TaskSnapshot<StoryGenerationTask>>(
        `/api/story/generation/${encodePath(id)}/regenerate`,
        { body: JSON.stringify({ stage }), method: "POST" },
      );
      return waitForTask(task, options);
    },
    async resumeGeneration(id, options) {
      const task = await requestJson<TaskSnapshot<StoryGenerationTask>>(
        `/api/story/generation/${encodePath(id)}/resume`,
        { body: JSON.stringify({}), method: "POST" },
      );
      return waitForTask(task, options);
    },
    async startGeneration(input, options) {
      const task = await requestJson<TaskSnapshot<StoryGenerationTask>>("/api/story/generation/start", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task, options);
    },
  };
}
