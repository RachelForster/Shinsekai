import type {
  ChatHistoryEntry,
  ChatRuntimeStatus,
  ChatSnapshot,
  ChatSprite,
  ChatStat,
  ChatStageEvent,
  ChatTurnOptions,
  ChatTurnState,
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
  optimisticSubmission?: {
    draftEditedAfterSubmission: boolean;
    eventSeq: number;
    previous: {
      characterName?: string;
      dialogHtml?: string;
      dialogText: string;
      error?: string;
      inputDraft: string;
      notificationText?: string;
      options: string[];
      sessionClosedReason?: string;
      status: ChatRuntimeStatus;
      statusMessage?: string;
      systemMessageText?: string;
    };
    source: "send-message" | "submit-option";
    text: string;
  };
  sessionClosedReason?: string;
  sprites: ChatStageSprite[];
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
  turnOptions: ChatTurnOptions;
  turnState: ChatTurnState;
  userDisplayName: string;
}

export interface ChatStageViewModel {
  backgroundPath?: string;
  bgmPath?: string;
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
  stats: ChatStat[];
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
  | { type: "submitUserMessage"; text: string; queued?: boolean; source?: "send-message" | "submit-option" }
  | { type: "rollbackUserSubmission"; source: "send-message" | "submit-option" }
  | { type: "setHistoryEntries"; historyEntries: ChatHistoryEntry[] }
  | { type: "setDraft"; text: string }
  | { type: "setTurnOptions"; options: ChatTurnOptions }
  | { type: "setStatus"; status: ChatRuntimeStatus }
  | { type: "error"; message: string };
