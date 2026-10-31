import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TransitionMedia } from "../../../modules/character-visual/TransitionMedia";

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("does not transition on initial display, plays once on change, then loops the target video", () => {
  const edges = [{ fromUrl: "a.png", url: "a-b.webm" }];
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled transitions={edges} />);
  const host = view.container.firstElementChild;
  const original = view.container.querySelector("img")!;
  expect(view.container.querySelector("video")).toBeNull();
  view.rerender(<TransitionMedia src="b.webm" alt="Mika" enabled transitions={edges} />);
  const bridge = view.container.querySelector('video[src="a-b.webm"]')!;
  expect(bridge).not.toBeNull();
  expect(bridge).not.toHaveAttribute("loop");
  expect((bridge as HTMLVideoElement).playbackRate).toBe(1);
  expect((bridge as HTMLVideoElement).defaultPlaybackRate).toBe(1);
  const target = view.container.querySelector('video[src="b.webm"]')!;
  expect(view.container.firstElementChild).toBe(host);
  expect(view.container.querySelector('img[src="a.png"]')).toBe(original);
  expect(original.parentElement).toHaveStyle({ opacity: "1" });
  expect(bridge).toHaveStyle({ opacity: "0" });
  expect(target).not.toHaveAttribute("autoplay");
  fireEvent.loadedData(target);
  fireEvent.loadedData(bridge);
  expect(original.parentElement).toHaveStyle({ opacity: "0" });
  expect(bridge).toHaveStyle({ opacity: "1" });
  const loads = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length;
  fireEvent.ended(bridge);
  expect(view.container.querySelector('video[src="a-b.webm"]')).toBeNull();
  expect(view.container.querySelector('video[src="b.webm"]')).toHaveAttribute("loop");
  expect((view.container.querySelector('video[src="b.webm"]') as HTMLVideoElement).playbackRate).toBe(1);
  expect(view.container.firstElementChild).toBe(host);
  expect(view.container.querySelector('video[src="b.webm"]')).toBe(target);
  expect(target.parentElement).toHaveStyle({ opacity: "1" });
  // Only the departing clip is unloaded; the decoded target is not loaded again.
  expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads + 1);
});

it("holds the final transition frame until the preloaded target has a decoded frame", () => {
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia src="b.webm" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const bridge = view.container.querySelector('video[src="a-b.webm"]')!;
  const target = view.container.querySelector('video[src="b.webm"]')!;
  fireEvent.loadedData(bridge);
  fireEvent.ended(bridge);
  expect(bridge).toBeInTheDocument();
  expect(bridge).toHaveStyle({ opacity: "1" });
  expect(target.parentElement).toHaveStyle({ opacity: "0" });
  fireEvent.loadedData(target);
  expect(bridge).not.toBeInTheDocument();
  expect(view.container.querySelector('video[src="b.webm"]')).toBe(target);
  expect(target.parentElement).toHaveStyle({ opacity: "1" });
});

it("fits a rounded H3 canvas without shrinking the bridge between full-height sprites", () => {
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  const original = view.container.querySelector("img")!;
  Object.defineProperties(original, { naturalWidth: { value: 1086 }, naturalHeight: { value: 1448 } });
  fireEvent.load(original);
  expect(view.container.firstElementChild).toHaveStyle({ aspectRatio: "0.75" });
  view.rerender(
    <TransitionMedia src="b.png" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const bridge = view.container.querySelector("video")!;
  Object.defineProperties(bridge, { videoWidth: { value: 512 }, videoHeight: { value: 672 } });
  fireEvent.loadedMetadata(bridge);
  expect((view.container.firstElementChild as HTMLElement).style.aspectRatio).toBe(String(512 / 672));
  expect(original.parentElement).toHaveStyle({ opacity: "1" });
});

it("waits for the compositor callback rather than exposing a video at loadeddata", () => {
  const callbacks = new Map<HTMLVideoElement, VideoFrameRequestCallback>();
  Object.defineProperty(HTMLVideoElement.prototype, "requestVideoFrameCallback", {
    configurable: true,
    value: function (this: HTMLVideoElement, callback: VideoFrameRequestCallback) {
      callbacks.set(this, callback);
      return 1;
    },
  });
  Object.defineProperty(HTMLVideoElement.prototype, "cancelVideoFrameCallback", { configurable: true, value: vi.fn() });
  try {
    const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
    const original = view.container.querySelector("img")!;
    view.rerender(
      <TransitionMedia src="b.webm" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
    );
    const bridge = view.container.querySelector<HTMLVideoElement>('video[src="a-b.webm"]')!;
    const target = view.container.querySelector<HTMLVideoElement>('video[src="b.webm"]')!;
    fireEvent.loadedData(bridge);
    expect(original.parentElement).toHaveStyle({ opacity: "1" });
    expect(bridge).toHaveStyle({ opacity: "0" });
    act(() => callbacks.get(bridge)!(0, {} as VideoFrameCallbackMetadata));
    expect(bridge).toHaveStyle({ opacity: "1" });
    fireEvent.ended(bridge);
    fireEvent.loadedData(target);
    expect(bridge).toBeInTheDocument();
    act(() => callbacks.get(target)!(0, {} as VideoFrameCallbackMetadata));
    expect(bridge).not.toBeInTheDocument();
    expect(target.parentElement).toHaveStyle({ opacity: "1" });
    view.unmount();
  } finally {
    delete (HTMLVideoElement.prototype as Partial<HTMLVideoElement>).requestVideoFrameCallback;
    delete (HTMLVideoElement.prototype as Partial<HTMLVideoElement>).cancelVideoFrameCallback;
  }
});

it("keeps the outgoing sprite visible when the bridge fails before the target is ready", () => {
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  const original = view.container.querySelector("img")!;
  view.rerender(
    <TransitionMedia src="b.png" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  fireEvent.error(view.container.querySelector("video")!);
  expect(view.container.querySelector('img[src="a.png"]')).toBe(original);
  expect(original.parentElement).toHaveStyle({ opacity: "1" });
  const target = view.container.querySelector('img[src="b.png"]')!;
  fireEvent.load(target);
  expect(view.container.querySelector("video")).toBeNull();
  expect(target.parentElement).toHaveStyle({ opacity: "1" });
});

it("bounds the wait for a target that never finishes loading", () => {
  vi.useFakeTimers();
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia src="b.webm" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const bridge = view.container.querySelector('video[src="a-b.webm"]')!;
  fireEvent.loadedData(bridge);
  fireEvent.ended(bridge);
  act(() => vi.advanceTimersByTime(2100));
  expect(view.container.querySelector('video[src="a-b.webm"]')).toBeNull();
  expect(view.container.querySelector('video[src="b.webm"]')?.parentElement).toHaveStyle({ opacity: "1" });
});

it("allows a 22-frame transition to finish beyond the old one-second fallback", () => {
  vi.useFakeTimers();
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia src="b.png" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const bridge = view.container.querySelector("video")!;
  Object.defineProperty(bridge, "duration", { value: 22 / 24 });
  fireEvent.load(view.container.querySelector('img[src="b.png"]')!);
  fireEvent.loadedData(bridge);
  act(() => vi.advanceTimersByTime(1100));
  expect(view.container.querySelector("video")).toBe(bridge);
  fireEvent.ended(bridge);
  expect(view.container.querySelector("video")).toBeNull();
  expect(view.container.querySelector("img")).toHaveAttribute("src", "b.png");
});

it("cancels an interrupted transition and chooses from the last settled sprite", () => {
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia src="b.png" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const old = view.container.querySelector("video")!;
  view.rerender(
    <TransitionMedia
      src="c.png"
      alt="Mika"
      enabled
      transitions={[
        { fromUrl: "a.png", url: "a-c.webm" },
        { fromUrl: "b.png", url: "b-c.webm" },
      ]}
    />,
  );
  expect(view.container.querySelector("video")).toHaveAttribute("src", "a-c.webm");
  fireEvent.load(view.container.querySelector('img[src="c.png"]')!);
  fireEvent.ended(old);
  expect(view.container.querySelector("video")).toHaveAttribute("src", "a-c.webm");
  fireEvent.ended(view.container.querySelector("video")!);
  expect(view.container.querySelector("img")).toHaveAttribute("src", "c.png");
});

it.each(["error", "timeout", "blocked"])(
  "falls back to the target on %s without waiting for dialogue",
  async (failure) => {
    vi.useFakeTimers();
    const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
    if (failure === "blocked") vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValue(new Error("blocked"));
    view.rerender(
      <TransitionMedia src="b.png" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
    );
    fireEvent.load(view.container.querySelector('img[src="b.png"]')!);
    if (failure === "error") fireEvent.error(view.container.querySelector("video")!);
    if (failure === "timeout") act(() => vi.advanceTimersByTime(2100));
    await act(async () => {});
    expect(view.container.querySelector("video")).toBeNull();
    expect(view.container.querySelector("img")).toHaveAttribute("src", "b.png");
  },
);

it.each(["restore", "reduced", "hidden"])("skips transition for %s", (mode) => {
  if (mode === "reduced")
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia
      src="b.png"
      alt="Mika"
      enabled={mode !== "restore"}
      active={mode !== "hidden"}
      transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]}
    />,
  );
  expect(view.container.querySelector("video")).toBeNull();
  expect(view.container.querySelector("img")).toHaveAttribute("src", "b.png");
});
