import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CharacterVisual, type CharacterVisualProps } from "../../../entities/character-visual/CharacterVisual";
import type {
  AvatarCapabilities,
  AvatarSession,
  CharacterVisualAsset,
} from "../../../entities/character-visual/contracts";
import { clearRegisteredAvatarFormats, registerAvatarFormat } from "../../../entities/character-visual/registry";
import { SpriteLayer } from "../../../features/chat-stage/components/StageLayers";
import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";

const capabilities: AvatarCapabilities = { mouth: false, blink: false, motion: false, sampling: "none" };
const asset: CharacterVisualAsset = {
  id: "alice",
  label: "Alice",
  avatarType: "demo",
  modelUrl: "/alice.model",
  url: "/state-1.json",
};
const props: CharacterVisualProps = {
  asset,
  className: "sprite-layer__image",
  onImageError: () => {},
  onMouseDown: () => {},
  hitbox: false,
  mode: "play",
};
function session() {
  return {
    capabilities,
    controls: {},
    apply: vi.fn().mockResolvedValue(undefined),
    readState: () => ({}),
    setMouthOpen: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  } satisfies AvatarSession<unknown, unknown>;
}
function register(create = vi.fn().mockResolvedValue(session())) {
  registerAvatarFormat({
    id: "demo",
    label: "Demo",
    capabilities,
    createEmpty: () => ({ model_path: "", sprites: [], emotion_tags: "" }),
    load: async () => ({ create, Editor: () => null }),
  });
  return create;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  clearRegisteredAvatarFormats();
  vi.unstubAllGlobals();
});

describe("CharacterVisual", () => {
  it("preserves static image hooks and resets a broken image on resource change", () => {
    const onImageError = vi.fn();
    const view = render(
      <CharacterVisual
        {...props}
        onImageError={onImageError}
        asset={{ ...asset, avatarType: "static", modelUrl: "", url: "/alice.png" }}
      />,
    );
    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img.className).toBe("sprite-layer__image");
    fireEvent.error(img);
    expect(onImageError).toHaveBeenCalledOnce();
    view.rerender(
      <CharacterVisual {...props} asset={{ ...asset, avatarType: "static", modelUrl: "", url: "/new.png" }} />,
    );
    expect(screen.getByRole("img")).not.toBe(img);
  });

  it("recovers from an unknown format when selecting a registered model", async () => {
    const create = register();
    const view = render(<CharacterVisual {...props} asset={{ ...asset, avatarType: "missing" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("unknown avatar format");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    view.rerender(<CharacterVisual {...props} />);
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("applies new states without recreating the model and disposes once", async () => {
    const instance = session();
    const create = register(vi.fn().mockResolvedValue(instance));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => ({ ok: true, json: async () => ({ url }) })),
    );
    const view = render(<CharacterVisual {...props} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledTimes(1));
    view.rerender(<CharacterVisual {...props} asset={{ ...asset, url: "/state-2.json" }} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledTimes(2));
    expect(create).toHaveBeenCalledOnce();
    expect(instance.dispose).not.toHaveBeenCalled();
    expect(instance.apply.mock.calls[1][0]).toEqual({ url: "/state-2.json" });
    view.unmount();
    expect(instance.dispose).toHaveBeenCalledOnce();
  });

  it("ignores a stale response even when fetch does not honor abort", async () => {
    const instance = session();
    register(vi.fn().mockResolvedValue(instance));
    const old = deferred<object>();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => old.promise })
      .mockResolvedValue({ ok: true, json: async () => ({ latest: true }) });
    vi.stubGlobal("fetch", fetch);
    const view = render(<CharacterVisual {...props} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    view.rerender(<CharacterVisual {...props} asset={{ ...asset, url: "/state-2.json" }} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledOnce());
    await act(async () => old.resolve({ latest: false }));
    expect(instance.apply).toHaveBeenCalledOnce();
    expect(instance.apply.mock.calls[0][0]).toEqual({ latest: true });
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("disposes a late creation after unmount without applying or resizing", async () => {
    const late = deferred<AvatarSession<unknown, unknown>>();
    const instance = session();
    const create = register(vi.fn().mockReturnValue(late.promise));
    const view = render(<CharacterVisual {...props} />);
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    view.unmount();
    await act(async () => late.resolve(instance));
    expect(instance.dispose).toHaveBeenCalledOnce();
    expect(instance.resize).not.toHaveBeenCalled();
    expect(instance.apply).not.toHaveBeenCalled();
  });

  it("recovers when a failed model is replaced", async () => {
    const instance = session();
    register(vi.fn().mockRejectedValueOnce(new Error("bad model")).mockResolvedValue(instance));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    const view = render(<CharacterVisual {...props} />);
    expect(await screen.findByRole("status")).toHaveTextContent("bad model");
    expect(screen.getByTestId("model-container")).toBeInTheDocument();
    view.rerender(<CharacterVisual {...props} asset={{ ...asset, modelUrl: "/good.model" }} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledOnce());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("rejects HTTP errors and recovers on the next state without a reload", async () => {
    const instance = session();
    const create = register(vi.fn().mockResolvedValue(instance));
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({ ok: false, status: 404 })
        .mockResolvedValue({ ok: true, json: async () => ({}) }),
    );
    const view = render(<CharacterVisual {...props} />);
    expect(await screen.findByRole("status")).toHaveTextContent("404");
    expect(instance.apply).not.toHaveBeenCalled();
    view.rerender(<CharacterVisual {...props} asset={{ ...asset, url: "/good.json" }} mode="restore" />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledOnce());
    expect(instance.apply.mock.calls[0][1]).toBe("restore");
    expect(create).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps the instance, slot styling and drag hitbox through stage state changes", async () => {
    const instance = session();
    const create = register(vi.fn().mockResolvedValue(instance));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    const onDragStart = vi.fn();
    const sprite = {
      id: "alice",
      label: "Alice",
      characterName: "Alice",
      path: "/1.json",
      avatarType: "demo",
      modelUrl: "/alice.model",
      scale: 1.5,
      slot: 0,
    };
    const view = render(
      <SpriteLayer
        hidden={false}
        onDragStart={onDragStart}
        runtimeScaleForSprite={() => 1}
        speaker="Alice"
        sprites={[sprite]}
      />,
    );
    await waitFor(() => expect(instance.apply).toHaveBeenCalledOnce());
    const visual = screen.getByLabelText("Alice");
    expect(visual).toHaveClass("sprite-layer__image");
    expect(visual.dataset.chatStageHitbox).toBe("true");
    expect(visual.closest("figure")?.style.getPropertyValue("--sprite-scale")).toBe("1.5");
    fireEvent.mouseDown(visual);
    expect(onDragStart).toHaveBeenCalledOnce();
    view.rerender(
      <SpriteLayer hidden={false} runtimeScaleForSprite={() => 1} sprites={[{ ...sprite, path: "/2.json" }]} />,
    );
    await waitFor(() => expect(instance.apply).toHaveBeenCalledTimes(2));
    expect(create).toHaveBeenCalledOnce();
  });

  it("keeps a character mounted across snapshot IDs, live events and reconnect", async () => {
    const instance = session();
    const create = register(vi.fn().mockResolvedValue(instance));
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) })),
    );
    const snapshot = {
      ...emptyChatState,
      effectImage: null,
      sprites: [{ id: "Alice-0", label: "Alice", path: "/1.json", avatarType: "demo", modelUrl: "/alice.model" }],
    };
    let state = chatStageReducer(emptyChatState, { type: "hydrate", snapshot });
    const view = render(<SpriteLayer hidden={false} runtimeScaleForSprite={() => 1} sprites={state.sprites} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledOnce());
    const container = screen.getByTestId("model-container");
    state = chatStageReducer(state, {
      type: "event",
      event: {
        type: "sprite.show",
        characterName: "Alice",
        url: "/2.json",
        avatarType: "demo",
        modelUrl: "/alice.model",
        scale: 1,
        seq: 1,
        ts: 1,
        v: 1,
      },
    });
    expect(state.sprites[0].id).toBe("Alice");
    view.rerender(<SpriteLayer hidden={false} runtimeScaleForSprite={() => 1} sprites={state.sprites} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledTimes(2));
    state = chatStageReducer(state, { type: "hydrate", snapshot: { ...snapshot, eventSeq: 2 } });
    view.rerender(<SpriteLayer hidden={false} runtimeScaleForSprite={() => 1} sprites={state.sprites} />);
    await waitFor(() => expect(instance.apply).toHaveBeenCalledTimes(3));
    expect(instance.apply.mock.calls.map((call) => call[1])).toEqual(["restore", "play", "restore"]);
    expect(create).toHaveBeenCalledOnce();
    expect(instance.dispose).not.toHaveBeenCalled();
    expect(screen.getByTestId("model-container")).toBe(container);
    view.unmount();
    expect(instance.dispose).toHaveBeenCalledOnce();
  });
});
