import type { Character } from "../../entities/config/types";
import { suggestUniqueSpritePrefix } from "../../shared/assets/spritePrefix";
import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";
import { SELF_PERSONA_NAME } from "../../shared/playerCharacterOptions";

export const CHARACTER_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

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

export function createCharacter(existingPrefixes: Iterable<string> = []): Character {
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
    sprite_prefix: suggestUniqueSpritePrefix("", existingPrefixes, "char"),
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

export function upsertCatalogCharacter(current: Character[], character: Character, originalName?: string): Character[] {
  const targetNames = new Set([originalName, character.name].filter(Boolean));
  const next: Character[] = [];
  let replaced = false;
  for (const item of current) {
    const matchedById = Boolean(character.id && item.id && item.id === character.id);
    if (matchedById || targetNames.has(item.name)) {
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

export function buildCommittedCharacterPayload(
  draft: Character,
  pronunciationMap: Record<string, string>,
  identity: Pick<Character, "id" | "name" | "sprite_prefix">,
): Character {
  return {
    ...draft,
    ...(identity.id ? { id: identity.id } : {}),
    ...(draft.display_name !== undefined ? { display_name: draft.display_name.trim() } : {}),
    character_setting: draft.character_setting.trim(),
    color: draft.color.trim() || DEFAULT_CHARACTER_COLOR,
    gpt_model_path: draft.gpt_model_path?.trim() || "",
    name: identity.name.trim(),
    prompt_lang: draft.prompt_lang?.trim() || "",
    prompt_text: draft.prompt_text?.trim() || "",
    pronunciation_map: pronunciationMap,
    refer_audio_path: draft.refer_audio_path?.trim() || "",
    sovits_model_path: draft.sovits_model_path?.trim() || "",
    sprite_prefix: identity.sprite_prefix.trim(),
  };
}

export function serializeCharacterNonIdentity(character: Character, pronunciationMap?: Record<string, string>): string {
  const mapSource = pronunciationMap ?? character.pronunciation_map ?? {};
  const sortedMap = Object.keys(mapSource)
    .sort()
    .map((key) => [key, mapSource[key]] as const);
  return JSON.stringify({
    avatar_type: character.avatar_type ?? "static",
    character_brief: character.character_brief ?? "",
    character_setting: (character.character_setting ?? "").trim(),
    color: (character.color ?? "").trim() || DEFAULT_CHARACTER_COLOR,
    display_name: (character.display_name ?? "").trim(),
    emotion_tags: character.emotion_tags ?? "",
    gpt_model_path: character.gpt_model_path?.trim() || "",
    prompt_lang: character.prompt_lang?.trim() || "",
    prompt_text: character.prompt_text?.trim() || "",
    pronunciation_map: sortedMap,
    refer_audio_path: character.refer_audio_path?.trim() || "",
    sovits_model_path: character.sovits_model_path?.trim() || "",
    speech_speed: character.speech_speed ?? 1,
    speech_volume: character.speech_volume ?? 1,
    sprite_scale: character.sprite_scale ?? 1,
  });
}
