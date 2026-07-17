import type { ChatStageSprite } from "./types";

/** Matches the legacy Qt SpritePanel default. */
export const CHAT_STAGE_SPRITE_SLOT_COUNT = 3;

export function chatStageSpriteCharacterName(sprite: ChatStageSprite) {
  return (sprite.characterName ?? sprite.label ?? sprite.id).trim();
}

function validSpriteSlot(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value < CHAT_STAGE_SPRITE_SLOT_COUNT;
}

export function resolvedChatStageSpriteSlot(sprite: ChatStageSprite, fallbackIndex = 0) {
  if (validSpriteSlot(sprite.slot)) {
    return sprite.slot;
  }
  return Math.min(Math.max(0, fallbackIndex), CHAT_STAGE_SPRITE_SLOT_COUNT - 1);
}

function firstFreeSpriteSlot(sprites: readonly ChatStageSprite[]) {
  const used = new Set(sprites.map((sprite, index) => resolvedChatStageSpriteSlot(sprite, index)));
  for (let slot = 0; slot < CHAT_STAGE_SPRITE_SLOT_COUNT; slot += 1) {
    if (!used.has(slot)) {
      return slot;
    }
  }
  return undefined;
}

function replaceSpriteInSlot(sprites: readonly ChatStageSprite[], nextSprite: ChatStageSprite, slot: number) {
  const characterName = chatStageSpriteCharacterName(nextSprite);
  return [
    ...sprites.filter(
      (sprite, index) =>
        chatStageSpriteCharacterName(sprite) !== characterName && resolvedChatStageSpriteSlot(sprite, index) !== slot,
    ),
    { ...nextSprite, slot },
  ];
}

/**
 * Keeps the display slot stable when the same character changes expression.
 * Array order is LRU order: the most recently shown character is appended.
 */
export function upsertChatStageSprite(sprites: readonly ChatStageSprite[], nextSprite: ChatStageSprite) {
  const characterName = chatStageSpriteCharacterName(nextSprite);
  const existingIndex = sprites.findIndex((sprite) => chatStageSpriteCharacterName(sprite) === characterName);
  const existing = existingIndex >= 0 ? sprites[existingIndex] : undefined;
  const existingSlot = existing ? resolvedChatStageSpriteSlot(existing, existingIndex) : undefined;
  const freeSlot = existingSlot == null ? firstFreeSpriteSlot(sprites) : undefined;
  const requestedSlot = validSpriteSlot(nextSprite.slot) ? nextSprite.slot : undefined;
  const oldestSlot = sprites.length ? resolvedChatStageSpriteSlot(sprites[0], 0) : 0;
  const slot = existingSlot ?? freeSlot ?? requestedSlot ?? oldestSlot;
  return replaceSpriteInSlot(sprites, nextSprite, slot);
}

/** Preserve server-assigned slots on reconnect while repairing old snapshots without slots. */
export function normalizeChatStageSprites(sprites: readonly ChatStageSprite[]) {
  return sprites.reduce<ChatStageSprite[]>((normalized, sprite) => {
    const characterName = chatStageSpriteCharacterName(sprite);
    const existingIndex = normalized.findIndex((item) => chatStageSpriteCharacterName(item) === characterName);
    const existing = existingIndex >= 0 ? normalized[existingIndex] : undefined;
    const existingSlot = existing ? resolvedChatStageSpriteSlot(existing, existingIndex) : undefined;
    const requestedSlot = validSpriteSlot(sprite.slot) ? sprite.slot : undefined;
    const requestedOccupied =
      requestedSlot != null &&
      normalized.some((item, index) => resolvedChatStageSpriteSlot(item, index) === requestedSlot);
    const slot =
      existingSlot ??
      (requestedSlot != null && !requestedOccupied ? requestedSlot : undefined) ??
      firstFreeSpriteSlot(normalized) ??
      requestedSlot ??
      (normalized[0] ? resolvedChatStageSpriteSlot(normalized[0], 0) : 0);
    return replaceSpriteInSlot(normalized, sprite, slot);
  }, []);
}

/** Reproduces the legacy Qt axis centers and whole-group centering compensation. */
export function chatStageSpriteAxisCenter(
  sprites: readonly ChatStageSprite[],
  sprite: ChatStageSprite,
  fallbackIndex: number,
) {
  if (!sprites.length) {
    return 50;
  }
  const slots = sprites.map((item, index) => resolvedChatStageSpriteSlot(item, index));
  const minSlot = Math.min(...slots);
  const maxSlot = Math.max(...slots);
  const slot = resolvedChatStageSpriteSlot(sprite, fallbackIndex);
  const compensation = 0.5 - (minSlot + maxSlot + 2) / (2 * CHAT_STAGE_SPRITE_SLOT_COUNT);
  return ((slot + 1) / CHAT_STAGE_SPRITE_SLOT_COUNT + compensation) * 100;
}
