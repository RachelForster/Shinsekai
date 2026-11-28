import { clearTransientNotificationState, withResolvedLayers } from "../layers";
import { normalizeChatStageSprites, upsertChatStageSprite } from "../sprites";
import type { ChatStageSprite } from "../types";
import type { StageEventHandlerMap } from "./types";

type VisualEventType =
  | "background.change"
  | "bgm.change"
  | "cg.show"
  | "cg.hide"
  | "sprite.show"
  | "sprite.remove"
  | "sprite.motion"
  | "sprite.reaction"
  | "player.portrait.show"
  | "presentation.restore";

export const visualHandlers: Pick<StageEventHandlerMap, VisualEventType> = {
  "background.change": (state, event, ctx) => {
    const sceneChanged = event.url !== (state.backgroundPath ?? "");
    const transitionEffect = event.transition?.trim() ?? "";
    return withResolvedLayers({
      ...clearTransientNotificationState(state),
      backgroundPath: event.url,
      backgroundTransition: transitionEffect ? { effect: transitionEffect, seq: event.seq } : null,
      spriteMotions: sceneChanged ? {} : state.spriteMotions,
      sprites: sceneChanged ? [] : state.sprites,
      eventSeq: ctx.eventSeq,
    });
  },
  "bgm.change": (state, event, ctx) =>
    withResolvedLayers({
      ...state,
      bgmPath: event.url,
      eventSeq: ctx.eventSeq,
    }),
  "cg.show": (state, event, ctx) =>
    withResolvedLayers({
      ...clearTransientNotificationState(state),
      cgPath: event.url,
      eventSeq: ctx.eventSeq,
    }),
  "cg.hide": (state, _event, ctx) =>
    withResolvedLayers({
      ...state,
      cgPath: undefined,
      eventSeq: ctx.eventSeq,
    }),
  "sprite.show": (state, event, ctx) => {
    const id = event.characterName;
    const nextSprite: ChatStageSprite = {
      identityKey: event.identityKey,
      characterName: event.characterName,
      id,
      label: event.characterName,
      path: event.url,
      scale: event.scale,
      slot: event.slot,
      x: event.x,
      y: event.y,
      avatarType: event.avatarType ?? "static",
      modelUrl: event.modelUrl ?? "",
      transitions: event.transitions,
      mouthSync: event.mouthSync,
      portraitCrop: event.portraitCrop,
      stateSequence: event.seq,
    };
    const sprites = upsertChatStageSprite(state.sprites, nextSprite);
    return withResolvedLayers({
      ...clearTransientNotificationState(state),
      eventSeq: ctx.eventSeq,
      sprites,
    });
  },
  "sprite.remove": (state, event, ctx) => {
    const remaining = state.sprites.filter(
      (sprite) => sprite.id !== event.characterName && sprite.label !== event.characterName,
    );
    const removedKeys = new Set<string>([event.characterName]);
    for (const sprite of state.sprites) {
      if (sprite.id === event.characterName || sprite.label === event.characterName) {
        if (sprite.id) removedKeys.add(sprite.id);
        if (sprite.label) removedKeys.add(sprite.label);
      }
    }
    const nextSpriteMotions = { ...state.spriteMotions };
    for (const key of removedKeys) {
      delete nextSpriteMotions[key];
    }
    return withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      spriteMotions: nextSpriteMotions,
      sprites: remaining,
    });
  },
  "sprite.motion": (state, event, ctx) => {
    const motion = event.motion.trim();
    const characterName = event.characterName.trim();
    if (!motion || !characterName) {
      return {
        ...state,
        eventSeq: ctx.eventSeq,
      };
    }
    return {
      ...state,
      eventSeq: ctx.eventSeq,
      spriteMotions: {
        ...state.spriteMotions,
        [characterName]: {
          durationMs: event.durationMs && event.durationMs > 0 ? event.durationMs : 600,
          motion,
          seq: event.seq,
        },
      },
    };
  },
  "sprite.reaction": (state, event, ctx) => {
    const text = event.text.trim();
    const durationMs = Math.max(800, event.durationMs || 3600);
    return withResolvedLayers({
      ...state,
      eventSeq: ctx.eventSeq,
      spriteReaction: text
        ? {
            characterName: event.characterName,
            deadline: ctx.receivedAt + durationMs,
            durationMs,
            seq: event.seq,
            text,
          }
        : null,
    });
  },
  "player.portrait.show": (state, event) => ({
    ...state,
    eventSeq: event.seq,
    playerPortrait: { characterName: event.characterName, url: event.url, crop: event.crop },
  }),
  "presentation.restore": (state, event) =>
    withResolvedLayers({
      ...state,
      ...event.presentation,
      eventSeq: event.seq,
      replaySelectedIndex: null,
      sprites: event.presentation.sprites
        ? normalizeChatStageSprites(event.presentation.sprites.map((sprite) => ({ ...sprite, applyMode: "restore" })))
        : state.sprites,
    }),
};
