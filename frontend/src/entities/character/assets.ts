import type { Character, ModelSprites } from "../config/types";

export type CharacterAssetSource = Partial<Pick<Character, "avatar_type" | "avatars" | "sprites" | "emotion_tags">>;

/** Storage defaults belong to the character entity, not a rendering format. */
export function createEmptyCharacterAssets(): ModelSprites {
  return { model_path: "", sprites: [], emotion_tags: "" };
}

export function characterAvatarType(character: CharacterAssetSource | undefined): string {
  return character?.avatar_type?.trim().toLowerCase() || "static";
}

/** Shared read-only selection; model state contents remain opaque to callers. */
export function getCharacterAssets(
  character: CharacterAssetSource | undefined,
  kind = characterAvatarType(character),
): ModelSprites {
  if (kind === "static") {
    return { model_path: "", sprites: character?.sprites ?? [], emotion_tags: character?.emotion_tags ?? "" };
  }
  return character?.avatars?.[kind] ?? createEmptyCharacterAssets();
}

export function characterAssetBanks(character: CharacterAssetSource | undefined): ModelSprites[] {
  return [getCharacterAssets(character, "static"), ...Object.values(character?.avatars ?? {})];
}
