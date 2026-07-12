import type {
  ChatHistoryEntry,
  ChatRuntimeStatus,
  ChatSnapshot,
  ChatSprite,
  ChatStageEvent,
  ChatTransportMode,
  ChatTransportState,
} from "../../../shared/platform/types";

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
  | { type: "submitUserMessage"; text: string }
  | { type: "setHistoryEntries"; historyEntries: ChatHistoryEntry[] }
  | { type: "setDraft"; text: string }
  | { type: "setStatus"; status: ChatRuntimeStatus }
  | { type: "error"; message: string };
