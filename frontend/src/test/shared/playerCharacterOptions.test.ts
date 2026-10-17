import { describe, expect, it } from "vitest";
import { DEFAULT_PLAYER_OPTIONS, normalizePlayerOptions } from "../../shared/playerCharacterOptions";

describe("player character options", () => {
  it("uses the same defaults for missing legacy fields", () => {
    expect(normalizePlayerOptions({})).toEqual(DEFAULT_PLAYER_OPTIONS);
    expect(normalizePlayerOptions({ playerCharacter: "Player" })).toEqual({
      ...DEFAULT_PLAYER_OPTIONS,
      playerCharacter: "Player",
    });
  });

  it("preserves an explicit disabled AI option independently of voice", () => {
    const options = { playerCharacter: "Player", readPlayerSpeech: true, allowPlayerDialogue: false };
    expect(normalizePlayerOptions(options)).toEqual(options);
  });

  it("keeps a saved voice preference even when no player is currently selected", () => {
    expect(normalizePlayerOptions({ readPlayerSpeech: true }).readPlayerSpeech).toBe(true);
  });

  it("does not mutate the source or share the default object", () => {
    const source = Object.freeze({ allowPlayerDialogue: false });
    const normalized = normalizePlayerOptions(source);
    normalized.playerCharacter = "Player";
    expect(source).toEqual({ allowPlayerDialogue: false });
    expect(DEFAULT_PLAYER_OPTIONS.playerCharacter).toBe("");
  });
});
