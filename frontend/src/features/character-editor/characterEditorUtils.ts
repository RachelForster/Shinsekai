import type { Character } from "../../entities/config/types";
import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";

export const CHARACTER_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

export const SELF_PERSONA_NAME = "自设";
export const SELF_PERSONA_SPRITE_PREFIX = "__self__";
export const DEFAULT_SPRITE_GROUP = "默认";

export const SPRITE_SCALE_MIN = 0;
export const SPRITE_SCALE_MAX = 3;
export const SPRITE_SCALE_STEP = 0.05;

export type CharacterFieldChange = <K extends keyof Character>(name: K, value: Character[K]) => void;

export type CharacterResourceDeleteTarget =
  | { characterName: string; index: number; kind: "sprite"; filename: string }
  | { characterName: string; count: number; kind: "all-sprites" }
  | { characterName: string; index: number; kind: "sprite-voice"; filename: string }
  | { characterName: string; kind: "memory"; memory: string; memoryId: string };

export function createCharacter(): Character {
  return {
    avatar_type: "static",
    avatars: {},
    character_brief: "",
    relation_graph: { nodes: [], edges: [] },
    character_setting: "",
    color: DEFAULT_CHARACTER_COLOR,
    emotion_tags: "",
    name: "",
    pronunciation_map: {},
    speech_speed: 1,
    speech_volume: 1,
    sprite_prefix: "temp",
    sprite_scale: 1,
    sprites: [],
  };
}

export function pronunciationMapToText(value: Record<string, string>) {
  return Object.entries(value ?? {})
    .map(([key, item]) => `${key}=${item}`)
    .join("\n");
}

export function pronunciationTextToMap(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const index = line.indexOf("=");
      if (index <= 0) {
        return acc;
      }
      const key = line.slice(0, index).trim();
      const item = line.slice(index + 1).trim();
      if (key) {
        acc[key] = item;
      }
      return acc;
    }, {});
}

export function clampSpriteScale(value: number) {
  return Math.min(SPRITE_SCALE_MAX, Math.max(SPRITE_SCALE_MIN, Number(value.toFixed(2))));
}

export function isSelfPersonaCharacter(
  character?: Pick<Character, "name" | "is_builtin" | "undeletable"> | null,
): boolean {
  return Boolean(
    character && (character.is_builtin || character.undeletable || character.name.trim() === SELF_PERSONA_NAME),
  );
}

export function normalizeSpriteGroupName(group?: string | null): string {
  const trimmed = String(group ?? "").trim();
  return trimmed || DEFAULT_SPRITE_GROUP;
}

export function resolveCharacterSpriteGroups(
  character: Pick<Character, "sprite_groups" | "sprites" | "default_sprite_group">,
): string[] {
  const seen = new Set<string>([DEFAULT_SPRITE_GROUP]);
  const ordered: string[] = [DEFAULT_SPRITE_GROUP];
  const push = (raw?: string | null) => {
    const normalized = normalizeSpriteGroupName(raw);
    if (!seen.has(normalized)) {
      seen.add(normalized);
      ordered.push(normalized);
    }
  };
  for (const group of character.sprite_groups ?? []) {
    push(group);
  }
  if (character.default_sprite_group) {
    push(character.default_sprite_group);
  }
  for (const sprite of character.sprites ?? []) {
    if (sprite.group) {
      push(sprite.group);
    }
  }
  return ordered;
}

export function upsertCatalogCharacter(
  current: Character[],
  character: Character,
  originalName?: string,
): Character[] {
  const targetNames = new Set([originalName, character.name].filter(Boolean));
  const next: Character[] = [];
  let replaced = false;
  for (const item of current) {
    if (targetNames.has(item.name)) {
      if (!replaced) {
        next.push(character);
        replaced = true;
      }
      continue;
    }
    next.push(item);
  }
  if (!replaced) {
    next.push(character);
  }
  const pinnedItems = next.filter((item) => item.pinned || isSelfPersonaCharacter(item));
  const regularItems = next.filter((item) => !(item.pinned || isSelfPersonaCharacter(item)));
  return [...pinnedItems, ...regularItems];
}
