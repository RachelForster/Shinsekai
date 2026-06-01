import { describe, expect, it } from "vitest";

import {
  CHARACTER_RESOURCES_URL,
  clampSpriteScale,
  createCharacter,
  pronunciationMapToText,
  pronunciationTextToMap,
  SPRITE_SCALE_MAX,
  SPRITE_SCALE_MIN,
} from "../features/character-editor/characterEditorUtils";
import { DEFAULT_CHARACTER_COLOR } from "../shared/constants";

describe("character editor utilities", () => {
  it("creates a complete editable character draft", () => {
    expect(createCharacter()).toEqual({
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
    });
    expect(CHARACTER_RESOURCES_URL).toBe("https://shinsekai.end0rph1n.icu/resources");
  });

  it("converts pronunciation maps to and from editable text", () => {
    expect(pronunciationMapToText({ 行: "hang2", 重: "chong2" })).toBe("行=hang2\n重=chong2");
    expect(
      pronunciationTextToMap([" 行 = hang2 ", "invalid", "=missing-key", "重= chong2", "empty="].join("\n")),
    ).toEqual({
      empty: "",
      行: "hang2",
      重: "chong2",
    });
  });

  it("clamps sprite scale to the supported range with two decimals", () => {
    expect(clampSpriteScale(-1)).toBe(SPRITE_SCALE_MIN);
    expect(clampSpriteScale(9)).toBe(SPRITE_SCALE_MAX);
    expect(clampSpriteScale(1.234)).toBe(1.23);
    expect(clampSpriteScale(1.235)).toBe(1.24);
  });
});
