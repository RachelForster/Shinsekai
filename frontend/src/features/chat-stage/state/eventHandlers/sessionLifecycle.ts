import { clearTransientNotificationState, withResolvedLayers } from "../layers";
import { hydrateFromSnapshot, snapshotEventSeq } from "../snapshot";
import type { ChatStageState } from "../types";
import { appendAudioCommand, type EventHandlerContext, type StageEventHandlerMap, type StageEventOf } from "./types";

type ChatInitEventType = "chat.init.progress" | "chat.init.completed" | "chat.init.failed" | "chat.init.cancelled";

type SessionLifecycleEventType =
  | "snapshot"
  | ChatInitEventType
  | "replay.state"
  | "status.change"
  | "notification.change"
  | "reply.finished"
  | "session.closed";

function foldChatInitEvent(
  state: ChatStageState,
  event: StageEventOf<ChatInitEventType>,
  ctx: EventHandlerContext,
): ChatStageState {
  return withResolvedLayers({
    ...state,
    eventSeq: ctx.eventSeq,
    initTask: { ...event.task },
  });
}

export const sessionLifecycleHandlers: Pick<StageEventHandlerMap, SessionLifecycleEventType> = {
  snapshot: (state, event, ctx) =>
    hydrateFromSnapshot(
      state,
      {
        ...event.snapshot,
        eventSeq: Math.max(snapshotEventSeq(event.snapshot), event.seq),
      },
      ctx.receivedAt,
    ),
  "chat.init.progress": foldChatInitEvent,
  "chat.init.completed": foldChatInitEvent,
  "chat.init.failed": foldChatInitEvent,
  "chat.init.cancelled": foldChatInitEvent,
  "replay.state": (state, event) =>
    withResolvedLayers({
      ...state,
      eventSeq: event.seq,
      replay: event.replay,
      status: event.replay ? "replaying" : "idle",
    }),
  "status.change": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      eventSeq: ctx.eventSeq,
      status: event.status,
    }),
  "notification.change": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      notificationText: event.text,
    }),
  "reply.finished": (state, _event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      activePlayback: null,
      eventSeq: ctx.eventSeq,
      status:
        state.status === "generating" || state.status === "streaming" || state.status === "speaking"
          ? "idle"
          : state.status,
    }),
  "session.closed": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      ambientEffects: [],
      activePlayback: null,
      audioCommands: appendAudioCommand(state, {
        kind: "all-stop",
        seq: event.seq,
      }),
      busyDurationSeconds: undefined,
      busyText: undefined,
      effectImage: null,
      eventSeq: ctx.eventSeq,
      notificationText: event.reason,
      loopingEffects: [],
      options: [],
      perception: null,
      pluginPagePresentations: [],
      sessionClosedReason: event.reason,
      backgroundTransition: null,
      spriteMotions: {},
      spriteReaction: null,
      status: "idle",
      systemMessageText: undefined,
      toolConfirmation: null,
    }),
};
