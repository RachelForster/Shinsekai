import { describe, expect, it } from "vitest";
import { vi } from "vitest";

import {
  backgroundDeleteDialogCopy,
  createBackground,
  runBackgroundDeleteTarget,
  type BackgroundDeleteTarget,
} from "../../../features/background-manager/backgroundUtils";
import type { MessageKey } from "../../../shared/i18n";

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

  it("builds delete confirmation copy from the delete target kind", () => {
    const t = (key: MessageKey, values?: Record<string, number | string>) =>
      values ? `${key}:${JSON.stringify(values)}` : key;

    expect(backgroundDeleteDialogCopy({ kind: "background", name: "Room" }, t)).toEqual({
      body: 'background.delete.confirmBody:{"name":"Room"}',
      confirmLabel: "common.delete",
      title: "background.delete.confirmTitle",
    });
    expect(backgroundDeleteDialogCopy({ filename: "scene.png", index: 2, kind: "image", name: "Room" }, t)).toEqual({
      body: 'background.asset.deleteImageConfirmBody:{"filename":"scene.png","index":3,"name":"Room"}',
      confirmLabel: "common.remove",
      title: "common.remove",
    });
    expect(backgroundDeleteDialogCopy({ count: 4, kind: "selected-bgm", indexes: [0, 2], name: "Room" }, t)).toEqual({
      body: 'background.asset.deleteSelectedBgmConfirmBody:{"count":4,"name":"Room"}',
      confirmLabel: "common.delete",
      title: "background.asset.deleteSelectedBgm",
    });
  });

  it.each<[BackgroundDeleteTarget, string, unknown]>([
    [{ kind: "background", name: "Room" }, "deleteBackground", "Room"],
    [{ count: 2, kind: "all-images", name: "Room" }, "deleteAllImages", "Room"],
    [{ filename: "scene.png", index: 1, kind: "image", name: "Room" }, "deleteImage", { index: 1, name: "Room" }],
    [{ filename: "song.mp3", index: 3, kind: "bgm", name: "Room" }, "deleteBgm", { index: 3, name: "Room" }],
    [
      { count: 2, indexes: [4, 1], kind: "selected-bgm", name: "Room" },
      "deleteSelectedBgm",
      { indexes: [4, 1], name: "Room" },
    ],
    [{ count: 3, kind: "all-bgm", name: "Room" }, "deleteAllBgm", "Room"],
  ])("routes %s to %s", (target, expectedAction, expectedPayload) => {
    const actions = {
      deleteAllBgm: vi.fn(),
      deleteAllImages: vi.fn(),
      deleteBackground: vi.fn(),
      deleteBgm: vi.fn(),
      deleteImage: vi.fn(),
      deleteSelectedBgm: vi.fn(),
    };

    runBackgroundDeleteTarget(target, actions);

    expect(actions[expectedAction as keyof typeof actions]).toHaveBeenCalledWith(expectedPayload);
    for (const [name, action] of Object.entries(actions)) {
      expect(action).toHaveBeenCalledTimes(name === expectedAction ? 1 : 0);
    }
  });
});
