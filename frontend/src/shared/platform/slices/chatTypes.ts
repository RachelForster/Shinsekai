import type { ChatThemePayload } from "../../theme/chatChromeTheme";
import type { ChatThemeManifest, ChatThemeSummary, SaveChatThemeInput } from "../../theme/chatTheme";
import type { StoryDocument, StoryEditInput, StorySuggestion, StorySuggestionInput } from "../storyEditorTypes";
import type { StoryGenerationPreview } from "../storyPreviewTypes";
import type { PlayerPortrait, SpriteTransitionMedia } from "./characterTypes";
import type { PerceptionRuntimeState } from "./perceptionTypes";
import type { PluginPagePresentation } from "./pluginTypes";
import type { StoryGenerationInput, StoryGenerationStage, StoryGenerationTask, StoryLibraryEntry } from "./storyTypes";
import type { RuntimeDependencyError, TaskProgressOptions, TaskSnapshot } from "./taskTypes";
import type {
  CharacterPromptMode,
  MediaSelectionMode,
  PlayerCharacterOptions,
  TemplateLaunchSession,
} from "./workspaceTypes";

export interface ConversationSummary {
  id: string;
  title: string;
  characters: string[];
  preview: string;
  updatedAt: number;
  kind: "normal" | "story";
  storyPath: string;
  historyPath: string;
  hasSettings: boolean;
  requiresCharacterSelection?: boolean;
}

export interface ChatLaunchPayload extends PlayerCharacterOptions {
  storyPath?: string;
  characterPromptMode?: CharacterPromptMode;
  primaryCharacters?: string[];
  maxDialogItems?: number;
  maxSpeechChars?: number;
  useChoice?: boolean;
  useCot?: boolean;
  useEffect?: boolean;
  useNarration?: boolean;
  useStat?: boolean;
  useTranslation?: boolean;
  voiceLanguage?: string;
  conversationTitle?: string;
  editorSession?: TemplateLaunchSession;
  backgroundName: string;
  characters: string[];
  enableMobileAccess?: boolean;
  effectNames?: string[];
  historyPath: string;
  initSpritePath?: string;
  showInitialSprite?: boolean;
  mediaSelectionMode?: MediaSelectionMode;
  resetHistory?: boolean;
  roomId?: string;
  scenario?: string;
  system?: string;
  templateName?: string;
  templateId: string;
  useCg?: boolean;
}

/** Explicit device preferences override persisted values when restoring a chat. */
export type ChatResumeOverrides = Pick<ChatLaunchPayload, "enableMobileAccess">;

export type ChatRuntimeStatus =
  | "idle"
  | "listening"
  | "generating"
  | "streaming"
  | "speaking"
  | "paused"
  | "replaying"
  | "error";

export interface ChatRuntimeProcessState {
  chatProcessRunning: boolean;
  chatRuntimeClosing: boolean;
  state: "idle" | "running" | "closing";
}

export interface ChatSprite {
  mouthSync?: string;
  transitions?: SpriteTransitionMedia[];
  /** Producer-owned identity, independent of display labels, expression URLs and snapshot IDs. */
  identityKey?: string;
  id: string;
  label: string;
  path: string;
  scale?: number;
  slot?: number;
  x?: number;
  y?: number;
  avatarType: string;
  modelUrl: string;
}

export type ChatHistoryRole = "assistant" | "options" | "system" | "user";

export interface ChatHistoryEntry {
  dialogId?: string;
  createdAt?: number;
  id: string;
  revertUserIndex?: number;
  role: ChatHistoryRole;
  text: string;
  voiceId?: string;
}

export type ChatStatIcon = "clock" | "coins" | "gauge" | "heart" | "shield" | "sparkles" | "star" | "target" | "zap";

export interface ChatStat {
  icon: ChatStatIcon;
  label: string;
  max?: number;
  value: number;
}

export interface ChatReplayEntry extends ChatHistoryEntry {
  options?: string[];
  selectedIndex?: number | null;
  voiceVolume?: number;
  key: string;
  position: number;
  speaker: string;
  body: string;
  canGenerate: boolean;
  voiceUrls: string[];
  voiceSource: string;
  voiceLabel: string;
  frame?: { backgroundPath: string; bgmPath: string; cgPath: string; sprites: ChatSprite[]; stats: ChatStat[] } | null;
}

export interface ChatReplaySnapshot {
  historyCount: number;
  id: string;
  sessionId: string;
  branchId: string;
  branchLabel: string;
  entries: ChatReplayEntry[];
}

export type ChatReplayVoice = Pick<ChatReplayEntry, "voiceUrls" | "voiceSource" | "voiceLabel">;

export interface ChatReplayProgress {
  voiceSource?: string;
  voiceLabel?: string;
  input?: {
    phase: "typing" | "submitting";
    text: string;
    durationMs: number;
    epoch: number;
  };
  id: string;
  index: number;
  total: number;
  paused: boolean;
  ended: boolean;
  waiting: boolean;
  error: string;
}

export interface ChatReplayControl {
  action: "pause" | "play" | "seek" | "skip-voice" | "retry";
  index?: number;
  playing?: boolean;
}

export interface ChatConversationBranch {
  createdAt?: number;
  forkedFromEntryId?: string;
  forkedFromText?: string;
  id: string;
  label: string;
  parentId?: string | null;
  updatedAt?: number;
}

export interface ChatConversationTree {
  activeBranchId: string;
  branches: ChatConversationBranch[];
}

export interface ChatExperimentalFeatures {
  conversationTree: boolean;
  forkHistory: boolean;
}

export interface ChatTurnOptions {
  batchEnabled: boolean;
  batchIdleSeconds: number;
  interruptEnabled: boolean;
}

export interface ChatTurnState {
  enabled: boolean;
  pendingCount: number;
  pendingMessages?: string[];
  remainingSeconds: number | null;
  scheduled: boolean;
  typing: boolean;
}

export interface ChatToolConfirmation {
  confirmationId: string;
  detail?: string;
  risk: "high" | "medium";
  toolName: string;
}

export interface ChatStoryOption {
  enabled: boolean;
  expectedNodeId: string;
  expectedRevision: number;
  id: string;
  label: string;
  lockedReason?: string | null;
  source: "story";
}

export type ChatOption = string | ChatStoryOption;

export interface ChatStoryState {
  activeCast: Array<{ id: string; roles: string[] }>;
  background?: string | null;
  castRevision: number;
  currentNodeId: string;
  currentNodeTitle: string;
  currentNodeType?: string;
  ending?: { id: string; title: string } | null;
  lastEvent?: { payload: Record<string, unknown>; revision?: number; type: string };
  objectives: unknown[];
  maxRounds?: number | null;
  nodeTurnCount?: number;
  options: ChatStoryOption[];
  revision: number;
  storyId: string;
  storyVersion: number;
  unlockedNotifications: Array<{ id: string; kind: string }>;
  visibleVariables: Array<{
    id: string;
    maximum?: number | null;
    minimum?: number | null;
    type: string;
    value: unknown;
  }>;
}

export interface ChatSnapshotOptions {
  /** Only pages with an audio player should claim a polling renderer. Defaults to true. */
  claimRenderer?: boolean;
}

export interface ChatCloseOptions {
  /** Reject the close if the active session has changed. */
  expectedSessionId?: string;
}

export interface ChatSpriteReactionSnapshot {
  characterName: string;
  text: string;
  durationMs: number;
  expiresAt?: number;
  seq: number;
}

export interface MobileAccessInfo {
  enabled: true;
  host: string;
  httpPort: number;
  qrCodeDataUrl: string;
  url: string;
  websocketPort: number;
  websocketUrl: string;
}

export interface ChatSnapshot {
  voiceArchiveEnabled?: boolean;
  playerPortrait?: PlayerPortrait | null;
  perception?: PerceptionRuntimeState | null;
  spriteReaction?: ChatSpriteReactionSnapshot | null;
  activePlayback?: {
    characterName: string;
    playbackId: string;
    rendererId?: string;
    seq: number;
    url: string;
    volume: number;
  } | null;
  asrEnabled?: boolean;
  asrLoading?: boolean;
  asrRunning?: boolean;
  backgroundPath?: string;
  bgmPath?: string;
  busyDurationSeconds?: number;
  busyText?: string;
  characterName?: string;
  conversationTree?: ChatConversationTree;
  cgPath?: string;
  chatProcessRunning?: boolean;
  chatRuntimeClosing?: boolean;
  dialogHtml?: string;
  dialogText: string;
  /** 后端已折叠进该 snapshot 的最新事件 seq，用于重连恢复幂等处理。 */
  eventSeq?: number;
  /** Server wall-clock time when this snapshot was prepared for delivery. */
  serverTimeMs?: number;
  effectImage?: {
    durationMs: number;
    expiresAt: number;
    label: string;
    seq: number;
    url: string;
  } | null;
  experimentalFeatures?: ChatExperimentalFeatures;
  historyEntries?: ChatHistoryEntry[];
  historyPath?: string;
  inputDraft: string;
  initTask?: TaskSnapshot;
  loopingEffects?: Array<{
    key: string;
    seq: number;
    url: string;
  }>;
  mobileAccess?: MobileAccessInfo;
  numericInfo?: string;
  notificationText?: string;
  options: ChatOption[];
  pluginPagePresentations?: PluginPagePresentation[];
  runtimeDependencyError?: RuntimeDependencyError;
  runtimeMode?: "native" | "react";
  sessionClosedReason?: string;
  sessionId?: string;
  sprites: ChatSprite[];
  story?: ChatStoryState;
  storyAck?: Record<string, unknown>;
  stats?: ChatStat[];
  status: ChatRuntimeStatus;
  replay?: ChatReplayProgress | null;
  replaySelectedIndex?: number | null;
  statusMessage?: string;
  systemMessageText?: string;
  toolConfirmation?: ChatToolConfirmation | null;
  turnOptions?: ChatTurnOptions;
  turnState?: ChatTurnState;
  userDisplayName?: string;
  voiceLanguage?: string;
  wsUrl?: string;
}

export type ChatPresentation = Partial<
  Pick<
    ChatSnapshot,
    | "backgroundPath"
    | "bgmPath"
    | "cgPath"
    | "sprites"
    | "stats"
    | "characterName"
    | "dialogHtml"
    | "dialogText"
    | "options"
    | "systemMessageText"
    | "playerPortrait"
  >
>;

export interface ChatCommandResult extends ChatSnapshot {
  clipboardText?: string;
  downloadUrl?: string;
  openedPath?: string;
}

export type ChatTransportState = "connected" | "connecting" | "polling" | "reconnecting";
export type ChatTransportMode = "snapshot" | "websocket";

export interface ChatAttachmentInput {
  kind: "file" | "image";
  name: string;
  path: string;
}

export interface ChatSendPayload {
  attachments: ChatAttachmentInput[];
  text: string;
}

export interface ChatCommand {
  cmdId?: string;
  payload?: unknown;
  type:
    | "audio-playback-signal"
    | "set-voice-archive"
    | "save-history-voice"
    | "cancel-input-batch"
    | "change-voice-language"
    | "chat-input-state"
    | "clear-history"
    | "copy-history"
    | "dialog-advance"
    | "dismiss-plugin-page"
    | "fork-history"
    | "flush-input-batch"
    | "open-history"
    | "pause-asr"
    | "begin-asr-hold"
    | "finish-asr-hold"
    | "cancel-asr-hold"
    | "rename-branch"
    | "revert-history"
    | "resume-asr"
    | "reroll"
    | "send-message"
    | "skip-speech"
    | "switch-branch"
    | "submit-option"
    | "update-turn-options";
}

export type ChatRealtimeCommandType =
  | Exclude<ChatCommand["type"], "copy-history" | "dismiss-plugin-page" | "open-history">
  | "revert-history";

/** 上行命令（React→server，WebSocket），沿用并扩展 ChatCommand。 */
export interface ChatUpstreamCommand {
  /** 客户端生成，用于 ack 关联。 */
  cmdId: string;
  payload?: unknown;
  type: ChatRealtimeCommandType;
}

interface ChatEventBase {
  v: 1;
  /** 单调递增，用于缺口检测 + 重连重放。 */
  seq: number;
  /** epoch 毫秒。 */
  ts: number;
}

export type ChatStageEvent =
  | (ChatEventBase & PlayerPortrait & { type: "player.portrait.show" })
  | (ChatEventBase & { type: "snapshot"; snapshot: ChatSnapshot })
  | (ChatEventBase & {
      type: "chat.init.progress" | "chat.init.completed" | "chat.init.failed" | "chat.init.cancelled";
      task: TaskSnapshot;
    })
  | (ChatEventBase & { type: "transport.state"; state: ChatTransportState; transport: ChatTransportMode })
  | (ChatEventBase & {
      type: "cmd.ack";
      cmdId: string;
      commandType: ChatRealtimeCommandType;
      error?: string;
      ok: boolean;
    })
  | (ChatEventBase & {
      type: "dialog.end";
      speaker: string;
      color: string;
      isSystem: boolean;
      fullHtml: string;
      animate?: boolean;
    })
  | (ChatEventBase & { type: "user.display_name.change"; name: string })
  | (ChatEventBase & { type: "history.replace"; entries: ChatHistoryEntry[]; voiceArchiveEnabled?: boolean })
  | (ChatEventBase & { type: "conversation.tree"; tree: ChatConversationTree })
  | (ChatEventBase & { type: "chat.turn.state"; state: ChatTurnState; options?: ChatTurnOptions })
  | (ChatEventBase & PluginPagePresentation & { type: "plugin.page.present" })
  | (ChatEventBase & { type: "plugin.page.dismiss"; pluginId: string; presentationId: string })
  | (ChatEventBase & {
      type: "sprite.show";
      mouthSync?: string;
      transitions?: SpriteTransitionMedia[];
      identityKey?: string;
      characterName: string;
      url: string;
      scale: number;
      slot?: number;
      x?: number;
      y?: number;
      avatarType: string;
      modelUrl: string;
    })
  | (ChatEventBase & { type: "sprite.remove"; characterName: string })
  | (ChatEventBase & { type: "background.change"; url: string })
  | (ChatEventBase & { type: "bgm.change"; url: string })
  | (ChatEventBase & { type: "cg.show"; url: string })
  | (ChatEventBase & { type: "cg.hide" })
  | (ChatEventBase & { type: "options.show"; options: ChatOption[]; selectedIndex?: number | null })
  | (ChatEventBase & { type: "replay.state"; replay: ChatReplayProgress | null })
  | (ChatEventBase & { type: "presentation.restore"; presentation: ChatPresentation })
  | (ChatEventBase & { type: "options.clear" })
  | (ChatEventBase & { type: "story.state.replace"; story: ChatStoryState })
  | (ChatEventBase & {
      type: "story.node.entered" | "story.node.unlocked" | "story.cast.replace" | "story.ending.reached";
      payload: Record<string, unknown>;
      revision: number;
    })
  | (ChatEventBase & {
      type: "tool.confirmation.show";
      confirmationId: string;
      detail?: string;
      risk: "high" | "medium";
      toolName: string;
    })
  | (ChatEventBase & { type: "tool.confirmation.clear"; confirmationId: string })
  | (ChatEventBase & { type: "numeric.update"; html: string })
  | (ChatEventBase & { type: "stats.update"; stats: ChatStat[] })
  | (ChatEventBase & { type: "busy.show"; text: string; durationSeconds: number })
  | (ChatEventBase & { type: "busy.hide" })
  | (ChatEventBase & { type: "notification.change"; text: string })
  | (ChatEventBase & { type: "status.change"; status: ChatRuntimeStatus })
  | (ChatEventBase & {
      type: "tts.play";
      url: string;
      characterName: string;
      playbackId?: string;
      rendererId?: string;
      volume?: number;
    })
  | (ChatEventBase & { type: "tts.skip"; playbackId?: string })
  | (ChatEventBase & { type: "effect.play"; url: string })
  | (ChatEventBase & { type: "effect.image.show"; durationMs: number; label: string; url: string })
  | (ChatEventBase & { type: "effect.loop.start"; key: string; url: string })
  | (ChatEventBase & { type: "effect.loop.stop"; key: string })
  | (ChatEventBase & { type: "effect.loop.stop-all" })
  | (ChatEventBase & { type: "asr.partial"; text: string })
  | (ChatEventBase & { type: "asr.final"; text: string })
  | (ChatEventBase & { type: "asr.state"; enabled?: boolean; loading?: boolean; running: boolean })
  | (ChatEventBase & { type: "perception.state"; perception: PerceptionRuntimeState })
  | (ChatEventBase & { type: "sprite.reaction"; characterName: string; text: string; durationMs: number })
  | (ChatEventBase & { type: "perception.capture_request"; reason?: string })
  | (ChatEventBase & { type: "reply.finished" })
  | (ChatEventBase & { type: "session.closed"; reason: string });

export interface ChatPlatform {
  getCurrentConversation: () => Promise<ConversationSummary | null>;
  reconfigureConversation: (
    id: string,
    payload: ChatLaunchPayload,
    options?: TaskProgressOptions<ChatSnapshot>,
  ) => Promise<ChatSnapshot>;
  listConversations: () => Promise<ConversationSummary[]>;
  prepareConversation: (id: string) => Promise<ChatLaunchPayload>;
  renameConversation: (id: string, title: string) => Promise<ConversationSummary>;
  deleteConversation: (id: string) => Promise<void>;
  close: (options?: ChatCloseOptions) => Promise<ChatSnapshot>;
  command: (command: ChatCommand) => Promise<ChatCommandResult>;
  getHistory: () => Promise<ChatHistoryEntry[]>;
  getHistoryVoice: (voiceId: string) => Promise<string[]>;
  prepareReplay: () => Promise<ChatReplaySnapshot>;
  getReplay: (id: string) => Promise<{ snapshot: ChatReplaySnapshot; generate: boolean }>;
  startReplay: (id: string, startKey: string, endKey: string, generate: boolean) => Promise<void>;
  generateReplayVoice: (id: string, key: string, signal?: AbortSignal) => Promise<ChatReplayVoice>;
  cancelReplay: (id: string) => Promise<void>;
  controlReplay: (id: string, control: ChatReplayControl) => Promise<void>;
  getRuntimeStatus: () => Promise<ChatRuntimeProcessState>;
  getSnapshot: (options?: ChatSnapshotOptions) => Promise<ChatSnapshot>;
  getTheme: () => Promise<ChatThemePayload>;
  launch: (payload: ChatLaunchPayload, options?: TaskProgressOptions<ChatSnapshot>) => Promise<ChatSnapshot>;
  resumeLast: (options?: TaskProgressOptions<ChatSnapshot>, overrides?: ChatResumeOverrides) => Promise<ChatSnapshot>;
  subscribe: (listener: (snapshot: ChatSnapshot) => void) => () => void;
  listThemes: () => Promise<ChatThemeSummary[]>;
  getThemeManifest: (id: string) => Promise<ChatThemeManifest>;
  getActiveThemeId: () => Promise<string>;
  setActiveThemeId: (id: string) => Promise<void>;
  /** 上传一个主题 .zip 安装（multipart）；返回安装后的概要。 */
  uploadTheme: (file: File) => Promise<ChatThemeSummary>;
  /** 上传聊天图片附件（multipart）；复制进允许目录后返回可直接发送的暂存附件。 */
  uploadAttachments: (files: File[]) => Promise<{ attachments: ChatAttachmentInput[] }>;
  /** 创建或更新用户主题，同时保留主题目录中的资源文件。 */
  saveTheme: (input: SaveChatThemeInput) => Promise<ChatThemeSummary>;
  /** 删除一个用户主题。 */
  deleteTheme: (id: string) => Promise<void>;
  subscribeEvents: (listener: (event: ChatStageEvent) => void) => () => void;
}

export interface StoryPlatform {
  readDocument: (storyPath: string) => Promise<StoryDocument>;
  saveDocument: (input: StoryEditInput) => Promise<StoryDocument>;
  suggestGraph: (input: StorySuggestionInput) => Promise<StorySuggestion>;
  list: () => Promise<StoryLibraryEntry[]>;
  delete: (storyPath: string) => Promise<void>;
  prepareLaunch: (storyPath: string, historyPath?: string) => Promise<ChatLaunchPayload>;
  getPreview: (id: string) => Promise<StoryGenerationPreview>;
  startSession: (storyPath: string) => Promise<ChatSnapshot>;
  cancelGeneration: (id: string) => Promise<StoryGenerationTask>;
  getGeneration: (id: string) => Promise<StoryGenerationTask>;
  regenerateGeneration: (
    id: string,
    stage: StoryGenerationStage,
    options?: TaskProgressOptions<StoryGenerationTask>,
  ) => Promise<StoryGenerationTask>;
  resumeGeneration: (id: string, options?: TaskProgressOptions<StoryGenerationTask>) => Promise<StoryGenerationTask>;
  startGeneration: (
    input: StoryGenerationInput,
    options?: TaskProgressOptions<StoryGenerationTask>,
  ) => Promise<StoryGenerationTask>;
}
