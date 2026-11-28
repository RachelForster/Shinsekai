import type { Character, PlayerCharacterOptions } from "./platform/types";

export const SELF_PERSONA_ID = "__self__";
export const SELF_PERSONA_NAME = "自设";
export const SELF_PERSONA_SPRITE_PREFIX = "__self__";

export type SelfPersonaShape = Partial<Pick<Character, "id" | "is_builtin" | "undeletable">> & Pick<Character, "name">;

export function isSelfPersonaId(id: string | undefined | null): boolean {
  return String(id ?? "").trim() === SELF_PERSONA_ID;
}

export function isSelfPersonaName(name: string | undefined | null): boolean {
  return String(name ?? "").trim() === SELF_PERSONA_NAME;
}

export function isSelfPersonaCharacter(character?: SelfPersonaShape | null): boolean {
  if (!character) {
    return false;
  }
  const cleanId = String(character.id ?? "").trim();
  if (isSelfPersonaId(cleanId)) {
    return true;
  }
  if (character.is_builtin || character.undeletable) {
    return true;
  }
  return !cleanId && isSelfPersonaName(character.name);
}

export function findSelfPersona<T extends SelfPersonaShape>(characters: readonly T[]): T | undefined {
  return (
    characters.find((character) => isSelfPersonaId(character.id)) ??
    characters.find((character) => isSelfPersonaCharacter(character))
  );
}

export function getCharacterDisplayName(
  character: Pick<Character, "name" | "display_name"> & Partial<Pick<Character, "id" | "is_builtin" | "undeletable">>,
): string {
  if (isSelfPersonaCharacter(character) && isSelfPersonaName(character.name) && character.display_name?.trim()) {
    return character.display_name.trim();
  }
  return character.name;
}

export const DEFAULT_PLAYER_OPTIONS: Readonly<Required<PlayerCharacterOptions>> = Object.freeze({
  playerCharacter: "",
  readPlayerSpeech: false,
  allowPlayerDialogue: true,
});

export function normalizePlayerOptions(options: PlayerCharacterOptions): Required<PlayerCharacterOptions> {
  return {
    playerCharacter: options.playerCharacter ?? DEFAULT_PLAYER_OPTIONS.playerCharacter,
    readPlayerSpeech: options.readPlayerSpeech ?? DEFAULT_PLAYER_OPTIONS.readPlayerSpeech,
    allowPlayerDialogue: options.allowPlayerDialogue ?? DEFAULT_PLAYER_OPTIONS.allowPlayerDialogue,
  };
}
