import type { ChatStageEvent } from "../../../shared/platform/types";
import { clearTransientNotificationState, withResolvedLayers } from "./layers";
import { hydrateFromSnapshot, snapshotEventSeq } from "./snapshot";
import { htmlToText } from "./text";
import type { ChatAudioCommand, ChatStageSprite, ChatStageState } from "./types";
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

function appendAudioCommand(state: ChatStageState, command: ChatAudioCommand) {
  return [...state.audioCommands, command].slice(-32);
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
    case "chat.turn.state":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        turnOptions: event.options ? { ...event.options } : state.turnOptions,
        turnState: {
          ...event.state,
          pendingMessages: [...(event.state.pendingMessages ?? [])],
        },
      });
    case "plugin.page.present": {
      const presentation = {
        mode: "overlay" as const,
        pageId: event.pageId,
        payload: { ...event.payload },
        pluginId: event.pluginId,
        presentationId: event.presentationId,
      };
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        pluginPagePresentations: [
          ...(state.pluginPagePresentations ?? []).filter(
            (item) => item.pluginId !== presentation.pluginId || item.presentationId !== presentation.presentationId,
          ),
          presentation,
        ].slice(-8),
      });
    }
    case "plugin.page.dismiss":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        pluginPagePresentations: (state.pluginPagePresentations ?? []).filter(
          (item) => item.pluginId !== event.pluginId || item.presentationId !== event.presentationId,
        ),
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
        toolConfirmation: null,
      });
    case "options.clear":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: [],
      });
    case "story.state.replace":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: event.story.options,
        story: event.story,
      });
    case "story.node.entered":
    case "story.node.unlocked":
    case "story.cast.replace":
    case "story.ending.reached":
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        story: state.story
          ? {
              ...state.story,
              lastEvent: {
                payload: event.payload,
                revision: event.revision,
                type: event.type,
              },
            }
          : undefined,
      });
    case "tool.confirmation.show":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        eventSeq: Math.max(state.eventSeq, event.seq),
        options: [],
        toolConfirmation: {
          confirmationId: event.confirmationId,
          detail: event.detail,
          risk: event.risk,
          toolName: event.toolName,
        },
      });
    case "tool.confirmation.clear":
      if (state.toolConfirmation && state.toolConfirmation.confirmationId !== event.confirmationId) {
        return withResolvedLayers({
          ...state,
          eventSeq: Math.max(state.eventSeq, event.seq),
        });
      }
      return withResolvedLayers({
        ...state,
        eventSeq: Math.max(state.eventSeq, event.seq),
        toolConfirmation: null,
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
        activePlayback: {
          characterName: event.characterName,
          playbackId: event.playbackId ?? "",
          rendererId: event.rendererId,
          seq: event.seq,
          url: event.url,
          volume:
            typeof event.volume === "number" && Number.isFinite(event.volume)
              ? Math.min(1, Math.max(0, event.volume))
              : 1,
        },
        audioCommands: appendAudioCommand(state, {
          kind: "voice-play",
          playbackId: event.playbackId ?? "",
          rendererId: event.rendererId,
          seq: event.seq,
          url: event.url,
          volume:
            typeof event.volume === "number" && Number.isFinite(event.volume)
              ? Math.min(1, Math.max(0, event.volume))
              : 1,
        }),
        characterName: event.characterName,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: "speaking",
      });
    case "tts.skip": {
      const shouldStop = !event.playbackId || state.activePlayback?.playbackId === event.playbackId;
      return withResolvedLayers({
        ...state,
        activePlayback: shouldStop ? null : state.activePlayback,
        audioCommands: appendAudioCommand(state, {
          kind: "voice-stop",
          playbackId: event.playbackId ?? "",
          seq: event.seq,
        }),
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: shouldStop && state.status === "speaking" ? "idle" : state.status,
      });
    }
    case "effect.play":
      return withResolvedLayers({
        ...state,
        audioCommands: appendAudioCommand(state, {
          kind: "effect-play",
          seq: event.seq,
          url: event.url,
        }),
        eventSeq: Math.max(state.eventSeq, event.seq),
      });
    case "effect.loop.start":
      return withResolvedLayers({
        ...state,
        audioCommands: appendAudioCommand(state, {
          key: event.key,
          kind: "effect-loop-start",
          seq: event.seq,
          url: event.url,
        }),
        eventSeq: Math.max(state.eventSeq, event.seq),
        loopingEffects: [
          ...(state.loopingEffects ?? []).filter((effect) => effect.key !== event.key),
          { key: event.key, seq: event.seq, url: event.url },
        ].slice(-32),
      });
    case "effect.loop.stop":
      return withResolvedLayers({
        ...state,
        audioCommands: appendAudioCommand(state, {
          key: event.key,
          kind: "effect-loop-stop",
          seq: event.seq,
        }),
        eventSeq: Math.max(state.eventSeq, event.seq),
        loopingEffects: (state.loopingEffects ?? []).filter((effect) => effect.key !== event.key),
      });
    case "effect.loop.stop-all":
      return withResolvedLayers({
        ...state,
        audioCommands: appendAudioCommand(state, {
          kind: "effect-loop-stop-all",
          seq: event.seq,
        }),
        eventSeq: Math.max(state.eventSeq, event.seq),
        loopingEffects: [],
      });
    case "asr.partial":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        asrEnabled: true,
        asrLoading: false,
        asrRunning: true,
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
        inputDraft: "",
        options: [],
      });
    case "asr.state": {
      const asrEnabled = event.enabled ?? event.running;
      const replyInProgress = ["generating", "streaming", "speaking"].includes(state.status);
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        asrEnabled,
        asrLoading: Boolean(event.loading) && asrEnabled,
        asrRunning: event.running && asrEnabled,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: event.running ? "listening" : replyInProgress ? state.status : "paused",
      });
    }
    case "reply.finished":
      return withResolvedLayers({
        ...clearTransientNotificationState(state),
        activePlayback: null,
        eventSeq: Math.max(state.eventSeq, event.seq),
        status: state.status === "generating" || state.status === "streaming" ? "idle" : state.status,
      });
    case "session.closed":
      return withResolvedLayers({
        ...state,
        activePlayback: null,
        audioCommands: appendAudioCommand(state, {
          kind: "all-stop",
          seq: event.seq,
        }),
        busyDurationSeconds: undefined,
        busyText: undefined,
        eventSeq: Math.max(state.eventSeq, event.seq),
        notificationText: event.reason,
        loopingEffects: [],
        options: [],
        pluginPagePresentations: [],
        sessionClosedReason: event.reason,
        status: "idle",
        systemMessageText: undefined,
        toolConfirmation: null,
      });
    default:
      return state;
  }
}
