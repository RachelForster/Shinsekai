import { defaultLayers } from "./layers";
import { defaultUserDialogSpeaker } from "./text";
import type { ChatStageState } from "./types";

export const emptyChatState: ChatStageState = {
  asrEnabled: false,
  asrLoading: false,
  asrRunning: false,
  dialogText: "",
  eventSeq: 0,
  inputAttachments: [],
  inputDraft: "",
  layers: defaultLayers(),
  options: [],
  pluginPagePresentations: [],
  sprites: [],
  stats: [],
  status: "idle",
  toolConfirmation: null,
  transportMode: "snapshot",
  transportState: "connecting",
  turnOptions: {
    batchEnabled: false,
    batchIdleSeconds: 5,
    interruptEnabled: true,
  },
  turnState: {
    enabled: false,
    pendingCount: 0,
    pendingMessages: [],
    remainingSeconds: null,
    scheduled: false,
    typing: false,
  },
  userDisplayName: defaultUserDialogSpeaker,
};
