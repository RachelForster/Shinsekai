import type { Character } from "../../entities/config/types";
import { suggestUniqueSpritePrefix } from "../../shared/assets/spritePrefix";
import { DEFAULT_CHARACTER_COLOR, DEFAULT_SPRITE_GROUP } from "../../shared/constants";
import {
  SELF_PERSONA_ID,
  SELF_PERSONA_SPRITE_PREFIX,
  isSelfPersonaCharacter,
} from "../../shared/playerCharacterOptions";

export const CHARACTER_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

export { DEFAULT_SPRITE_GROUP, SELF_PERSONA_ID, SELF_PERSONA_SPRITE_PREFIX, isSelfPersonaCharacter };

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

export function removeCharacterVoice(draft: Character, profileId: string): Character {
  const voiceProfiles = { ...draft.voice_profiles };
  const [firstId] = Object.keys(voiceProfiles);
  if (!firstId) return draft;

  const removedId = profileId || firstId;
  const removed = voiceProfiles[removedId];
  if (!removed) return draft;
  delete voiceProfiles[removedId];

  return {
    ...draft,
    ...(!profileId && {
      default_voice_name: removed.name,
      gpt_model_path: removed.gpt_model_path ?? "",
      sovits_model_path: removed.sovits_model_path ?? "",
      refer_audio_path: removed.refer_audio_path ?? "",
      prompt_text: removed.prompt_text ?? "",
      prompt_lang: removed.prompt_lang ?? "",
      speech_speed: removed.speech_speed,
      speech_volume: removed.speech_volume,
    }),
    voice_profiles: voiceProfiles,
    sprites: draft.sprites.map((sprite) =>
      sprite.voice_profile_id === removedId ? { ...sprite, voice_profile_id: null } : sprite,
    ),
  };
}

export function buildNewCharacterPayload(
  draft: Character,
  pronunciationMap: Record<string, string>,
  identity: Pick<Character, "name" | "sprite_prefix">,
): Character {
  const { id: _omittedId, ...rest } = draft;
  return {
    ...rest,
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

export function buildCommittedCharacterPayload(
  draft: Character,
  pronunciationMap: Record<string, string>,
  baseCharacter: Character,
  identityOverride?: Partial<Pick<Character, "name" | "sprite_prefix">>,
): Character {
  const { relation_graph: _omittedRelationGraph, ...persistedBase } = baseCharacter;
  return {
    ...persistedBase,
    default_voice_name: draft.default_voice_name?.trim(),
    voice_profiles: draft.voice_profiles,
    sprites: baseCharacter.sprites.map((sprite) => {
      const edited = draft.sprites.find((item) => item.path === sprite.path);
      return edited ? { ...sprite, voice_profile_id: edited.voice_profile_id } : sprite;
    }),
    ...(baseCharacter.id ? { id: baseCharacter.id } : {}),
    ...(draft.display_name !== undefined ? { display_name: draft.display_name.trim() } : {}),
    avatar_type: draft.avatar_type ?? baseCharacter.avatar_type ?? "static",
    avatars: {
      ...draft.avatars,
      ...baseCharacter.avatars,
    },
    character_brief: draft.character_brief ?? "",
    character_setting: draft.character_setting.trim(),
    color: draft.color.trim() || DEFAULT_CHARACTER_COLOR,
    emotion_tags: draft.emotion_tags ?? "",
    gpt_model_path: draft.gpt_model_path?.trim() || "",
    name: (identityOverride?.name ?? baseCharacter.name).trim(),
    prompt_lang: draft.prompt_lang?.trim() || "",
    prompt_text: draft.prompt_text?.trim() || "",
    pronunciation_map: pronunciationMap,
    refer_audio_path: draft.refer_audio_path?.trim() || "",
    sovits_model_path: draft.sovits_model_path?.trim() || "",
    speech_speed: draft.speech_speed ?? baseCharacter.speech_speed ?? 1,
    speech_volume: draft.speech_volume ?? baseCharacter.speech_volume ?? 1,
    sprite_prefix: (identityOverride?.sprite_prefix ?? baseCharacter.sprite_prefix).trim(),
    sprite_scale: draft.sprite_scale ?? baseCharacter.sprite_scale ?? 1,
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
    default_voice_name: character.default_voice_name?.trim() ?? "",
    voice_profiles: character.voice_profiles ?? {},
    sprite_voice_profiles: character.sprites
      .filter((sprite) => sprite.voice_profile_id)
      .map((sprite) => [sprite.path, sprite.voice_profile_id]),
    refer_audio_path: character.refer_audio_path?.trim() || "",
    sovits_model_path: character.sovits_model_path?.trim() || "",
    speech_speed: character.speech_speed ?? 1,
    speech_volume: character.speech_volume ?? 1,
    sprite_scale: character.sprite_scale ?? 1,
  });
}
