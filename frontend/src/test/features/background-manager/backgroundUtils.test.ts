import { describe, expect, it } from "vitest";

import { createBackground } from "../../../features/background-manager/backgroundUtils";

describe("background manager utilities", () => {
  it("creates a safe empty background draft", () => {
    expect(createBackground()).toEqual({
      bg_tags: "",
      bgm_list: [],
      bgm_tags: "",
      name: "",
      sprite_prefix: "temp",
      sprites: [],
    });
  });
});
