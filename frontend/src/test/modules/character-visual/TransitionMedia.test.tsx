import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TransitionMedia } from "../../../modules/character-visual/TransitionMedia";
import { setSpriteTransitionPlaybackRate } from "../../../shared/assets/useSpriteTransitionPlaybackRate";
import { routeAvatarSpeechEvent, routeAvatarVoice } from "../../../modules/character-visual/voiceRoute";

beforeEach(() => {
  setSpriteTransitionPlaybackRate(1);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => {
  cleanup();
  routeAvatarSpeechEvent("Mika", "finished");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  setSpriteTransitionPlaybackRate(1);
});

function decoded(element: HTMLImageElement | HTMLVideoElement) {
  if (element instanceof HTMLVideoElement) fireEvent.loadedData(element);
  else fireEvent.load(element);
}

function opacityEnded(element: Element) {
  fireEvent(element, Object.assign(new Event("transitionend", { bubbles: true }), { propertyName: "opacity" }));
}

it("retains the outgoing speaking surface until the expression fade is fully transparent", () => {
  const view = render(
    <TransitionMedia src="a.png" speakingSrc="a-talk.webm" voiceCharacterName="Mika" alt="Mika" enabled />,
  );
  decoded(view.container.querySelector("img")!);
  const outgoingTalk = view.container.querySelector<HTMLVideoElement>('[src="a-talk.webm"]')!;
  decoded(outgoingTalk);
  act(() => {
    routeAvatarSpeechEvent("Mika", "started");
    routeAvatarVoice("Mika", 0.6);
  });
  expect(outgoingTalk.style.opacity).toBe("1");
  view.rerender(<TransitionMedia src="b.png" speakingSrc="b-talk.webm" voiceCharacterName="Mika" alt="Mika" enabled />);
  expect(view.container.querySelector('[src="a-talk.webm"]')).toBe(outgoingTalk);
  expect(outgoingTalk.style.opacity).toBe("1");
  decoded(view.container.querySelector<HTMLImageElement>('[src="b.png"]')!);
  const content = view.container.querySelector(".character-visual__transition-content")!;
  expect(content).toHaveAttribute("data-fade-phase", "out");
  expect(outgoingTalk).toBeInTheDocument();
  opacityEnded(content);
  expect(outgoingTalk).not.toBeInTheDocument();
});

it.each([
  ["a.png", "b.png"],
  ["a.png", "b.webm"],
  ["a.mp4", "b.png"],
  ["a.webm", "b.mp4"],
])("fades %s out before fading %s in when no matching clip exists", (from, to) => {
  const view = render(<TransitionMedia src={from} alt="Mika" enabled className="sprite-layer__image" />);
  const host = view.container.firstElementChild;
  const content = view.container.querySelector(".character-visual__transition-content")!;
  const original = view.container.querySelector<HTMLImageElement | HTMLVideoElement>("img, video")!;
  decoded(original);
  expect(content).not.toHaveAttribute("data-fade-phase");

  view.rerender(
    <TransitionMedia
      src={to}
      alt="Mika"
      enabled
      className="sprite-layer__image"
      transitions={[{ fromUrl: "unrelated.png", url: "unrelated-transition.webm" }]}
    />,
  );
  const target = view.container.querySelector<HTMLImageElement | HTMLVideoElement>(`[src="${to}"]`)!;
  expect(content).toHaveAttribute("data-fade-phase", "loading");
  expect(content).toHaveStyle({ opacity: "1" });
  expect(original.parentElement).toHaveStyle({ opacity: "1" });
  expect(target.parentElement).toHaveStyle({ opacity: "0" });
  expect(view.container.querySelector('[src="unrelated-transition.webm"]')).toBeNull();
  expect(target).not.toHaveAttribute("autoplay");

  decoded(target);
  expect(content).toHaveAttribute("data-fade-phase", "out");
  expect(content).toHaveStyle({ opacity: "0", transition: "opacity 160ms ease-in-out" });
  expect(original).toBeInTheDocument();
  expect(target.parentElement).toHaveStyle({ opacity: "0" });
  opacityEnded(original);
  expect(content).toHaveAttribute("data-fade-phase", "out");
  opacityEnded(content);

  expect(original).not.toBeInTheDocument();
  expect(view.container.querySelector(`[src="${to}"]`)).toBe(target);
  expect(target.parentElement).toHaveStyle({ opacity: "1" });
  expect(content).toHaveAttribute("data-fade-phase", "in");
  expect(content).toHaveStyle({ opacity: "1" });
  if (target instanceof HTMLVideoElement) {
    expect(target).toHaveAttribute("autoplay");
    expect(target).toHaveAttribute("loop");
  }

  opacityEnded(content);
  expect(content).not.toHaveAttribute("data-fade-phase");
  expect(view.container.firstElementChild).toBe(host);
});

it("waits for a decoded target, swaps dimensions while transparent, and bounds missing fade events", () => {
  vi.useFakeTimers();
  const dimensions = vi.fn();
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled onDimensions={dimensions} />);
  const original = view.container.querySelector("img")!;
  Object.defineProperties(original, { naturalWidth: { value: 400 }, naturalHeight: { value: 800 } });
  fireEvent.load(original);
  view.rerender(<TransitionMedia src="b.png" alt="Mika" enabled onDimensions={dimensions} />);
  const content = view.container.querySelector(".character-visual__transition-content")!;
  act(() => vi.advanceTimersByTime(5000));
  expect(content).toHaveAttribute("data-fade-phase", "loading");
  expect(original.parentElement).toHaveStyle({ opacity: "1" });
  const target = view.container.querySelector('img[src="b.png"]')!;
  Object.defineProperties(target, { naturalWidth: { value: 800 }, naturalHeight: { value: 800 } });
  fireEvent.load(target);
  expect(view.container.firstElementChild).toHaveStyle({ aspectRatio: "0.5" });
  act(() => vi.advanceTimersByTime(300));
  expect(content).toHaveAttribute("data-fade-phase", "in");
  expect(view.container.firstElementChild).toHaveStyle({ aspectRatio: "1" });
  expect(dimensions).toHaveBeenLastCalledWith(800, 800);
  expect(target).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(300));
  expect(content).not.toHaveAttribute("data-fade-phase");
  expect(content).toHaveStyle({ opacity: "1" });
});

it("keeps the latest request when a fade is interrupted and ignores the old timers", () => {
  vi.useFakeTimers();
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(<TransitionMedia src="b.png" alt="Mika" enabled />);
  fireEvent.load(view.container.querySelector('img[src="b.png"]')!);
  const content = view.container.querySelector(".character-visual__transition-content")!;
  expect(content).toHaveAttribute("data-fade-phase", "out");
  view.rerender(<TransitionMedia src="c.webm" alt="Mika" enabled />);
  act(() => vi.advanceTimersByTime(1000));
  expect(content).toHaveAttribute("data-fade-phase", "loading");
  expect(view.container.querySelector('img[src="a.png"]')).toBeInTheDocument();
  expect(view.container.querySelector('img[src="b.png"]')).toBeNull();
  const target = view.container.querySelector('video[src="c.webm"]')!;
  fireEvent.loadedData(target);
  opacityEnded(content);
  expect(view.container.querySelector("img")).toBeNull();
  expect(target.parentElement).toHaveStyle({ opacity: "1" });
  opacityEnded(content);
  expect(content).not.toHaveAttribute("data-fade-phase");
});

it("cancels a pending fade when returning to the currently displayed sprite", () => {
  vi.useFakeTimers();
  const view = render(<TransitionMedia src="a.webm" alt="Mika" enabled />);
  const original = view.container.querySelector("video")!;
  view.rerender(<TransitionMedia src="b.png" alt="Mika" enabled />);
  fireEvent.load(view.container.querySelector("img")!);
  view.rerender(<TransitionMedia src="a.webm" alt="Mika" enabled />);
  act(() => vi.advanceTimersByTime(1000));
  expect(view.container.querySelector("video")).toBe(original);
  expect(view.container.querySelector("img")).toBeNull();
  expect(view.container.querySelector(".character-visual__transition-content")).not.toHaveAttribute("data-fade-phase");
});

it("fades from the visible bridge when interrupted by a sprite without a matching clip", () => {
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia src="b.png" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const bridge = view.container.querySelector("video")!;
  fireEvent.loadedData(bridge);
  const content = view.container.querySelector(".character-visual__transition-content")!;
  expect(content).not.toHaveAttribute("data-fade-phase");
  view.rerender(<TransitionMedia src="c.png" alt="Mika" enabled />);
  expect(bridge).toBeInTheDocument();
  expect(bridge).toHaveStyle({ opacity: "1" });
  expect(bridge).not.toHaveAttribute("autoplay");
  const target = view.container.querySelector('img[src="c.png"]')!;
  fireEvent.load(target);
  fireEvent.ended(bridge);
  expect(content).toHaveAttribute("data-fade-phase", "out");
  expect(target.parentElement).toHaveStyle({ opacity: "0" });
  opacityEnded(content);
  expect(bridge).not.toBeInTheDocument();
  expect(target.parentElement).toHaveStyle({ opacity: "1" });
  opacityEnded(content);
  expect(content).not.toHaveAttribute("data-fade-phase");
});

it.each(["restore", "reduced", "inactive", "hidden"])("skips the default fade for %s", (mode) => {
  vi.useFakeTimers();
  if (mode === "reduced")
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  if (mode === "hidden") vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  view.rerender(<TransitionMedia src="b.webm" alt="Mika" enabled={mode !== "restore"} active={mode !== "inactive"} />);
  expect(view.container.querySelector("img")).toBeNull();
  expect(view.container.querySelector(".character-visual__transition-content")).not.toHaveAttribute("data-fade-phase");
  expect(view.container.querySelector("video")?.parentElement).toHaveStyle({ opacity: "1" });
});

it.each(["inactive", "hidden", "unmount"])("cleans up an ongoing fade on %s", (mode) => {
  vi.useFakeTimers();
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(<TransitionMedia src="b.png" alt="Mika" enabled />);
  fireEvent.load(view.container.querySelector('img[src="b.png"]')!);
  if (mode === "inactive") view.rerender(<TransitionMedia src="b.png" alt="Mika" enabled active={false} />);
  else if (mode === "hidden") {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    fireEvent(document, new Event("visibilitychange"));
  } else view.unmount();
  act(() => vi.advanceTimersByTime(1000));
  expect(view.container.querySelector('img[src="a.png"]')).toBeNull();
  if (mode !== "unmount") {
    expect(view.container.querySelector(".character-visual__transition-content")).not.toHaveAttribute(
      "data-fade-phase",
    );
    expect(view.container.querySelector("img")).toHaveAttribute("src", "b.png");
  } else expect(view.container).toBeEmptyDOMElement();
});

it("changes the bridge speed live without reloading it or changing the target loop", () => {
  vi.useFakeTimers();
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled />);
  view.rerender(
    <TransitionMedia src="b.webm" alt="Mika" enabled transitions={[{ fromUrl: "a.png", url: "a-b.webm" }]} />,
  );
  const bridge = view.container.querySelector<HTMLVideoElement>('video[src="a-b.webm"]')!;
  const target = view.container.querySelector<HTMLVideoElement>('video[src="b.webm"]')!;
  Object.defineProperty(bridge, "duration", { value: 22 / 24 });
  fireEvent.loadedData(target);
  fireEvent.loadedData(bridge);
  bridge.currentTime = 0.2;
  const loads = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length;
  act(() => setSpriteTransitionPlaybackRate(0.5));
  expect(bridge.playbackRate).toBe(0.5);
  expect(bridge.defaultPlaybackRate).toBe(0.5);
  expect(bridge.currentTime).toBe(0.2);
  expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads);
  act(() => vi.advanceTimersByTime(2100));
  expect(bridge).toBeInTheDocument();
  fireEvent.ended(bridge);
  expect(target).toHaveAttribute("loop");
  expect(target.playbackRate).toBe(1);
});

it("calibrates the bridge in the existing highlight host and preserves the decoded target", () => {
  const before = {
    width: 480,
    height: 800,
    bounds: [0.1, 0.02, 0.9, 0.98] as [number, number, number, number],
    luma: 96,
  };
  const targetMetrics = {
    ...before,
    height: 768,
    bounds: [0.1, 0, 0.9, 1] as [number, number, number, number],
    luma: 100,
  };
  const view = render(<TransitionMedia src="a.png" alt="Mika" enabled className="sprite-layer__image" />);
  const host = view.container.firstElementChild;
  view.rerender(
    <TransitionMedia
      src="b.png"
      alt="Mika"
      enabled
      className="sprite-layer__image"
      transitions={[
        {
          fromUrl: "a.png",
          url: "a-b.webm",
          presentation: { from: before, first: before, last: before, to: targetMetrics },
        },
      ]}
    />,
  );
  const target = view.container.querySelector('img[src="b.png"]')!;
  expect(host).toHaveStyle({ aspectRatio: "0.625" });
  Object.defineProperties(target, { naturalWidth: { value: 480 }, naturalHeight: { value: 768 } });
  fireEvent.load(target);
  const clip = view.container.querySelector<HTMLVideoElement>("video")!;
  Object.defineProperties(clip, {
    duration: { value: 22 / 24 },
    videoWidth: { value: 480 },
    videoHeight: { value: 800 },
  });
  fireEvent.loadedMetadata(clip);
  fireEvent.loadedData(clip);
  clip.currentTime = 21 / 24;
  fireEvent.timeUpdate(clip);
  expect(clip.style.filter).toContain("1.041666");
  expect(clip.style.transform).toContain("1.041666");
  expect(view.container.firstElementChild).toBe(host);
  expect(host).toHaveClass("sprite-layer__image");
  expect(clip).not.toHaveClass("sprite-layer__image");
  fireEvent.ended(clip);
  expect(target).toBeInTheDocument();
  expect(target).not.toHaveStyle({ filter: clip.style.filter });
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
