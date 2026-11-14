import { DEFAULT_CHAT_THEME_ID, type ChatThemeManifest, type ChatThemeSummary } from "../../theme/chatTheme";
import { runtimeStatusFromSnapshot } from "../chatRuntimeStatus";
import { PlatformRequestError } from "../errors";
import { sampleChatSnapshot, sampleChatThemeManifests } from "../sampleData";
import type {
  ChatConversationBranch,
  ChatHistoryEntry,
  ChatPlatform,
  ChatReplaySnapshot,
  ChatSendPayload,
  ChatSnapshot,
} from "./chatTypes";
import {
  type BrowserPreviewContext,
  clone,
  delay,
  previewTask,
  previewThemePayloadFromManifest,
} from "./previewContext";

function cloneHistoryEntries(entries: ChatHistoryEntry[] | undefined): ChatHistoryEntry[] {
  return (entries ?? []).map((entry) => ({ ...entry }));
}

function browserPreviewChatPayload(payload: unknown) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    const text = String(payload ?? "").trim();
    return { displayText: text, text };
  }
  const candidate = payload as Partial<ChatSendPayload>;
  const text = String(candidate.text ?? "").trim();
  const labels = Array.isArray(candidate.attachments)
    ? candidate.attachments
        .filter((attachment) => attachment?.kind === "image" || attachment?.kind === "file")
        .map((attachment) => `[${attachment.kind}: ${String(attachment.name || "attachment")}]`)
    : [];
  return { displayText: [text, labels.join(" ")].filter(Boolean).join("\n"), text };
}

function isPreviewRealtimeCommand(command: { type: string }) {
  return command.type !== "copy-history" && command.type !== "dismiss-plugin-page" && command.type !== "open-history";
}

export function createChatPreviewPlatform(ctx: BrowserPreviewContext): ChatPlatform {
  const {
    chatEventListeners,
    chatListeners,
    config,
    conversations,
    emitChat,
    emitTurnState,
    getActiveThemeId,
    getChat,
    getTemplateSession,
    listPreviewThemes,
    nextChatEventSeq,
    previewThemeAssetBases,
    previewThemeManifests,
    previewThemeSources,
    resolvePreviewManifest,
    setActiveThemeId,
    setChat,
    setTemplateSession,
  } = ctx;

  let previewBranchCounter = 1;
  let previewHistoryCounter = 0;
  const previewBranches = new Map<string, ChatConversationBranch & { historyEntries: ChatHistoryEntry[] }>();
  previewBranches.set("main", {
    id: "main",
    label: "Main",
    parentId: null,
    historyEntries: cloneHistoryEntries(getChat().historyEntries),
  });

  const pendingChatTimeouts = new Set<number>();
  let replayPlan: ChatReplaySnapshot | null = null;
  let replayRestore: ChatSnapshot | null = null;
  let replayTimer: number | undefined;

  const showPreviewReplay = () => {
    window.clearTimeout(replayTimer);
    const current = getChat();
    const progress = current.replay;
    const entry = progress && replayPlan?.entries[progress.index];
    if (!progress || !entry) return;
    setChat({
      ...current,
      status: "replaying",
      characterName: entry.speaker,
      dialogHtml: "",
      dialogText: entry.body,
      options: entry.options ?? [],
      replaySelectedIndex: entry.selectedIndex,
      backgroundPath: "",
      bgmPath: "",
      cgPath: "",
      sprites: [],
      stats: [],
    });
    emitChat();
    if (progress.paused || progress.ended) return;
    replayTimer = window.setTimeout(
      () => {
        const latest = getChat();
        if (latest.replay !== progress) return;
        latest.replay =
          progress.index === progress.total - 1
            ? { ...progress, ended: true, paused: true }
            : { ...progress, index: progress.index + 1 };
        showPreviewReplay();
      },
      Math.max(700, entry.body.length * 125),
    );
  };

  const previewBranchTree = () => ({
    activeBranchId: getChat().conversationTree?.activeBranchId || "main",
    branches: [...previewBranches.values()].map(({ historyEntries: _historyEntries, ...branch }) => ({ ...branch })),
  });

  const savePreviewActiveBranch = () => {
    const current = getChat();
    const activeBranchId = current.conversationTree?.activeBranchId || "main";
    const branch = previewBranches.get(activeBranchId);
    if (branch) {
      branch.historyEntries = cloneHistoryEntries(current.historyEntries);
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
      setChat(patch(getChat()));
      emitChat();
    }, delayMs);
    pendingChatTimeouts.add(timeoutId);
  };

  return {
    async getCurrentConversation() {
      return clone(conversations.get(getChat().historyPath ?? "")?.summary ?? null);
    },
    async reconfigureConversation(id, payload, options) {
      const item = conversations.get(id);
      if (!item) throw new Error("Conversation not found");
      const chat = getChat();
      if (chat.chatProcessRunning && chat.historyPath !== item.summary.historyPath) {
        throw new Error("Another chat is running");
      }
      if (
        chat.chatProcessRunning &&
        (!["idle", "paused", "error"].includes(chat.status) ||
          chat.turnState?.pendingCount ||
          chat.turnState?.scheduled)
      ) {
        throw new Error("Wait for the current reply to finish");
      }
      return this.launch({ ...payload, historyPath: item.summary.historyPath, resetHistory: false }, options);
    },
    async listConversations() {
      return clone([...conversations.values()].map((item) => item.summary).sort((a, b) => b.updatedAt - a.updatedAt));
    },
    async prepareConversation(id) {
      const item = conversations.get(id);
      if (!item) throw new Error("Conversation not found");
      return clone(item.payload);
    },
    async renameConversation(id, title) {
      const item = conversations.get(id);
      if (!item) throw new Error("Conversation not found");
      item.summary.title = title;
      return clone(item.summary);
    },
    async deleteConversation(id) {
      const item = conversations.get(id);
      if (!item) throw new Error("Conversation not found");
      const chat = getChat();
      if ((chat.chatProcessRunning || chat.chatRuntimeClosing) && chat.historyPath === item.summary.historyPath) {
        throw new Error("Close this chat before deleting it.");
      }
      conversations.delete(id);
    },
    async close(options) {
      const chat = getChat();
      if (options?.expectedSessionId !== undefined && options.expectedSessionId !== (chat.sessionId ?? "")) {
        throw new PlatformRequestError("The current chat has changed.", 409, "chat_session_changed");
      }
      clearScheduledChatUpdates();
      const next: ChatSnapshot = {
        ...chat,
        chatProcessRunning: false,
        chatRuntimeClosing: false,
        notificationText: "聊天会话已结束。",
        options: [],
        sessionClosedReason: "聊天会话已结束。",
        status: "idle",
      };
      setChat(next);
      emitChat();
      return delay(next);
    },
    async command(command) {
      if (isPreviewRealtimeCommand(command) && String(getChat().sessionClosedReason ?? "").trim()) {
        setChat({
          ...getChat(),
          notificationText: "",
          sessionClosedReason: "",
        });
      }
      if (command.type === "dismiss-plugin-page") {
        const payload = command.payload as { pluginId?: unknown; presentationId?: unknown } | undefined;
        const pluginId = String(payload?.pluginId ?? "");
        const presentationId = String(payload?.presentationId ?? "");
        const chat = getChat();
        setChat({
          ...chat,
          pluginPagePresentations: (chat.pluginPagePresentations ?? []).filter(
            (item) => item.pluginId !== pluginId || item.presentationId !== presentationId,
          ),
        });
        emitChat();
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
        const chat = getChat();
        setChat({
          ...chat,
          turnOptions: nextOptions,
          turnState: {
            ...(chat.turnState ?? sampleChatSnapshot.turnState!),
            enabled: nextOptions.batchEnabled,
            ...(!nextOptions.batchEnabled
              ? { pendingCount: 0, pendingMessages: [], remainingSeconds: null, scheduled: false, typing: false }
              : {}),
          },
        });
        emitTurnState();
      }
      if (command.type === "chat-input-state") {
        const payload = command.payload as { composing?: unknown; hasText?: unknown } | undefined;
        const active = Boolean(payload?.composing || payload?.hasText);
        const chat = getChat();
        setChat({
          ...chat,
          turnState: {
            ...(chat.turnState ?? sampleChatSnapshot.turnState!),
            remainingSeconds: active ? null : (chat.turnOptions?.batchIdleSeconds ?? 5),
            scheduled: !active && (chat.turnState?.pendingCount ?? 0) > 0,
            typing: active && (chat.turnState?.pendingCount ?? 0) > 0,
          },
        });
        emitTurnState();
      }
      if (command.type === "flush-input-batch" || command.type === "cancel-input-batch") {
        const chat = getChat();
        setChat({
          ...chat,
          turnState: {
            ...(chat.turnState ?? sampleChatSnapshot.turnState!),
            pendingCount: 0,
            pendingMessages: [],
            remainingSeconds: null,
            scheduled: false,
            typing: false,
          },
        });
        emitTurnState();
      }
      if (command.type === "send-message") {
        const payload = browserPreviewChatPayload(command.payload);
        const displayText = payload.displayText;
        const chat = getChat();
        if (chat.turnOptions?.batchEnabled) {
          const next: ChatSnapshot = {
            ...chat,
            inputDraft: "",
            options: [],
            turnState: {
              ...(chat.turnState ?? sampleChatSnapshot.turnState!),
              enabled: true,
              pendingCount: (chat.turnState?.pendingCount ?? 0) + 1,
              pendingMessages: [...(chat.turnState?.pendingMessages ?? []), displayText],
              remainingSeconds: chat.turnOptions.batchIdleSeconds,
              scheduled: true,
              typing: false,
            },
          };
          setChat(next);
          emitTurnState();
          return delay(next);
        }
        clearScheduledChatUpdates();
        const userDisplayName = chat.userDisplayName?.trim() || "你";
        const nextUserIndex =
          Math.max(-1, ...cloneHistoryEntries(chat.historyEntries).map((entry) => entry.revertUserIndex ?? -1)) + 1;
        setChat({
          ...chat,
          characterName: userDisplayName,
          dialogText: displayText,
          historyEntries: [
            ...cloneHistoryEntries(chat.historyEntries),
            {
              createdAt: Date.now(),
              id: `history-${Date.now()}-user`,
              revertUserIndex: nextUserIndex,
              role: "user",
              text: `${userDisplayName}: ${displayText}`,
            },
          ],
          inputDraft: "",
          options: [],
          numericInfo: "streaming",
          status: "streaming",
        });
        emitChat();
        scheduleChatUpdate(700, (current) => ({
          ...current,
          characterName: "Nanami",
          dialogText: `收到：${displayText}`,
          historyEntries: [
            ...cloneHistoryEntries(current.historyEntries),
            { id: `history-${Date.now()}-assistant`, role: "assistant", text: `Nanami: 收到：${displayText}` },
          ],
          numericInfo: "speaking",
          status: "speaking",
        }));
        scheduleChatUpdate(1400, (current) => ({ ...current, numericInfo: "idle", status: "idle" }));
      }
      if (command.type === "submit-option") {
        const option = String(command.payload ?? "").trim();
        const chat = getChat();
        if (chat.turnOptions?.batchEnabled) {
          const next: ChatSnapshot = {
            ...chat,
            inputDraft: "",
            turnState: {
              ...(chat.turnState ?? sampleChatSnapshot.turnState!),
              enabled: true,
              pendingCount: (chat.turnState?.pendingCount ?? 0) + 1,
              pendingMessages: [...(chat.turnState?.pendingMessages ?? []), option],
              remainingSeconds: chat.turnOptions.batchIdleSeconds,
              scheduled: true,
              typing: false,
            },
          };
          setChat(next);
          emitTurnState();
          return delay(next);
        }
        clearScheduledChatUpdates();
        setChat({
          ...chat,
          dialogText: `选择：${option}`,
          historyEntries: [
            ...cloneHistoryEntries(chat.historyEntries),
            { id: `history-${Date.now()}-option`, role: "options", text: `选项: ${option}` },
          ],
          options: [],
          status: "generating",
          numericInfo: "generating",
        });
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
        setChat({ ...getChat(), status: "idle", numericInfo: "idle" });
        emitChat();
      }
      if (["pause-asr", "finish-asr-hold", "cancel-asr-hold"].includes(command.type)) {
        clearScheduledChatUpdates();
        setChat({
          ...getChat(),
          asrEnabled: false,
          asrLoading: false,
          asrRunning: false,
          status: "paused",
          numericInfo: "paused",
        });
        emitChat();
      }
      if (command.type === "resume-asr" || command.type === "begin-asr-hold") {
        clearScheduledChatUpdates();
        setChat({
          ...getChat(),
          asrEnabled: true,
          asrLoading: false,
          asrRunning: true,
          status: "listening",
          numericInfo: "listening",
        });
        emitChat();
      }
      if (command.type === "change-voice-language") {
        const voiceLanguage =
          String(command.payload ?? "")
            .trim()
            .toLowerCase() || "ja";
        config.system_config.voice_language = voiceLanguage;
        setChat({ ...getChat(), numericInfo: "idle", status: "idle", voiceLanguage });
        emitChat();
      }
      if (command.type === "clear-history") {
        clearScheduledChatUpdates();
        setChat({
          ...getChat(),
          dialogText: "浏览器预览历史已清空。",
          historyEntries: [],
          options: [],
          status: "idle",
          numericInfo: "idle",
        });
        emitChat();
      }
      if (command.type === "revert-history") {
        clearScheduledChatUpdates();
        const revertUserIndex = Number(command.payload);
        const chat = getChat();
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
            setChat({
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
            });
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
        const chat = getChat();
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
          const forked: ChatSnapshot = {
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
          setChat(forked);
          forked.conversationTree = previewBranchTree();
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
          const switched: ChatSnapshot = {
            ...getChat(),
            conversationTree: { activeBranchId: branchId, branches: previewBranchTree().branches },
            dialogText: branch.historyEntries.at(-1)?.text ?? "",
            historyEntries: cloneHistoryEntries(branch.historyEntries),
            numericInfo: "idle",
            options: [],
            status: "idle",
          };
          setChat(switched);
          switched.conversationTree = previewBranchTree();
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
          getChat().conversationTree = previewBranchTree();
          emitChat();
        }
      }
      if (command.type === "copy-history") {
        const chat = getChat();
        return {
          ...clone(chat),
          clipboardText: cloneHistoryEntries(chat.historyEntries)
            .map((entry) => entry.text)
            .join("\n"),
        };
      }
      if (command.type === "open-history") {
        const chat = getChat();
        return { ...clone(chat), openedPath: chat.historyPath ?? "./data/chat_history/preview" };
      }
      if (command.type === "set-voice-archive" && typeof command.payload === "boolean") {
        setChat({ ...getChat(), voiceArchiveEnabled: command.payload });
        emitChat();
      }
      return clone(getChat());
    },
    getHistory: () => delay(cloneHistoryEntries(getChat().historyEntries)),
    getHistoryVoice: () => delay([]),
    prepareReplay: async () => {
      const chat = getChat();
      replayPlan = {
        id: "preview-replay",
        sessionId: chat.sessionId ?? "",
        branchId: "main",
        branchLabel: "",
        historyCount: chat.historyEntries?.length ?? 0,
        entries: cloneHistoryEntries(chat.historyEntries)
          .filter((entry) => !/^\s*(?:scene|场景|bgm)[:：]/i.test(entry.text))
          .map((entry, index) => {
            const match = entry.text.match(/^\s*([^：:\n]+)[：:]\s*([\s\S]*)$/);
            return {
              ...entry,
              key: entry.id,
              position: index + 1,
              speaker: match?.[1] ?? "",
              body: match?.[2] ?? entry.text,
              canGenerate: false,
              voiceUrls: [],
              voiceSource: "",
              voiceLabel: "",
              frame: null,
            };
          }),
      };
      return delay(clone(replayPlan));
    },
    startReplay: async (id, startKey, endKey) => {
      const chat = getChat();
      if (!replayPlan || replayPlan.id !== id || chat.replay) throw new Error("Replay unavailable");
      const start = replayPlan.entries.findIndex((entry) => entry.key === startKey);
      const end = replayPlan.entries.findIndex((entry) => entry.key === endKey);
      if (start < 0 || end < start) throw new Error("Invalid replay range");
      replayRestore = clone(chat);
      replayPlan = { ...replayPlan, entries: replayPlan.entries.slice(start, end + 1) };
      chat.replay = { id, index: 0, total: end - start + 1, paused: false, ended: false, waiting: false, error: "" };
      showPreviewReplay();
    },
    getReplay: async (id) => {
      if (!replayPlan || getChat().replay?.id !== id) throw new Error("No preview replay is running");
      return { snapshot: clone(replayPlan), generate: false };
    },
    generateReplayVoice: async () => {
      throw new Error("Preview has no voice provider");
    },
    cancelReplay: async (id) => {
      if (getChat().replay?.id !== id || !replayRestore) return;
      window.clearTimeout(replayTimer);
      setChat({ ...replayRestore, replay: null, replaySelectedIndex: null });
      replayRestore = null;
      emitChat();
    },
    controlReplay: async (id, control) => {
      const chat = getChat();
      if (chat.replay?.id !== id) throw new Error("No preview replay is running");
      const progress = chat.replay;
      if (control.action === "seek") {
        const index = control.index ?? -1;
        if (index < 0 || index >= progress.total) throw new Error("Invalid replay range");
        chat.replay = { ...progress, index, paused: !control.playing, ended: false };
      } else if (control.action === "play" || control.action === "pause") {
        chat.replay = { ...progress, paused: control.action === "pause" };
      }
      showPreviewReplay();
    },
    getRuntimeStatus: () => delay(runtimeStatusFromSnapshot(getChat())),
    getSnapshot: () => delay(getChat()),
    getTheme: () =>
      delay(
        previewThemePayloadFromManifest(
          resolvePreviewManifest(getActiveThemeId()) ?? sampleChatThemeManifests[DEFAULT_CHAT_THEME_ID],
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
      const chat = getChat();
      const player = config.characters.find(
        (item) => item.name === payload.playerCharacter && payload.characters.includes(item.name),
      );
      const character = config.characters.find(
        (item) => payload.characters.includes(item.name) && item.name !== player?.name,
      );
      const background = config.background_list.find((item) => item.name === payload.backgroundName);
      const requestedHistoryPath = payload.historyPath || chat.historyPath || "./data/chat_history/preview";
      const historyBase = requestedHistoryPath.toLowerCase().endsWith(".json")
        ? requestedHistoryPath.slice(0, -".json".length)
        : requestedHistoryPath;
      const historyPath = payload.resetHistory
        ? `${historyBase}-quick-restart-${(previewHistoryCounter += 1)}`
        : requestedHistoryPath;
      const next: ChatSnapshot = {
        ...chat,
        backgroundPath: background?.sprites[0]?.path,
        userDisplayName: player?.name || "你",
        playerPortrait: player?.sprites[0]
          ? {
              characterName: player.name,
              url: player.sprites[0].path,
              crop: player.sprites[0].portrait_crop ?? player.portrait_crop ?? { x: 0.5, y: 0.2, zoom: 1 },
            }
          : null,
        characterName: character?.name,
        chatProcessRunning: true,
        chatRuntimeClosing: false,
        dialogText: "",
        historyPath,
        sprites:
          payload.showInitialSprite !== false && character?.sprites[0]
            ? [
                {
                  avatarType: "static",
                  modelUrl: "",
                  id: `${character.name}-0`,
                  identityKey: `character:${character.name.toLowerCase()}`,
                  label: character.name,
                  path: character.sprites[0].path,
                },
              ]
            : [],
        sessionClosedReason: "",
        status: "idle",
        statusMessage: `${payload.templateId || payload.templateName || "预览聊天"} 已启动：${historyPath}`,
      };
      setChat(next);
      const templateSession = getTemplateSession();
      if (templateSession) {
        setTemplateSession({ ...templateSession, historyPath });
      }
      conversations.set(historyPath, {
        payload: clone({ ...payload, historyPath, resetHistory: false }),
        summary: {
          id: historyPath,
          title:
            conversations.get(historyPath)?.summary.title ||
            payload.conversationTitle?.trim() ||
            payload.templateName ||
            "",
          characters: payload.characters,
          preview: "",
          updatedAt: Date.now(),
          kind: payload.storyPath ? "story" : (conversations.get(historyPath)?.summary.kind ?? "normal"),
          storyPath: payload.storyPath || conversations.get(historyPath)?.summary.storyPath || "",
          historyPath,
          hasSettings: true,
        },
      });
      emitChat();
      previewTask<ChatSnapshot>(
        taskId,
        {
          kind: "chat-initialization",
          message: "Chat is ready",
          phase: "completed",
          progress: 1,
          result: clone(next),
          status: "succeeded",
          title: "Initialize chat",
        },
        options,
      );
      return clone(next);
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
      const chat = getChat();
      const templateSession = getTemplateSession();
      const player = config.characters.find(
        (item) =>
          item.name === templateSession?.playerCharacter && templateSession?.selectedCharacters?.includes(item.name),
      );
      const character = config.characters.find(
        (item) => templateSession?.selectedCharacters?.includes(item.name) && item.name !== player?.name,
      );
      const background = config.background_list.find((item) => item.name === templateSession?.background);
      const historyPath = templateSession?.historyPath || chat.historyPath || "./data/chat_history/preview";
      const next: ChatSnapshot = {
        ...chat,
        backgroundPath: background?.sprites[0]?.path ?? chat.backgroundPath,
        userDisplayName: player?.name || "你",
        playerPortrait: player?.sprites[0]
          ? chat.playerPortrait?.characterName === player.name
            ? chat.playerPortrait
            : {
                characterName: player.name,
                url: player.sprites[0].path,
                crop: player.sprites[0].portrait_crop ?? player.portrait_crop ?? { x: 0.5, y: 0.2, zoom: 1 },
              }
          : null,
        characterName: character?.name ?? chat.characterName,
        chatProcessRunning: true,
        chatRuntimeClosing: false,
        dialogText: "",
        historyPath,
        sprites:
          templateSession?.showInitialSprite === false
            ? []
            : character?.sprites[0]
              ? [
                  {
                    avatarType: "static",
                    modelUrl: "",
                    id: `${character.name}-0`,
                    identityKey: `character:${character.name.toLowerCase()}`,
                    label: character.name,
                    path: character.sprites[0].path,
                  },
                ]
              : chat.sprites,
        sessionClosedReason: "",
        status: "idle",
        statusMessage: `已恢复上次启动：${historyPath}`,
      };
      setChat(next);
      emitChat();
      previewTask<ChatSnapshot>(
        taskId,
        {
          kind: "chat-initialization",
          message: "Chat is ready",
          phase: "completed",
          progress: 1,
          result: clone(next),
          status: "succeeded",
          title: "Initialize chat",
        },
        options,
      );
      return clone(next);
    },
    subscribe(listener) {
      chatListeners.add(listener);
      listener(clone(getChat()));
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
    getActiveThemeId: () => delay(getActiveThemeId()),
    async setActiveThemeId(id) {
      if (!previewThemeManifests.has(id)) {
        throw new Error(`主题不存在：${id}`);
      }
      setActiveThemeId(id);
    },
    async uploadTheme(file) {
      const id =
        file.name
          .replace(/\.zip$/i, "")
          .trim()
          .replace(/[^\w-]+/g, "-") || "uploaded-theme";
      const base = resolvePreviewManifest(getActiveThemeId()) ?? sampleChatThemeManifests[DEFAULT_CHAT_THEME_ID];
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
    async uploadAttachments() {
      return { attachments: [] };
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
      if (getActiveThemeId() === id) {
        setActiveThemeId(DEFAULT_CHAT_THEME_ID);
      }
    },
    subscribeEvents(listener) {
      chatEventListeners.add(listener);
      listener({
        seq: nextChatEventSeq(),
        snapshot: clone(getChat()),
        ts: Date.now(),
        type: "snapshot",
        v: 1,
      });
      return () => {
        chatEventListeners.delete(listener);
      };
    },
  };
}
