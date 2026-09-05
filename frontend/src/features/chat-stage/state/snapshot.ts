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

function asrUtteranceId(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function hydratedInputDraft(
  state: ChatStageState,
  snapshot: ChatSnapshot,
): Pick<ChatStageState, "asrSourceUtteranceId" | "asrUtteranceId" | "inputDraft"> {
  const localUtteranceId = asrUtteranceId(state.asrUtteranceId);
  const snapshotUtteranceId = asrUtteranceId(snapshot.asrUtteranceId);

  // A non-ASR-owned local value is a genuine user edit. Keep it across a
  // reconnect even when the runtime snapshot has no draft (or has a newer
  // ASR draft). An ASR-owned value, however, must yield to the authoritative
  // snapshot so a final consumed while disconnected cannot reappear.
  if (!localUtteranceId && state.inputDraft) {
    return {
      asrSourceUtteranceId: state.asrSourceUtteranceId,
      asrUtteranceId: null,
      inputDraft: state.inputDraft,
    };
  }
  const snapshotHasDraft = Boolean(snapshot.inputDraft);
  return {
    asrSourceUtteranceId: snapshotHasDraft ? snapshotUtteranceId : null,
    asrUtteranceId: snapshotHasDraft ? snapshotUtteranceId : null,
    inputDraft: snapshot.inputDraft,
  };
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

export function hydrateFromSnapshot(state: ChatStageState, snapshot: ChatSnapshot): ChatStageState {
  const nextEventSeq = snapshotEventSeq(snapshot);
  if (nextEventSeq < state.eventSeq) {
    return state;
  }
  const transport = shouldPreserveTransportState(state)
    ? { transportMode: state.transportMode, transportState: state.transportState }
    : transportFromSnapshot(snapshot);
  const audioCommands = recoveryAudioCommands(state, snapshot, nextEventSeq);
  const draft = hydratedInputDraft(state, snapshot);
  return withResolvedLayers({
    ...emptyChatState,
    ...snapshot,
    audioCommands,
    asrTranscript: undefined,
    error: undefined,
    eventSeq: nextEventSeq,
    inputAttachments: state.inputAttachments,
    ...draft,
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
