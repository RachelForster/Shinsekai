import { describe, expect, it } from "vitest";

import {
  clampSpriteScale,
  createCharacter,
  pronunciationMapToText,
  pronunciationTextToMap,
  SPRITE_SCALE_MAX,
  SPRITE_SCALE_MIN,
} from "../../../features/character-editor/characterEditorUtils";
import { DEFAULT_CHARACTER_COLOR } from "../../../shared/constants";

describe("character editor utilities", () => {
  it("creates a safe empty character draft", () => {
    expect(createCharacter()).toEqual({
      character_setting: "",
      color: DEFAULT_CHARACTER_COLOR,
      emotion_tags: "",
      scenarios: [],
      name: "",
      pronunciation_map: {},
      speech_speed: 1,
      speech_volume: 1,
      sprite_prefix: "temp",
      sprite_scale: 1,
      sprites: [],
    });
  });

  it("parses pronunciation map text and ignores invalid rows", () => {
    expect(
      pronunciationTextToMap(`
        Hanadan = hanadan
        no-separator
        = missing-key
        mood= calm = soft
      `),
    ).toEqual({
      Hanadan: "hanadan",
      mood: "calm = soft",
    });
  });

  it("serializes pronunciation maps one entry per line", () => {
    expect(pronunciationMapToText({ Shinsekai: "shinsekai", Senpai: "senpai" })).toBe(
      "Shinsekai=shinsekai\nSenpai=senpai",
    );
  });

  it("rounds and clamps sprite scale values", () => {
    expect(clampSpriteScale(-0.2)).toBe(SPRITE_SCALE_MIN);
    expect(clampSpriteScale(1.234)).toBe(1.23);
    expect(clampSpriteScale(4.2)).toBe(SPRITE_SCALE_MAX);
  });
});
