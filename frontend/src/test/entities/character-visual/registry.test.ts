import { describe, expect, it } from "vitest";

import type { AvatarFormat } from "../../../entities/character-visual/contracts";
import {
  avatarFormat,
  clearRegisteredAvatarFormats,
  registerAvatarFormat,
  registeredAvatarFormats,
} from "../../../entities/character-visual/registry";

function nullFormat(id = "null"): AvatarFormat<unknown, unknown> {
  return {
    id,
    label: "Null",
    capabilities: { mouth: true, blink: false, motion: false, sampling: "none" },
    createEmpty: () => ({ model_path: "", sprites: [], emotion_tags: "" }),
    module: {
      create: async () => {
        throw new Error("not implemented");
      },
      Editor: () => null,
    },
  };
}

describe("avatar format registry", () => {
  it("registers and looks up a format", () => {
    registerAvatarFormat(nullFormat());
    expect(avatarFormat("null")?.id).toBe("null");
    expect(registeredAvatarFormats().map((f) => f.id)).toEqual(["null"]);
  });

  it("rejects the reserved static id", () => {
    expect(() => registerAvatarFormat(nullFormat("static"))).toThrow("reserved");
  });

  it("rejects an empty id", () => {
    expect(() => registerAvatarFormat(nullFormat("  "))).toThrow("empty");
  });

  it("clears between tests", () => {
    registerAvatarFormat(nullFormat());
    clearRegisteredAvatarFormats();
    expect(avatarFormat("null")).toBeUndefined();
  });
});
