import { describe, expect, it } from "vitest";

import {
  clampSpriteScale,
  createCharacter,
  pronunciationMapToText,
  pronunciationTextToMap,
  SPRITE_SCALE_MAX,
  SPRITE_SCALE_MIN,
  upsertCatalogCharacter,
} from "../../../features/character-editor/characterEditorUtils";
import { DEFAULT_CHARACTER_COLOR } from "../../../shared/constants";

describe("character editor utilities", () => {
  it("creates a safe empty character draft with non-colliding sprite prefix", () => {
    expect(createCharacter()).toEqual({
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
      sprite_prefix: "char_1",
      sprite_scale: 1,
      sprites: [],
    });
    expect(createCharacter(["char_1", "char_2"]).sprite_prefix).toBe("char_3");
  });

  it("updates renamed characters in place when matched by id", () => {
    const first = { ...createCharacter(), id: "char-a", name: "Alpha", sprite_prefix: "alpha" };
    const second = { ...createCharacter(), id: "char-b", name: "Beta", sprite_prefix: "beta" };
    const third = { ...createCharacter(), id: "char-c", name: "Gamma", sprite_prefix: "gamma" };
    const renamed = { ...second, name: "Beta Prime" };

    expect(upsertCatalogCharacter([first, second, third], renamed).map((item) => item.name)).toEqual([
      "Alpha",
      "Beta Prime",
      "Gamma",
    ]);
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
