import type { ChatSnapshot } from "../../../shared/platform/types";
import { emptyChatState } from "./initialState";
import { withResolvedLayers } from "./layers";
import { normalizeChatStageSprites } from "./sprites";
import type { ChatAudioCommand, ChatStageState } from "./types";

export function snapshotEventSeq(snapshot: ChatSnapshot) {
  return typeof snapshot.eventSeq === "number" && Number.isFinite(snapshot.eventSeq) ? snapshot.eventSeq : 0;
}

function transportFromSnapshot(snapshot: ChatSnapshot): Pick<ChatStageState, "transportMode" | "transportState"> {
  if (snapshot.wsUrl && snapshot.sessionId) {
    return {
      transportMode: "websocket",
      transportState: "connecting",
    };
  }
  return {
    transportMode: "snapshot",
    transportState: "connected",
  };
}

function shouldPreserveTransportState(state: ChatStageState) {
  return state.transportMode !== emptyChatState.transportMode || state.transportState !== emptyChatState.transportState;
}

function recoveryAudioCommands(state: ChatStageState, snapshot: ChatSnapshot, snapshotSeq: number): ChatAudioCommand[] {
  const commands: ChatAudioCommand[] = [];
  const previousPlayback = state.activePlayback;
  const activePlayback = snapshot.activePlayback;
  if (previousPlayback?.playbackId && (!activePlayback || previousPlayback.playbackId !== activePlayback.playbackId)) {
    commands.push({
      kind: "voice-stop",
      playbackId: previousPlayback.playbackId,
      seq: snapshotSeq,
    });
  }
  if (activePlayback?.playbackId && activePlayback.url) {
    commands.push({
      kind: "voice-play",
      playbackId: activePlayback.playbackId,
      rendererId: activePlayback.rendererId,
      seq: activePlayback.seq,
      url: activePlayback.url,
      volume: activePlayback.volume,
    });
  }

  const nextLoopKeys = new Set((snapshot.loopingEffects ?? []).map((effect) => effect.key));
  for (const effect of state.loopingEffects ?? []) {
    if (!nextLoopKeys.has(effect.key)) {
      commands.push({ key: effect.key, kind: "effect-loop-stop", seq: snapshotSeq });
    }
  }
  for (const effect of snapshot.loopingEffects ?? []) {
    commands.push({
      key: effect.key,
      kind: "effect-loop-start",
      seq: effect.seq,
      url: effect.url,
    });
  }
  return commands;
}

function restoreEffectImage(state: ChatStageState, snapshot: ChatSnapshot, receivedAt: number) {
  const image = snapshot.effectImage;
  if (!image || !Number.isFinite(snapshot.serverTimeMs)) return null;
  const remaining = Math.min(image.durationMs, Math.max(0, image.expiresAt - snapshot.serverTimeMs!));
  if (!Number.isFinite(remaining) || remaining <= 0) return null;
  let deadline = receivedAt + remaining;
  const previous = state.effectImage;
  if (state.sessionId === snapshot.sessionId && previous?.seq === image.seq && previous.url === image.url) {
    // Repeated snapshots cannot restart or extend an already displayed image.
    deadline = Math.min(deadline, previous.deadline);
  }
  return { deadline, durationMs: image.durationMs, label: image.label, seq: image.seq, url: image.url };
}

export function hydrateFromSnapshot(state: ChatStageState, snapshot: ChatSnapshot, receivedAt = 0): ChatStageState {
  const nextEventSeq = snapshotEventSeq(snapshot);
  if (nextEventSeq < state.eventSeq) {
    return state;
  }
  const transport = shouldPreserveTransportState(state)
    ? { transportMode: state.transportMode, transportState: state.transportState }
    : transportFromSnapshot(snapshot);
  const audioCommands = recoveryAudioCommands(state, snapshot, nextEventSeq);
  return withResolvedLayers({
    ...emptyChatState,
    ...snapshot,
    effectImage: restoreEffectImage(state, snapshot, receivedAt),
    audioCommands,
    asrTranscript: undefined,
    error: undefined,
    eventSeq: nextEventSeq,
    inputAttachments: state.inputAttachments,
    inputDraft: state.inputDraft || snapshot.inputDraft,
    pluginPagePresentations: (snapshot.pluginPagePresentations ?? []).map((presentation) => ({
      ...presentation,
      payload: { ...presentation.payload },
    })),
    sprites: normalizeChatStageSprites(snapshot.sprites.map((sprite) => ({ ...sprite }))),
    stats: (snapshot.stats ?? []).map((stat) => ({ ...stat })),
    toolConfirmation: snapshot.toolConfirmation ? { ...snapshot.toolConfirmation } : null,
    turnOptions: { ...emptyChatState.turnOptions, ...snapshot.turnOptions },
    turnState: {
      ...emptyChatState.turnState,
      ...snapshot.turnState,
      pendingMessages: [...(snapshot.turnState?.pendingMessages ?? [])],
    },
    ...transport,
  });
}
