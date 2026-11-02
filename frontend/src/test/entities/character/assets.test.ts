import { describe, expect, it } from "vitest";
import { createEmptyCharacterAssets, getCharacterAssets } from "../../../entities/character/assets";

describe("character asset storage without a renderer", () => {
  it("creates independent banks without loading or registering any format", () => {
    const first = createEmptyCharacterAssets();
    const second = createEmptyCharacterAssets();
    first.sprites.push({ path: "demo-state.json" });
    expect(second).toEqual({ model_path: "", sprites: [], emotion_tags: "" });
  });

  it("reads unknown format banks and legacy static sprites without an SDK", () => {
    const bank = { model_path: "test.demo", sprites: [{ path: "pose.json" }], emotion_tags: "pose" };
    const character = { avatar_type: "demo", avatars: { demo: bank }, sprites: [{ path: "static.png" }] };
    expect(getCharacterAssets(character)).toBe(bank);
    expect(getCharacterAssets(character, "static").sprites).toBe(character.sprites);
    expect(getCharacterAssets(undefined)).toEqual(createEmptyCharacterAssets());
  });
});
