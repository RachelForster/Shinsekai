import { applyStageEvent } from "./events";
import { clearTransientNotificationState, withResolvedLayers } from "./layers";
import { hydrateFromSnapshot } from "./snapshot";
import type { ChatStageAction, ChatStageState } from "./types";

export function chatStageReducer(state: ChatStageState, action: ChatStageAction): ChatStageState {
  switch (action.type) {
    case "event": {
      const next = applyStageEvent(state, action.event);
      const authoritativeEvent =
        (action.event.type === "snapshot" && next !== state) ||
        (action.event.type !== "transport.state" && action.event.seq > state.eventSeq);
      return authoritativeEvent ? { ...next, optimisticSubmission: undefined } : next;
    }
    case "hydrate":
      return hydrateFromSnapshot(state, action.snapshot);
    case "submitUserMessage":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        characterName: state.userDisplayName,
        dialogHtml: undefined,
        dialogText: action.text,
        error: undefined,
        inputDraft: "",
        optimisticSubmission: {
          previous: {
            characterName: state.characterName,
            dialogHtml: state.dialogHtml,
            dialogText: state.dialogText,
            error: state.error,
            inputDraft: state.inputDraft,
            notificationText: state.notificationText,
            options: [...state.options],
            sessionClosedReason: state.sessionClosedReason,
            status: state.status,
            systemMessageText: state.systemMessageText,
          },
          source: action.source ?? "send-message",
        },
        options: [],
        sessionClosedReason: undefined,
        status: "generating",
        systemMessageText: undefined,
      });
    case "rollbackUserSubmission": {
      const optimistic = state.optimisticSubmission;
      if (!optimistic || optimistic.source !== action.source) {
        return state;
      }
      return withResolvedLayers({
        ...state,
        ...optimistic.previous,
        options: [...optimistic.previous.options],
        optimisticSubmission: undefined,
      });
    }
    case "commitUserSubmission":
      return state.optimisticSubmission?.source === action.source
        ? { ...state, optimisticSubmission: undefined }
        : state;
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
