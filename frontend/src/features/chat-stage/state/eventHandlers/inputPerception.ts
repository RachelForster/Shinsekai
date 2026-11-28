import { clearTransientNotificationState, withResolvedLayers } from "../layers";
import type { StageEventHandlerMap } from "./types";

type InputPerceptionEventType =
  | "asr.partial"
  | "asr.final"
  | "asr.state"
  | "perception.state"
  | "perception.capture_request";

export const inputPerceptionHandlers: Pick<StageEventHandlerMap, InputPerceptionEventType> = {
  "asr.partial": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      asrEnabled: true,
      asrLoading: false,
      asrRunning: true,
      asrTranscript: event.text,
      eventSeq: ctx.eventSeq,
      inputDraft: event.text,
      status: "listening",
    }),
  "asr.final": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      asrTranscript: event.text,
      eventSeq: ctx.eventSeq,
      inputDraft: "",
      options: [],
    }),
  "asr.state": (state, event, ctx) => {
    const asrEnabled = event.enabled ?? event.running;
    const replyInProgress = ["generating", "streaming", "speaking"].includes(state.status);
    return withResolvedLayers({
      ...clearTransientNotificationState(state),
      asrEnabled,
      asrLoading: Boolean(event.loading) && asrEnabled,
      asrRunning: event.running && asrEnabled,
      eventSeq: ctx.eventSeq,
      status: event.running ? "listening" : replyInProgress ? state.status : "paused",
    });
  },
  "perception.state": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      perception: { ...event.perception },
    }),
  "perception.capture_request": (state, event, ctx) => ({
    ...state,
    eventSeq: ctx.eventSeq,
    perceptionCaptureRequestSeq: event.seq,
  }),
};
