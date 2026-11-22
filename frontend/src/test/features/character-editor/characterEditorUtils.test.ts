import { describe, expect, it } from "vitest";

import {
  buildCommittedCharacterPayload,
  buildNewCharacterPayload,
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

  it("omits relation_graph on committed character updates and omits id on new character creation", () => {
    const committed = {
      ...createCharacter(),
      id: "char-mika",
      name: "Mika",
      relation_graph: {
        edges: [{ content: "best friend", source: "Mika", target: "Aki", temperature: 8 }],
        nodes: [{ key: "Mika" }, { key: "Aki" }],
      },
      sprite_prefix: "mika",
      sprites: [{ path: "D:/sprites/mika/a.png" }],
    };
    const draft = {
      ...createCharacter(),
      character_setting: "  Updated bio  ",
      id: "leaked-id",
      name: "UnconfirmedRename",
      relation_graph: { edges: [], nodes: [] },
      sprite_prefix: "unconfirmed_prefix",
    };

    const autoSavePayload = buildCommittedCharacterPayload(draft, { Mika: "mika" }, committed);
    expect(autoSavePayload).not.toHaveProperty("relation_graph");
    expect(autoSavePayload.id).toBe("char-mika");
    expect(autoSavePayload.name).toBe("Mika");
    expect(autoSavePayload.sprite_prefix).toBe("mika");
    expect(autoSavePayload.character_setting).toBe("Updated bio");
    expect(autoSavePayload.sprites).toEqual([{ path: "D:/sprites/mika/a.png" }]);

    const createPayload = buildNewCharacterPayload(draft, {}, { name: "NewHero", sprite_prefix: "new_hero" });
    expect(createPayload).not.toHaveProperty("id");
    expect(createPayload.name).toBe("NewHero");
    expect(createPayload.sprite_prefix).toBe("new_hero");
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
