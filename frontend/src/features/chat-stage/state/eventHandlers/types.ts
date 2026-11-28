import type { ChatStageEvent } from "../../../../shared/platform/types";
import type { ChatAudioCommand, ChatStageState } from "../types";

export type StageEventOf<T extends ChatStageEvent["type"]> = Extract<ChatStageEvent, { type: T }>;

export type NonFoldedEventType = "transport.state" | "cmd.ack";
export type FoldedStageEventType = Exclude<ChatStageEvent["type"], NonFoldedEventType>;

export interface EventHandlerContext {
  eventSeq: number;
  receivedAt: number;
}

export type StageEventHandler<T extends FoldedStageEventType> = (
  state: ChatStageState,
  event: StageEventOf<T>,
  ctx: EventHandlerContext,
) => ChatStageState;

export type StageEventHandlerMap = {
  [K in FoldedStageEventType]: StageEventHandler<K>;
};

export function appendAudioCommand(state: ChatStageState, command: ChatAudioCommand): ChatAudioCommand[] {
  return [...state.audioCommands, command].slice(-32);
}
