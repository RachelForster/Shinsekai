import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CharacterVisual } from "../../../entities/character-visual/CharacterVisual";
import type { AvatarFormat, AvatarSession } from "../../../entities/character-visual/contracts";
import {
  clearRegisteredAvatarFormats,
  registerAvatarFormat,
} from "../../../entities/character-visual/registry";

afterEach(() => {
  cleanup();
  clearRegisteredAvatarFormats();
});

describe("CharacterVisual", () => {
  it("renders a static image for the default avatar type", () => {
    render(
      <CharacterVisual
        asset={{ id: "alice", label: "Alice", url: "/img/alice.png" }}
        imageClassName="sprite-layer__image"
      />,
    );

    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.src).toContain("/img/alice.png");
    expect(img.className).toBe("sprite-layer__image");
  });

  it("renders an unavailable placeholder for an unknown format", () => {
    render(<CharacterVisual asset={{ id: "alice", label: "Alice", url: "", avatarType: "gltf" }} />);

    expect(screen.getByRole("status").textContent).toContain("unknown avatar format: gltf");
  });

  it("mounts a registered format session and disposes it on unmount", async () => {
    const disposed = vi.fn();
    const created = vi.fn().mockResolvedValue({
      controls: {},
      apply: vi.fn(),
      readState: vi.fn(),
      setMouthOpen: vi.fn(),
      resize: vi.fn(),
      dispose: disposed,
    } satisfies AvatarSession<unknown, unknown>);

    const format: AvatarFormat<unknown, unknown> = {
      id: "null",
      label: "Null",
      capabilities: { mouth: true, blink: false, motion: false, sampling: "none" },
      createEmpty: () => ({ model_path: "", sprites: [], emotion_tags: "" }),
      module: { create: created, Editor: () => null },
    };
    registerAvatarFormat(format);

    const { unmount } = render(
      <CharacterVisual asset={{ id: "alice", label: "Alice", url: "", avatarType: "null", modelUrl: "/m.model" }} />,
    );

    expect(await screen.findByTestId("model-container")).toBeInTheDocument();
    expect(created).toHaveBeenCalledTimes(1);
    expect(created.mock.calls[0][0].modelUrl).toBe("/m.model");

    unmount();
    expect(disposed).toHaveBeenCalledTimes(1);
  });
});
