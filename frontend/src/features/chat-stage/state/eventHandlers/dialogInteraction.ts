import { clearTransientNotificationState, withResolvedLayers } from "../layers";
import { htmlToText } from "../text";
import type { StageEventHandlerMap } from "./types";

type DialogInteractionEventType =
  | "dialog.end"
  | "user.display_name.change"
  | "options.show"
  | "options.clear"
  | "tool.confirmation.show"
  | "tool.confirmation.clear"
  | "history.replace"
  | "chat.turn.state"
  | "numeric.update"
  | "stats.update"
  | "busy.show"
  | "busy.hide";

export const dialogInteractionHandlers: Pick<StageEventHandlerMap, DialogInteractionEventType> = {
  "dialog.end": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      eventSeq: ctx.eventSeq,
      error: undefined,
      ...(event.isSystem && !event.speaker.trim()
        ? { isSystemDialog: true, systemMessageText: htmlToText(event.fullHtml) }
        : {
            characterName: event.speaker,
            dialogHtml: event.fullHtml,
            dialogText: htmlToText(event.fullHtml),
            isSystemDialog: false,
            options: [],
            spriteReaction: null,
            systemMessageText: undefined,
          }),
    }),
  "user.display_name.change": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      userDisplayName: event.name.trim() || state.userDisplayName,
    }),
  "options.show": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      replaySelectedIndex: event.selectedIndex,
      eventSeq: ctx.eventSeq,
      options: event.options,
      toolConfirmation: null,
    }),
  "options.clear": (state, _event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      options: [],
    }),
  "tool.confirmation.show": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      eventSeq: ctx.eventSeq,
      options: [],
      toolConfirmation: {
        confirmationId: event.confirmationId,
        detail: event.detail,
        risk: event.risk,
        toolName: event.toolName,
      },
    }),
  "tool.confirmation.clear": (state, event, ctx) => {
    if (state.toolConfirmation && state.toolConfirmation.confirmationId !== event.confirmationId) {
      return withResolvedLayers({
        ...state,
        eventSeq: ctx.eventSeq,
      });
    }
    return withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      toolConfirmation: null,
    });
  },
  "history.replace": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      historyEntries: event.entries.map((entry) => ({ ...entry })),
      voiceArchiveEnabled: event.voiceArchiveEnabled ?? state.voiceArchiveEnabled,
    }),
  "chat.turn.state": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      turnOptions: event.options ? { ...event.options } : state.turnOptions,
      turnState: {
        ...event.state,
        pendingMessages: [...(event.state.pendingMessages ?? [])],
      },
    }),
  "numeric.update": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      numericInfo: htmlToText(event.html),
    }),
  "stats.update": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      stats: event.stats.map((stat) => ({ ...stat })),
    }),
  "busy.show": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      busyDurationSeconds: event.durationSeconds,
      busyText: event.text,
      eventSeq: ctx.eventSeq,
    }),
  "busy.hide": (state, _event, ctx) =>
    withResolvedLayers({
      ...state,
      busyDurationSeconds: undefined,
      busyText: undefined,
      eventSeq: ctx.eventSeq,
    }),
};
