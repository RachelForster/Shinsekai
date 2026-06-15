import { applyStageEvent } from "./events";
import { withResolvedLayers } from "./layers";
import { hydrateFromSnapshot } from "./snapshot";
import type { ChatStageAction, ChatStageState } from "./types";

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
