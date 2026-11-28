import { withResolvedLayers } from "../layers";
import type { ChatStageState } from "../types";
import type { EventHandlerContext, StageEventHandlerMap, StageEventOf } from "./types";

type StoryProgressEventType =
  | "story.node.entered"
  | "story.node.unlocked"
  | "story.cast.replace"
  | "story.ending.reached";

type CapabilityPluginEventType =
  | "story.state.replace"
  | StoryProgressEventType
  | "behavior.state.replace"
  | "outfit.state"
  | "memory.mode"
  | "plugin.page.present"
  | "plugin.page.dismiss"
  | "plugin.behavior.event";

function foldStoryProgress(
  state: ChatStageState,
  event: StageEventOf<StoryProgressEventType>,
  ctx: EventHandlerContext,
): ChatStageState {
  return withResolvedLayers({
    ...state,
    eventSeq: ctx.eventSeq,
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
}

export const capabilityPluginHandlers: Pick<StageEventHandlerMap, CapabilityPluginEventType> = {
  "story.state.replace": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      story: event.story,
    }),
  "story.node.entered": foldStoryProgress,
  "story.node.unlocked": foldStoryProgress,
  "story.cast.replace": foldStoryProgress,
  "story.ending.reached": foldStoryProgress,
  "behavior.state.replace": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      behavior: event.behavior ?? null,
    }),
  "outfit.state": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      autoOutfitSwitch: event.autoOutfitSwitch,
      outfits: Object.fromEntries(Object.entries(event.outfits).map(([key, value]) => [key, { ...value }])),
      outfitCatalog: Object.fromEntries(
        Object.entries(event.outfitCatalog).map(([key, value]) => [key, { ...value, groups: [...value.groups] }]),
      ),
    }),
  "memory.mode": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      memoryMode: event.memoryMode,
    }),
  "plugin.page.present": (state, event, ctx) => {
    const presentation = {
      mode: "overlay" as const,
      pageId: event.pageId,
      payload: { ...event.payload },
      pluginId: event.pluginId,
      presentationId: event.presentationId,
    };
    return withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      pluginPagePresentations: [
        ...(state.pluginPagePresentations ?? []).filter(
          (item) => item.pluginId !== presentation.pluginId || item.presentationId !== presentation.presentationId,
        ),
        presentation,
      ].slice(-8),
    });
  },
  "plugin.page.dismiss": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      pluginPagePresentations: (state.pluginPagePresentations ?? []).filter(
        (item) => item.pluginId !== event.pluginId || item.presentationId !== event.presentationId,
      ),
    }),
  "plugin.behavior.event": (state, event, ctx) => {
    const nextEvent = {
      eventType: event.eventType,
      payload: { ...(event.payload ?? {}) },
      pluginId: event.pluginId,
      seq: event.seq,
    };
    const filtered = (state.pluginBehaviorEvents ?? []).filter((item) => event.seq <= 0 || item.seq !== event.seq);
    return {
      ...state,
      eventSeq: ctx.eventSeq,
      pluginBehaviorEvents: [...filtered, nextEvent].slice(-32),
    };
  },
};
