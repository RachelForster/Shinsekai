import type { ChatRuntimeStatus, ChatSnapshot } from "../../shared/platform/types";

export interface ChatStageState extends ChatSnapshot {
  error?: string;
}

export type ChatStageAction =
  | { type: "hydrate"; snapshot: ChatSnapshot }
  | { type: "setDraft"; text: string }
  | { type: "setStatus"; status: ChatRuntimeStatus }
  | { type: "error"; message: string };

export function chatStageReducer(state: ChatStageState, action: ChatStageAction): ChatStageState {
  switch (action.type) {
    case "hydrate":
      return { ...state, ...action.snapshot, error: undefined };
    case "setDraft":
      return { ...state, inputDraft: action.text };
    case "setStatus":
      return { ...state, status: action.status };
    case "error":
      return { ...state, error: action.message, status: "error" };
    default:
      return state;
  }
}

export const emptyChatState: ChatStageState = {
  dialogText: "",
  inputDraft: "",
  options: [],
  sprites: [],
  status: "idle",
};
