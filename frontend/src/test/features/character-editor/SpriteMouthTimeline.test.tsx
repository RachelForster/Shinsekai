import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SpriteMouthTimeline, mouthFrameAtTime } from "../../../features/character-editor/SpriteMouthTimeline";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../entities/files/repository", () => ({ fileUrl: (value: string) => value }));
const originalFrameCallback = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, "requestVideoFrameCallback");
const originalCancelCallback = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, "cancelVideoFrameCallback");
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  for (const [key, descriptor] of [
    ["requestVideoFrameCallback", originalFrameCallback],
    ["cancelVideoFrameCallback", originalCancelCallback],
  ] as const) {
    if (descriptor) Object.defineProperty(HTMLVideoElement.prototype, key, descriptor);
    else delete (HTMLVideoElement.prototype as unknown as Record<string, unknown>)[key];
  }
});

it("uses decoded timestamps for variable frame intervals", () => {
  const frames = [0, 0.1, 0.3].map((time, index) => ({ index, path: `${index}.jpg`, time }));
  expect(mouthFrameAtTime(frames, 0.2)).toBe(1);
  expect(mouthFrameAtTime(frames, 9)).toBe(2);
});

it("does not let the previous presented frame overwrite an explicit frame step", () => {
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  const callbacks: VideoFrameRequestCallback[] = [];
  Object.defineProperty(HTMLVideoElement.prototype, "requestVideoFrameCallback", {
    configurable: true,
    value: (callback: VideoFrameRequestCallback) => {
      callbacks.push(callback);
      return callbacks.length;
    },
  });
  Object.defineProperty(HTMLVideoElement.prototype, "cancelVideoFrameCallback", { configurable: true, value: vi.fn() });
  const pick = vi.fn();
  render(
    <I18nProvider language="en">
      <SpriteMouthTimeline
        src="speech.mp4"
        frames={[0, 0.04, 0.1].map((time, index) => ({ index, time, path: `${index}.jpg` }))}
        disabled={false}
        onPick={pick}
      />
    </I18nProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Next frame" }));
  act(() => callbacks[0](0, { mediaTime: 0 } as VideoFrameCallbackMetadata));
  expect(screen.getByText("Frame 2 / 3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Use current frame as Half-open" }));
  expect(pick).toHaveBeenCalledWith("half", 1);
  act(() => callbacks[1](1, { mediaTime: 0.04 } as VideoFrameCallbackMetadata));
  expect(screen.getByText("Frame 2 / 3")).toBeInTheDocument();
});
