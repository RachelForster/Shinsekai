import { clearTransientNotificationState, withResolvedLayers } from "../layers";
import { appendAudioCommand, type StageEventHandlerMap } from "./types";

type AudioEffectEventType =
  | "tts.play"
  | "tts.skip"
  | "effect.play"
  | "effect.image.show"
  | "effect.loop.start"
  | "effect.loop.stop"
  | "effect.loop.stop-all"
  | "ambient.start"
  | "ambient.layer"
  | "ambient.stop"
  | "ambient.stop-all";

export const audioEffectHandlers: Pick<StageEventHandlerMap, AudioEffectEventType> = {
  "tts.play": (state, event, ctx) => {
    const volume =
      typeof event.volume === "number" && Number.isFinite(event.volume) ? Math.min(1, Math.max(0, event.volume)) : 1;
    return withResolvedLayers({
      ...clearTransientNotificationState(state),
      activePlayback: {
        characterName: event.characterName,
        playbackId: event.playbackId ?? "",
        rendererId: event.rendererId,
        seq: event.seq,
        url: event.url,
        volume,
      },
      audioCommands: appendAudioCommand(state, {
        kind: "voice-play",
        characterName: event.characterName,
        playbackId: event.playbackId ?? "",
        rendererId: event.rendererId,
        seq: event.seq,
        url: event.url,
        volume,
      }),
      characterName: event.characterName,
      eventSeq: ctx.eventSeq,
      spriteReaction: null,
      status: "speaking",
    });
  },
  "tts.skip": (state, event, ctx) => {
    const shouldStop = !event.playbackId || state.activePlayback?.playbackId === event.playbackId;
    return withResolvedLayers({
      ...state,
      activePlayback: shouldStop ? null : state.activePlayback,
      audioCommands: appendAudioCommand(state, {
        kind: "voice-stop",
        playbackId: event.playbackId ?? "",
        seq: event.seq,
      }),
      eventSeq: ctx.eventSeq,
      status: shouldStop && state.status === "speaking" ? "idle" : state.status,
    });
  },
  "effect.play": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      audioCommands: appendAudioCommand(state, {
        kind: "effect-play",
        seq: event.seq,
        url: event.url,
      }),
      eventSeq: ctx.eventSeq,
    }),
  "effect.image.show": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      effectImage: {
        deadline: ctx.receivedAt + Math.max(0, event.durationMs),
        durationMs: Math.max(0, event.durationMs),
        label: event.label,
        seq: event.seq,
        url: event.url,
      },
      eventSeq: ctx.eventSeq,
    }),
  "effect.loop.start": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      audioCommands: appendAudioCommand(state, {
        key: event.key,
        kind: "effect-loop-start",
        seq: event.seq,
        url: event.url,
      }),
      eventSeq: ctx.eventSeq,
      loopingEffects: [
        ...(state.loopingEffects ?? []).filter((effect) => effect.key !== event.key),
        { key: event.key, seq: event.seq, url: event.url },
      ].slice(-32),
    }),
  "effect.loop.stop": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      audioCommands: appendAudioCommand(state, {
        key: event.key,
        kind: "effect-loop-stop",
        seq: event.seq,
      }),
      eventSeq: ctx.eventSeq,
      loopingEffects: (state.loopingEffects ?? []).filter((effect) => effect.key !== event.key),
    }),
  "effect.loop.stop-all": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      audioCommands: appendAudioCommand(state, {
        kind: "effect-loop-stop-all",
        seq: event.seq,
      }),
      eventSeq: ctx.eventSeq,
      loopingEffects: [],
    }),
  "ambient.start": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      ambientEffects: [
        ...(state.ambientEffects ?? []).filter((effect) => effect.key !== event.key),
        {
          audioUrl: event.audioUrl ?? "",
          key: event.key,
          layer: event.layer,
          seq: event.seq,
          url: event.url,
        },
      ].slice(-32),
      eventSeq: ctx.eventSeq,
    }),
  "ambient.layer": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      ambientEffects: (state.ambientEffects ?? []).map((effect) =>
        effect.key === event.key
          ? {
              ...effect,
              layer: event.layer,
              ...(event.audioUrl !== undefined ? { audioUrl: event.audioUrl } : {}),
            }
          : effect,
      ),
      eventSeq: ctx.eventSeq,
    }),
  "ambient.stop": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      ambientEffects: (state.ambientEffects ?? []).filter((effect) => effect.key !== event.key),
      eventSeq: ctx.eventSeq,
    }),
  "ambient.stop-all": (state, _event, ctx) =>
    withResolvedLayers({
      ...state,
      ambientEffects: [],
      eventSeq: ctx.eventSeq,
    }),
};
