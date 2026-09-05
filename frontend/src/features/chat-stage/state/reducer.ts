import { mergeChatAttachmentInputs } from "../attachments";
import { applyStageEvent } from "./events";
import { clearTransientNotificationState, withResolvedLayers } from "./layers";
import { hydrateFromSnapshot, snapshotEventSeq } from "./snapshot";
import { normalizedUserDisplayName } from "./text";
import type { ChatStageAction, ChatStageState } from "./types";

function preserveOptimisticPresentation(state: ChatStageState, next: ChatStageState): ChatStageState {
  return withResolvedLayers({
    ...next,
    characterName: state.characterName,
    dialogHtml: state.dialogHtml,
    dialogText: state.dialogText,
    inputAttachments: state.inputAttachments,
    inputDraft: state.inputDraft,
    asrUtteranceId: state.asrUtteranceId,
    optimisticSubmission: state.optimisticSubmission,
    options: [...state.options],
    sessionClosedReason: state.sessionClosedReason,
    status: state.status,
    statusMessage: state.statusMessage,
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
  if (snapshot.sessionClosedReason || snapshot.options.length > 0) {
    return true;
  }
  if (
    snapshot.story &&
    (snapshot.story.ending ||
      snapshot.story.revision !== state.story?.revision ||
      snapshot.story.currentNodeId !== state.story?.currentNodeId)
  ) {
    return true;
  }
  if (authoritativeEventSeq <= optimistic.eventSeq) {
    return false;
  }
  const dialogText = snapshot.dialogText.trim();
  const dialogHtml = snapshot.dialogHtml?.trim();
  const speaker = snapshot.characterName?.trim();
  const statusMessage = snapshot.statusMessage?.trim();
  const userName = normalizedUserDisplayName(state.userDisplayName);
  const hasDialogContent = Boolean(dialogHtml || dialogText);
  const isCommandFeedback = Boolean(statusMessage && !dialogHtml && statusMessage === dialogText);
  if (!hasDialogContent || isCommandFeedback) {
    return false;
  }
  return Boolean(speaker && speaker !== userName);
}

function submitUserMessageState(
  state: ChatStageState,
  {
    preserveInput = false,
    queued,
    source = "send-message",
    text,
  }: {
    queued?: boolean;
    preserveInput?: boolean;
    source?: "send-message" | "submit-option";
    text: string;
  },
): ChatStageState {
  const optimisticSubmission: NonNullable<ChatStageState["optimisticSubmission"]> = {
    attachmentsEditedAfterSubmission: false,
    draftEditedAfterSubmission: false,
    eventSeq: state.eventSeq,
    previous: {
      characterName: state.characterName,
      dialogHtml: state.dialogHtml,
      dialogText: state.dialogText,
      error: state.error,
      asrUtteranceId: state.asrUtteranceId,
      inputDraft: state.inputDraft,
      inputAttachments: state.inputAttachments.map((attachment) => ({ ...attachment })),
      notificationText: state.notificationText,
      options: [...state.options],
      sessionClosedReason: state.sessionClosedReason,
      status: state.status,
      statusMessage: state.statusMessage,
      systemMessageText: state.systemMessageText,
    },
    source,
    text,
  };
  const preservedInput = preserveInput
    ? {
        asrUtteranceId: state.asrUtteranceId,
        inputAttachments: state.inputAttachments,
        inputDraft: state.inputDraft,
      }
    : {
        asrUtteranceId: null,
        inputAttachments: [],
        inputDraft: "",
      };
  if (queued) {
    // Batch/queued submissions must still show the user's own message instead of
    // leaving the previous turn's reply on screen (which reads as the dialogue
    // "rolling back" to the last message). Present it like a normal submission; the
    // batch flush timing is handled by the command layer, not the presentation.
    return withResolvedLayers({
      ...clearTransientNotificationState(state),
      characterName: normalizedUserDisplayName(state.userDisplayName),
      dialogHtml: undefined,
      dialogText: text,
      ...preservedInput,
      optimisticSubmission,
      options: [],
    });
  }
  return withResolvedLayers({
    ...clearTransientNotificationState(state),
    characterName: normalizedUserDisplayName(state.userDisplayName),
    dialogHtml: undefined,
    dialogText: text,
    error: undefined,
    ...preservedInput,
    optimisticSubmission,
    options: [],
    sessionClosedReason: undefined,
    status: "generating",
    statusMessage: undefined,
    systemMessageText: undefined,
  });
}

export function chatStageReducer(state: ChatStageState, action: ChatStageAction): ChatStageState {
  switch (action.type) {
    case "event": {
      const next = applyStageEvent(state, action.event);
      if (
        next !== state &&
        action.event.type === "asr.final" &&
        action.event.text.trim() &&
        !state.optimisticSubmission &&
        !["generating", "streaming", "speaking"].includes(state.status)
      ) {
        return submitUserMessageState(next, {
          preserveInput: Boolean(next.inputDraft),
          queued: next.turnOptions.batchEnabled,
          text: action.event.text.trim(),
        });
      }
      if (!state.optimisticSubmission || next === state) {
        return next;
      }
      if (action.event.type === "snapshot") {
        const authoritativeEventSeq = Math.max(snapshotEventSeq(action.event.snapshot), action.event.seq);
        if (authoritativeEventSeq <= state.eventSeq) {
          return state;
        }
        return snapshotReplacesOptimisticPresentation(state, next, authoritativeEventSeq)
          ? { ...next, optimisticSubmission: undefined }
          : preserveOptimisticPresentation(state, next);
      }
      if (["dialog.end", "options.show", "session.closed", "story.state.replace"].includes(action.event.type)) {
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
      return submitUserMessageState(state, action);
    case "rollbackUserSubmission": {
      const optimistic = state.optimisticSubmission;
      if (!optimistic || optimistic.source !== action.source) {
        return state;
      }
      const inputDraft = optimistic.draftEditedAfterSubmission ? state.inputDraft : optimistic.previous.inputDraft;
      const asrUtteranceId = optimistic.draftEditedAfterSubmission
        ? state.asrUtteranceId
        : optimistic.previous.asrUtteranceId;
      const inputAttachments = optimistic.attachmentsEditedAfterSubmission
        ? state.inputAttachments
        : optimistic.previous.inputAttachments;
      return withResolvedLayers({
        ...state,
        ...optimistic.previous,
        asrUtteranceId,
        inputDraft,
        inputAttachments: inputAttachments.map((attachment) => ({ ...attachment })),
        options: [...optimistic.previous.options],
        optimisticSubmission: undefined,
      });
    }
    case "setHistoryEntries":
      return withResolvedLayers({
        ...state,
        historyEntries: action.historyEntries.map((entry) => ({ ...entry })),
      });
    case "addAttachments":
      return withResolvedLayers({
        ...state,
        inputAttachments: mergeChatAttachmentInputs(state.inputAttachments, action.attachments),
        optimisticSubmission: state.optimisticSubmission
          ? { ...state.optimisticSubmission, attachmentsEditedAfterSubmission: true }
          : undefined,
      });
    case "setAttachments":
      return withResolvedLayers({
        ...state,
        inputAttachments: action.attachments.map((attachment) => ({ ...attachment })),
        optimisticSubmission: state.optimisticSubmission
          ? { ...state.optimisticSubmission, attachmentsEditedAfterSubmission: true }
          : undefined,
      });
    case "setDraft":
      return withResolvedLayers({
        ...state,
        asrUtteranceId: null,
        inputDraft: action.text,
        optimisticSubmission: state.optimisticSubmission
          ? { ...state.optimisticSubmission, draftEditedAfterSubmission: true }
          : undefined,
      });
    case "setTurnOptions":
      return withResolvedLayers({
        ...state,
        turnOptions: { ...action.options },
      });
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
