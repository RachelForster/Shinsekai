import { defaultLayers } from "./layers";
import { defaultUserDialogSpeaker } from "./text";
import type { ChatStageState } from "./types";

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
