import { applyStageEvent } from "./events";
import { clearTransientNotificationState, withResolvedLayers } from "./layers";
import { hydrateFromSnapshot, snapshotEventSeq } from "./snapshot";
import type { ChatStageAction, ChatStageState } from "./types";

function preserveOptimisticPresentation(state: ChatStageState, next: ChatStageState): ChatStageState {
  return withResolvedLayers({
    ...next,
    characterName: state.characterName,
    dialogHtml: state.dialogHtml,
    dialogText: state.dialogText,
    inputDraft: state.inputDraft,
    optimisticSubmission: state.optimisticSubmission,
    options: [...state.options],
    sessionClosedReason: state.sessionClosedReason,
    status: state.status,
    systemMessageText: state.systemMessageText,
  });
}

function snapshotReplacesOptimisticPresentation(
  state: ChatStageState,
  snapshot: ChatStageState,
  authoritativeEventSeq: number,
): boolean {
  const optimistic = state.optimisticSubmission;
  if (!optimistic) {
    return true;
  }
  if (snapshot.sessionClosedReason || snapshot.options.length > 0 || snapshot.systemMessageText?.trim()) {
    return true;
  }
  if (authoritativeEventSeq <= optimistic.eventSeq) {
    return false;
  }
  const dialogText = snapshot.dialogText.trim();
  const speaker = snapshot.characterName?.trim();
  const userName = state.userDisplayName.trim();
  if (speaker && speaker !== userName) {
    return true;
  }
  return Boolean(dialogText && dialogText !== optimistic.text);
}

export function chatStageReducer(state: ChatStageState, action: ChatStageAction): ChatStageState {
  switch (action.type) {
    case "event": {
      const next = applyStageEvent(state, action.event);
      if (!state.optimisticSubmission || next === state) {
        return next;
      }
      if (action.event.type === "snapshot") {
        const authoritativeEventSeq = snapshotEventSeq(action.event.snapshot);
        if (authoritativeEventSeq <= state.eventSeq) {
          return state;
        }
        return snapshotReplacesOptimisticPresentation(state, next, authoritativeEventSeq)
          ? { ...next, optimisticSubmission: undefined }
          : preserveOptimisticPresentation(state, next);
      }
      if (["dialog.end", "options.show", "session.closed"].includes(action.event.type)) {
        return { ...next, optimisticSubmission: undefined };
      }
      return next;
    }
    case "hydrate": {
      const next = hydrateFromSnapshot(state, action.snapshot);
      if (!state.optimisticSubmission || next === state) {
        return next;
      }
      // Hydration requests may have started before the user submitted. Keep the
      // local presentation until the event stream publishes a newer response.
      return action.snapshot.sessionClosedReason
        ? { ...next, optimisticSubmission: undefined }
        : preserveOptimisticPresentation(state, next);
    }
    case "submitUserMessage":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        characterName: state.userDisplayName,
        dialogHtml: undefined,
        dialogText: action.text,
        error: undefined,
        inputDraft: "",
        optimisticSubmission: {
          eventSeq: state.eventSeq,
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
          text: action.text,
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
