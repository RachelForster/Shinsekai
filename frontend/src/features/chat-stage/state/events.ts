import type { ChatStageEvent } from "../../../shared/platform/types";
import { clearTransientNotificationState, withResolvedLayers } from "./layers";
import { hydrateFromSnapshot, snapshotEventSeq } from "./snapshot";
import { htmlToText } from "./text";
import type { ChatStageSprite, ChatStageState } from "./types";
import { upsertChatStageSprite } from "./sprites";

function upsertSprite(state: ChatStageState, event: Extract<ChatStageEvent, { type: "sprite.show" }>): ChatStageState {
  const id = event.characterName;
  const nextSprite: ChatStageSprite = {
    characterName: event.characterName,
    id,
    label: event.characterName,
    path: event.url,
    scale: event.scale,
    slot: event.slot,
    x: event.x,
    y: event.y,
  };
  const sprites = upsertChatStageSprite(state.sprites, nextSprite);
  return withResolvedLayers({
    ...clearTransientNotificationState(state),
    eventSeq: Math.max(state.eventSeq, event.seq),
    sprites,
  });
}

function removeSprite(
  state: ChatStageState,
  event: Extract<ChatStageEvent, { type: "sprite.remove" }>,
): ChatStageState {
  return withResolvedLayers({
    ...state,
    eventSeq: Math.max(state.eventSeq, event.seq),
    sprites: state.sprites.filter(
      (sprite) => sprite.id !== event.characterName && sprite.label !== event.characterName,
    ),
  });
}

export function applyStageEvent(state: ChatStageState, event: ChatStageEvent): ChatStageState {
  if (event.type === "transport.state") {
    return withResolvedLayers({
      ...state,
      transportMode: event.transport,
      transportState: event.state,
    });
  }
  if (event.type !== "snapshot" && event.seq <= state.eventSeq) {
    return state;
  }
  switch (event.type) {
    case "snapshot":
      return hydrateFromSnapshot(state, {
        ...event.snapshot,
        eventSeq: Math.max(snapshotEventSeq(event.snapshot), event.seq),
      });
    case "chat.init.progress":
    case "chat.init.completed":
    case "chat.init.failed":
    case "chat.init.cancelled":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        initTask: { ...event.task },
      });
    case "dialog.end":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        error: undefined,
        ...(event.isSystem && !event.speaker.trim()
          ? { systemMessageText: htmlToText(event.fullHtml) }
          : {
              characterName: event.speaker,
              dialogHtml: event.fullHtml,
              dialogText: htmlToText(event.fullHtml),
              options: [],
              systemMessageText: undefined,
            }),
      });
    case "user.display_name.change":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        userDisplayName: event.name.trim() || state.userDisplayName,
      });
    case "history.replace":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        historyEntries: event.entries.map((entry) => ({ ...entry })),
      });
    case "conversation.tree":
      return withResolvedLayers({
        ...state,
        conversationTree: {
          activeBranchId: event.tree.activeBranchId,
          branches: event.tree.branches.map((branch) => ({ ...branch })),
        },
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "sprite.show":
      return upsertSprite(state, event);
    case "sprite.remove":
      return removeSprite(state, event);
    case "background.change":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        backgroundPath: event.url,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "bgm.change":
      return withResolvedLayers({
        ...state,
        bgmPath: event.url,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "cg.show":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        cgPath: event.url,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "cg.hide":
      return withResolvedLayers({
        ...state,
        cgPath: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "options.show":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: event.options,
      });
    case "options.clear":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: [],
      });
    case "numeric.update":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        numericInfo: htmlToText(event.html),
      });
    case "stats.update":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        stats: event.stats.map((stat) => ({ ...stat })),
      });
    case "busy.show":
      return withResolvedLayers({
        ...state,
        busyDurationSeconds: event.durationSeconds,
        busyText: event.text,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "busy.hide":
      return withResolvedLayers({
        ...state,
        busyDurationSeconds: undefined,
        busyText: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "notification.change":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        notificationText: event.text,
      });
    case "status.change":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: event.status,
      });
    case "tts.play":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        characterName: event.characterName,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: "speaking",
      });
    case "tts.skip":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: state.status === "speaking" ? "idle" : state.status,
      });
    case "asr.partial":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        asrTranscript: event.text,
        eventSeq: Math.max(state.eventSeq, event.seq),
        inputDraft: event.text,
        status: "listening",
      });
    case "asr.final":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        asrTranscript: event.text,
        eventSeq: Math.max(state.eventSeq, event.seq),
        inputDraft: event.text,
      });
    case "asr.state":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: event.running ? "listening" : "paused",
      });
    case "reply.finished":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: state.status === "generating" || state.status === "streaming" ? "idle" : state.status,
      });
    case "session.closed":
      return withResolvedLayers({
        ...state,
        busyDurationSeconds: undefined,
        busyText: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
        notificationText: event.reason,
        options: [],
        sessionClosedReason: event.reason,
        status: "idle",
        systemMessageText: undefined,
      });
    default:
      return state;
  }
}
