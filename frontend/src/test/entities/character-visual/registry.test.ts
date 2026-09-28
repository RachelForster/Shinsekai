import { afterEach, describe, expect, it, vi } from "vitest";

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
    load: async () => ({
      create: async () => {
        throw new Error("not implemented");
      },
      Editor: () => null,
    }),
  };
}

afterEach(clearRegisteredAvatarFormats);

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

  it("normalizes identifiers and rejects collisions", () => {
    registerAvatarFormat(nullFormat(" VRM "));
    expect(avatarFormat("vrm")?.id).toBe("vrm");
    expect(avatarFormat(" VRM ")?.id).toBe("vrm");
    expect(() => registerAvatarFormat(nullFormat("vrm"))).toThrow("duplicate");
    expect(() => registerAvatarFormat(nullFormat(" STATIC "))).toThrow("reserved");
  });

  it("loads on demand, shares concurrent loads and retries failures", async () => {
    const format = nullFormat();
    const module = await format.load();
    const load = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(module);
    registerAvatarFormat({ ...format, load });
    expect(load).not.toHaveBeenCalled();
    const registered = avatarFormat("null")!;
    await expect(registered.load()).rejects.toThrow("offline");
    const first = registered.load();
    expect(registered.load()).toBe(first);
    await expect(first).resolves.toBe(module);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("clears between tests", () => {
    registerAvatarFormat(nullFormat());
    clearRegisteredAvatarFormats();
    expect(avatarFormat("null")).toBeUndefined();
  });
});
