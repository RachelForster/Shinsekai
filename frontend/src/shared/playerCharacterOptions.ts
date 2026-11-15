import type { Character, PlayerCharacterOptions } from "./platform/types";

export const SELF_PERSONA_NAME = "自设";

export function getCharacterDisplayName(character: Pick<Character, "name" | "display_name">): string {
  return (character.name === SELF_PERSONA_NAME && character.display_name?.trim()) || character.name;
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
