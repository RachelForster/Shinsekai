import type { ChatSnapshot } from "../../../shared/platform/types";
import { emptyChatState } from "./initialState";
import { withResolvedLayers } from "./layers";
import { normalizeChatStageSprites } from "./sprites";
import type { ChatStageState } from "./types";

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

export function hydrateFromSnapshot(state: ChatStageState, snapshot: ChatSnapshot): ChatStageState {
  const nextEventSeq = snapshotEventSeq(snapshot);
  if (nextEventSeq < state.eventSeq) {
    return state;
  }
  const transport = shouldPreserveTransportState(state)
    ? { transportMode: state.transportMode, transportState: state.transportState }
    : transportFromSnapshot(snapshot);
  return withResolvedLayers({
    ...emptyChatState,
    ...snapshot,
    asrTranscript: undefined,
    error: undefined,
    eventSeq: nextEventSeq,
    inputAttachments: state.inputAttachments,
    sprites: normalizeChatStageSprites(snapshot.sprites.map((sprite) => ({ ...sprite }))),
    stats: (snapshot.stats ?? []).map((stat) => ({ ...stat })),
    turnOptions: { ...emptyChatState.turnOptions, ...snapshot.turnOptions },
    turnState: {
      ...emptyChatState.turnState,
      ...snapshot.turnState,
      pendingMessages: [...(snapshot.turnState?.pendingMessages ?? [])],
    },
    ...transport,
  });
}
