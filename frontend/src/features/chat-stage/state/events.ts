import type { ChatStageEvent } from "../../../shared/platform/types";
import { dispatchFoldedStageEvent } from "./eventHandlers";
import { withResolvedLayers } from "./layers";
import type { ChatStageState } from "./types";

export function applyStageEvent(state: ChatStageState, event: ChatStageEvent, receivedAt = 0): ChatStageState {
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
  if (event.type === "cmd.ack") {
    return state;
  }
  return dispatchFoldedStageEvent(state, event, {
    eventSeq: Math.max(state.eventSeq, event.seq),
    receivedAt,
  });
}
