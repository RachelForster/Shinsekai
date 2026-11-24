import { describe, expect, it } from "vitest";

import { createBackground } from "../../../features/background-manager/backgroundUtils";

describe("background manager utilities", () => {
  it("creates a complete editable background draft with non-colliding sprite prefix", () => {
    expect(createBackground()).toEqual({
      bg_tags: "",
      bgm_list: [],
      bgm_tags: "",
      name: "",
      sprite_prefix: "bg_1",
      sprites: [],
    });
    expect(createBackground(["bg_1"]).sprite_prefix).toBe("bg_2");
  });
});
