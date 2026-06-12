import type {
  ChatHistoryEntry,
  ChatRuntimeStatus,
  ChatSnapshot,
  ChatSprite,
  ChatStageEvent,
  ChatTransportMode,
  ChatTransportState,
} from "../../shared/platform/types";

export interface ChatStageLayers {
  background: boolean;
  busy: boolean;
  cg: boolean;
  dialog: boolean;
  input: boolean;
  notification: boolean;
  options: boolean;
  sprites: boolean;
  toolbar: boolean;
}

export interface ChatStageSprite extends ChatSprite {
  characterName?: string;
  scale?: number;
  slot?: number;
}

export interface ChatStageState extends Omit<ChatSnapshot, "sprites"> {
  asrTranscript?: string;
  busyDurationSeconds?: number;
  busyText?: string;
  cgPath?: string;
  dialogHtml?: string;
  error?: string;
  eventSeq: number;
  layers: ChatStageLayers;
  notificationText?: string;
  sessionClosedReason?: string;
  sprites: ChatStageSprite[];
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
  userDisplayName: string;
}

export interface ChatStageViewModel {
  backgroundPath?: string;
  busyText?: string;
  cgPath?: string;
  dialogCharacterName?: string;
  dialogHtml?: string;
  dialogText: string;
  inputDisabled: boolean;
  inputDraft: string;
  layers: ChatStageLayers;
  notificationText?: string;
  options: string[];
  sprites: ChatStageSprite[];
  status: ChatRuntimeStatus;
  statusText: string;
  tokenUsageText?: string;
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
  userDisplayName: string;
  voiceLanguage?: string;
}

export type ChatStageAction =
  | { type: "event"; event: ChatStageEvent }
  | { type: "hydrate"; snapshot: ChatSnapshot }
  | { type: "setHistoryEntries"; historyEntries: ChatHistoryEntry[] }
  | { type: "setDraft"; text: string }
  | { type: "setStatus"; status: ChatRuntimeStatus }
  | { type: "error"; message: string };

function defaultLayers(): ChatStageLayers {
  return {
    background: true,
    busy: false,
    cg: false,
    dialog: false,
    input: true,
    notification: false,
    options: false,
    sprites: false,
    toolbar: true,
  };
}

function htmlToText(value: string) {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(?:div|li|p)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const defaultUserDialogSpeaker = "你";

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizedUserDisplayName(value?: string) {
  return value?.trim() || defaultUserDialogSpeaker;
}

function isSystemPromptText(value: string) {
  const text = value.trim();
  if (!text) {
    return false;
  }
  return /^(已跳过|已选择|选择：|历史|浏览器预览历史|语音识别|正在请求|聊天会话|您的消息已提交|进程已经|当前聊天会话|实时聊天会话)/.test(
    text,
  );
}

function normalizeTokenUsageText(value: string | undefined, status: ChatRuntimeStatus) {
  const text = value?.trim();
  if (!text || text === status) {
    return undefined;
  }
  if (/^(idle|listening|paused|generating|streaming|speaking|error)$/i.test(text)) {
    return undefined;
  }
  return text;
}

function systemPromptTextFromState(state: ChatStageState, dialogText: string) {
  if (state.error) {
    return state.error;
  }
  const statusMessage = state.statusMessage?.trim();
  if (statusMessage && !state.characterName?.trim()) {
    return statusMessage;
  }
  if (!state.characterName?.trim() && state.dialogHtml === undefined && isSystemPromptText(dialogText)) {
    return dialogText.trim();
  }
  return undefined;
}

function userDialogPrefixPattern(userDisplayName: string) {
  const names = [defaultUserDialogSpeaker, userDisplayName]
    .map((name) => name.trim())
    .filter(Boolean)
    .filter((name, index, list) => list.indexOf(name) === index)
    .map(escapeRegExp);
  return new RegExp(`^\\s*(?:${names.join("|")})\\s*[：:]\\s*`);
}

function normalizeDialogView(
  characterName: string | undefined,
  dialogText: string,
  dialogHtml: string | undefined,
  userDisplayName: string,
) {
  const normalizedName = characterName?.trim();
  const userName = normalizedUserDisplayName(userDisplayName);
  const prefixPattern = userDialogPrefixPattern(userName);
  if (normalizedName === defaultUserDialogSpeaker || normalizedName === userName) {
    return {
      characterName: userName,
      dialogHtml,
      dialogText: dialogText.replace(prefixPattern, ""),
    };
  }
  if (!normalizedName && dialogHtml === undefined && prefixPattern.test(dialogText)) {
    return {
      characterName: userName,
      dialogHtml,
      dialogText: dialogText.replace(prefixPattern, ""),
    };
  }
  return {
    characterName,
    dialogHtml,
    dialogText,
  };
}

function sortSprites(sprites: ChatStageSprite[]) {
  return [...sprites].sort((left, right) => {
    const slotDiff = (left.slot ?? Number.MAX_SAFE_INTEGER) - (right.slot ?? Number.MAX_SAFE_INTEGER);
    if (slotDiff !== 0) {
      return slotDiff;
    }
    return left.id.localeCompare(right.id);
  });
}

function clearTransientNotificationState(state: ChatStageState) {
  return {
    ...state,
    notificationText: undefined,
    sessionClosedReason: undefined,
  };
}

function withResolvedLayers(state: ChatStageState): ChatStageState {
  return {
    ...state,
    layers: {
      ...state.layers,
      background: true,
      busy: Boolean(state.busyText),
      cg: Boolean(state.cgPath),
      dialog: Boolean(state.error || state.dialogHtml || state.dialogText || state.characterName),
      input: !state.sessionClosedReason,
      notification: Boolean(state.notificationText),
      options: state.options.length > 0,
      sprites: !state.cgPath && state.sprites.length > 0,
      toolbar: true,
    },
  };
}

function snapshotEventSeq(snapshot: ChatSnapshot) {
  return typeof snapshot.eventSeq === "number" && Number.isFinite(snapshot.eventSeq) ? snapshot.eventSeq : 0;
}

function transportFromSnapshot(snapshot: ChatSnapshot): Pick<ChatStageState, "transportMode" | "transportState"> {
  if (snapshot.wsUrl && snapshot.sessionId) {
    return {
      transportMode: "websocket",
      transportState: "connecting",
    };
  }
  return {
    transportMode: "snapshot",
    transportState: "connected",
  };
}

function shouldPreserveTransportState(state: ChatStageState) {
  return (
    state.transportMode !== emptyChatState.transportMode ||
    state.transportState !== emptyChatState.transportState
  );
}

function hydrateFromSnapshot(state: ChatStageState, snapshot: ChatSnapshot): ChatStageState {
  const nextEventSeq = snapshotEventSeq(snapshot);
  if (nextEventSeq < state.eventSeq) {
    return state;
  }
  const transport =
    shouldPreserveTransportState(state)
      ? { transportMode: state.transportMode, transportState: state.transportState }
      : transportFromSnapshot(snapshot);
  return withResolvedLayers({
    ...emptyChatState,
    ...snapshot,
    asrTranscript: undefined,
    error: undefined,
    eventSeq: nextEventSeq,
    sprites: snapshot.sprites.map((sprite) => ({ ...sprite })),
    ...transport,
  });
}

function upsertSprite(state: ChatStageState, event: Extract<ChatStageEvent, { type: "sprite.show" }>): ChatStageState {
  const id = event.slot != null ? `${event.characterName}:${event.slot}` : event.characterName;
  const nextSprite: ChatStageSprite = {
    characterName: event.characterName,
    id,
    label: event.characterName,
    path: event.url,
    scale: event.scale,
    slot: event.slot,
  };
  const sprites = sortSprites(
    [...state.sprites.filter((sprite) => sprite.id !== id && sprite.label !== event.characterName), nextSprite],
  );
  return withResolvedLayers({
    ...clearTransientNotificationState(state),
    eventSeq: Math.max(state.eventSeq, event.seq),
    sprites,
  });
}

function removeSprite(state: ChatStageState, event: Extract<ChatStageEvent, { type: "sprite.remove" }>): ChatStageState {
  return withResolvedLayers({
    ...state,
    eventSeq: Math.max(state.eventSeq, event.seq),
    sprites: state.sprites.filter(
      (sprite) => sprite.id !== event.characterName && sprite.label !== event.characterName,
    ),
  });
}

function applyStageEvent(state: ChatStageState, event: ChatStageEvent): ChatStageState {
  if (event.type === "transport.state") {
    return withResolvedLayers({
      ...state,
      transportMode: event.transport,
      transportState: event.state,
    });
  }
  if (event.type !== "snapshot" && event.seq <= state.eventSeq) {
    return state;
  }
  switch (event.type) {
    case "snapshot":
      return hydrateFromSnapshot(state, {
        ...event.snapshot,
        eventSeq: Math.max(snapshotEventSeq(event.snapshot), event.seq),
      });
    case "dialog.end":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        error: undefined,
        ...(event.isSystem && !event.speaker.trim()
          ? { notificationText: htmlToText(event.fullHtml) }
          : {
              characterName: event.speaker,
              dialogHtml: event.fullHtml,
              dialogText: htmlToText(event.fullHtml),
              options: [],
            }),
      });
    case "user.display_name.change":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        userDisplayName: event.name.trim() || state.userDisplayName,
      });
    case "history.replace":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        historyEntries: event.entries.map((entry) => ({ ...entry })),
      });
    case "sprite.show":
      return upsertSprite(state, event);
    case "sprite.remove":
      return removeSprite(state, event);
    case "background.change":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        backgroundPath: event.url,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "cg.show":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        cgPath: event.url,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "cg.hide":
      return withResolvedLayers({
        ...state,
        cgPath: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "options.show":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: event.options,
      });
    case "options.clear":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: [],
      });
    case "numeric.update":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        numericInfo: htmlToText(event.html),
      });
    case "busy.show":
      return withResolvedLayers({
        ...state,
        busyDurationSeconds: event.durationSeconds,
        busyText: event.text,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "busy.hide":
      return withResolvedLayers({
        ...state,
        busyDurationSeconds: undefined,
        busyText: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "notification.change":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        notificationText: event.text,
      });
    case "status.change":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: event.status,
      });
    case "tts.play":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        characterName: event.characterName,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: "speaking",
      });
    case "tts.skip":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: state.status === "speaking" ? "idle" : state.status,
      });
    case "asr.partial":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        asrTranscript: event.text,
        eventSeq: Math.max(state.eventSeq, event.seq),
        inputDraft: event.text,
        status: "listening",
      });
    case "asr.final":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        asrTranscript: event.text,
        eventSeq: Math.max(state.eventSeq, event.seq),
        inputDraft: event.text,
      });
    case "asr.state":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: event.running ? "listening" : "paused",
      });
    case "reply.finished":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: state.status === "generating" || state.status === "streaming" ? "idle" : state.status,
      });
    case "session.closed":
      return withResolvedLayers({
        ...state,
        busyDurationSeconds: undefined,
        busyText: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
        notificationText: event.reason,
        options: [],
        sessionClosedReason: event.reason,
        status: "idle",
      });
    default:
      return state;
  }
}

export function chatStageReducer(state: ChatStageState, action: ChatStageAction): ChatStageState {
  switch (action.type) {
    case "event":
      return applyStageEvent(state, action.event);
    case "hydrate":
      return hydrateFromSnapshot(state, action.snapshot);
    case "setHistoryEntries":
      return withResolvedLayers({
        ...state,
        historyEntries: action.historyEntries.map((entry) => ({ ...entry })),
      });
    case "setDraft":
      return withResolvedLayers({ ...state, inputDraft: action.text });
    case "setStatus":
      return withResolvedLayers({
        ...state,
        sessionClosedReason: undefined,
        status: action.status,
      });
    case "error":
      return withResolvedLayers({
        ...state,
        error: action.message,
        status: "error",
      });
    default:
      return state;
  }
}

export function buildChatStageViewModel(state: ChatStageState): ChatStageViewModel {
  const dialog = normalizeDialogView(
    state.error ? undefined : state.characterName,
    state.error ?? state.dialogText,
    state.error ? undefined : state.dialogHtml,
    state.userDisplayName,
  );
  const tokenUsageText = normalizeTokenUsageText(state.numericInfo, state.status);
  const systemPromptText = systemPromptTextFromState(state, dialog.dialogText);
  const layers = {
    ...state.layers,
    dialog: state.layers.dialog && !systemPromptText && Boolean(dialog.dialogHtml || dialog.dialogText),
    notification: Boolean(state.notificationText || systemPromptText),
  };
  return {
    backgroundPath: state.backgroundPath,
    busyText: state.busyText,
    cgPath: state.cgPath,
    dialogCharacterName: systemPromptText ? undefined : dialog.characterName,
    dialogHtml: systemPromptText ? undefined : dialog.dialogHtml,
    dialogText: systemPromptText ? "" : dialog.dialogText,
    inputDisabled: !state.layers.input || state.status === "generating" || state.status === "streaming",
    inputDraft: state.inputDraft,
    layers,
    notificationText: state.notificationText || systemPromptText,
    options: state.options,
    sprites: state.sprites,
    status: state.status,
    statusText: state.status,
    tokenUsageText,
    transportMode: state.transportMode,
    transportState: state.transportState,
    userDisplayName: normalizedUserDisplayName(state.userDisplayName),
    voiceLanguage: state.voiceLanguage,
  };
}

export const emptyChatState: ChatStageState = {
  dialogText: "",
  eventSeq: 0,
  inputDraft: "",
  layers: defaultLayers(),
  options: [],
  sprites: [],
  status: "idle",
  transportMode: "snapshot",
  transportState: "connecting",
  userDisplayName: defaultUserDialogSpeaker,
};
