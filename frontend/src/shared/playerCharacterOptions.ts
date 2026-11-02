import type { PlayerCharacterOptions } from "./platform/types";

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
