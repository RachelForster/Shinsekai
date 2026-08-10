import type {
  ChatAttachmentInput,
  ChatHistoryEntry,
  ChatOption,
  ChatRuntimeStatus,
  ChatSnapshot,
  ChatSprite,
  ChatStat,
  ChatStageEvent,
  ChatStoryState,
  ChatToolConfirmation,
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

export type ChatAudioCommand =
  | { kind: "voice-play"; playbackId: string; rendererId?: string; seq: number; url: string; volume: number }
  | { kind: "voice-stop"; playbackId: string; seq: number }
  | { kind: "effect-play"; seq: number; url: string }
  | { key: string; kind: "effect-loop-start"; seq: number; url: string }
  | { key: string; kind: "effect-loop-stop"; seq: number }
  | { kind: "effect-loop-stop-all"; seq: number }
  | { kind: "all-stop"; seq: number };

export interface ChatStageState extends Omit<ChatSnapshot, "sprites"> {
  audioCommands: ChatAudioCommand[];
  asrTranscript?: string;
  busyDurationSeconds?: number;
  busyText?: string;
  cgPath?: string;
  dialogHtml?: string;
  error?: string;
  eventSeq: number;
  layers: ChatStageLayers;
  inputAttachments: ChatAttachmentInput[];
  notificationText?: string;
  optimisticSubmission?: {
    attachmentsEditedAfterSubmission: boolean;
    draftEditedAfterSubmission: boolean;
    eventSeq: number;
    previous: {
      characterName?: string;
      dialogHtml?: string;
      dialogText: string;
      error?: string;
      inputDraft: string;
      inputAttachments: ChatAttachmentInput[];
      notificationText?: string;
      options: ChatOption[];
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
  asrEnabled: boolean;
  asrLoading: boolean;
  asrRunning: boolean;
  backgroundPath?: string;
  bgmPath?: string;
  busyText?: string;
  cgPath?: string;
  dialogCharacterName?: string;
  dialogHtml?: string;
  dialogText: string;
  inputDisabled: boolean;
  inputAttachments: ChatAttachmentInput[];
  inputDraft: string;
  layers: ChatStageLayers;
  notificationText?: string;
  options: ChatOption[];
  sprites: ChatStageSprite[];
  story?: ChatStoryState;
  stats: ChatStat[];
  status: ChatRuntimeStatus;
  statusText: string;
  tokenUsageText?: string;
  toolConfirmation?: ChatToolConfirmation | null;
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
  userDisplayName: string;
  voiceLanguage?: string;
}

export type ChatStageAction =
  | { type: "event"; event: ChatStageEvent }
  | { type: "hydrate"; snapshot: ChatSnapshot }
  | { type: "addAttachments"; attachments: ChatAttachmentInput[] }
  | { type: "submitUserMessage"; text: string; queued?: boolean; source?: "send-message" | "submit-option" }
  | { type: "rollbackUserSubmission"; source: "send-message" | "submit-option" }
  | { type: "setHistoryEntries"; historyEntries: ChatHistoryEntry[] }
  | { type: "setAttachments"; attachments: ChatAttachmentInput[] }
  | { type: "setDraft"; text: string }
  | { type: "setTurnOptions"; options: ChatTurnOptions }
  | { type: "setStatus"; status: ChatRuntimeStatus }
  | { type: "error"; message: string };
