import { afterEach, describe, expect, it, vi } from "vitest";
import { cropGraphAvatar, prepareGraphAvatar } from "../../../features/character-relation/model/graphAvatar";
import { composeGraphNode } from "../../../features/character-relation/view/composingGraphNode";

afterEach(() => vi.restoreAllMocks());

describe("graph avatars", () => {
  it("uses portrait crop coordinates and zoom for the source image", () => {
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    const image = new Image();
    expect(cropGraphAvatar(image, 200, 400, { x: 0.5, y: 0.5, zoom: 2 })).toBeDefined();
    expect(drawImage).toHaveBeenCalledWith(image, 50, 150, 100, 100, 0, 0, 128, 128);
  });

  it("returns no avatar when loading is cancelled", async () => {
    const image = new Image();
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
      tag === "img" ? image : createElement(tag)) as typeof document.createElement);
    const controller = new AbortController();
    const pending = prepareGraphAvatar("/missing.png", false, { x: 0.5, y: 0.2, zoom: 1 }, controller.signal);
    controller.abort();
    expect(await pending).toBeUndefined();
  });

  it("crops the decoded first video frame and releases the video", async () => {
    const video = document.createElement("video");
    Object.defineProperties(video, { videoWidth: { value: 200 }, videoHeight: { value: 400 } });
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
      tag === "video" ? video : createElement(tag)) as typeof document.createElement);
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(video, "pause").mockImplementation(() => {});
    vi.spyOn(video, "load").mockImplementation(() => {});
    const pending = prepareGraphAvatar(
      "/portrait.webm",
      true,
      { x: 0.5, y: 0.5, zoom: 2 },
      new AbortController().signal,
    );
    video.dispatchEvent(new Event("loadeddata"));
    expect(await pending).toBeInstanceOf(HTMLCanvasElement);
    expect(drawImage).toHaveBeenCalledWith(video, 50, 150, 100, 100, 0, 0, 128, 128);
    expect(video.hasAttribute("src")).toBe(false);
  });

  it("falls back to a circle when an avatar cannot be composed", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const node = composeGraphNode({
      node: { key: "A" },
      position: { x: 1, y: 2 },
      owner: "A",
      activeNodeKey: "A",
      selectedNodeKey: "A",
      fixed: true,
      backgroundColor: "#000",
      theme: { accent: "#fff", selected: "#222", muted: "#888" },
      characterColors: new Map(),
      avatars: new Map([["a", document.createElement("canvas")]]),
    });
    expect(node).toMatchObject({ symbol: "circle", id: "A", itemStyle: { borderWidth: 4 } });
  });
});
