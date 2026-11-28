import { audioEffectHandlers } from "./audioEffects";
import { capabilityPluginHandlers } from "./capabilitiesPlugins";
import { dialogInteractionHandlers } from "./dialogInteraction";
import { inputPerceptionHandlers } from "./inputPerception";
import { sessionLifecycleHandlers } from "./sessionLifecycle";
import type { EventHandlerContext, FoldedStageEventType, StageEventHandlerMap, StageEventOf } from "./types";
import { visualHandlers } from "./visuals";

export const stageEventHandlers = {
  ...visualHandlers,
  ...audioEffectHandlers,
  ...dialogInteractionHandlers,
  ...sessionLifecycleHandlers,
  ...inputPerceptionHandlers,
  ...capabilityPluginHandlers,
} satisfies StageEventHandlerMap;

export type FoldedStageEvent = StageEventOf<FoldedStageEventType>;

export function dispatchFoldedStageEvent(state: ChatStageStateArg, event: FoldedStageEvent, ctx: EventHandlerContext) {
  const handler = stageEventHandlers[event.type] as (
    current: ChatStageStateArg,
    payload: FoldedStageEvent,
    context: EventHandlerContext,
  ) => ChatStageStateArg;
  return handler(state, event, ctx);
}

type ChatStageStateArg = Parameters<StageEventHandlerMap["cg.hide"]>[0];
