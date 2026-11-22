import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { VoiceAnalyser } from "../../../features/chat-stage/audio/voiceAnalyser";

let tick: FrameRequestCallback;
const disconnect = vi.fn();
const analyser = {
  fftSize: 256,
  getFloatTimeDomainData: (data: Float32Array) => data.fill(0.1),
};
const source = {
  connect: vi.fn(),
  disconnect,
  context: { state: "running", createAnalyser: () => analyser },
} as unknown as MediaElementAudioSourceNode;
beforeEach(() => {
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameRequestCallback) => {
      tick = callback;
      return 1;
    }),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => vi.unstubAllGlobals());

it("routes only actual playing voice and clears during pause/buffering and stop", async () => {
  const listener = vi.fn();
  const driver = new VoiceAnalyser(listener);
  const audio = new Audio();
  Object.defineProperty(audio, "paused", { value: false });
  driver.start(audio, "Haru", source);
  await Promise.resolve();
  tick(0);
  expect(listener).toHaveBeenLastCalledWith("Haru", expect.any(Number));
  expect(listener.mock.lastCall![1]).toBeGreaterThan(0);
  audio.dispatchEvent(new Event("waiting"));
  tick(10);
  expect(listener).toHaveBeenLastCalledWith("Haru", 0);
  audio.dispatchEvent(new Event("playing"));
  tick(20);
  expect(listener.mock.lastCall![1]).toBeGreaterThan(0);
  driver.stop();
  expect(listener).toHaveBeenLastCalledWith("Haru", 0);
  expect(disconnect).toHaveBeenCalledWith(analyser);
  driver.stop();
});

it("does not create WebAudio for a voice without a character", () => {
  const listener = vi.fn();
  const driver = new VoiceAnalyser(listener);
  driver.start(new Audio(), "", source);
  expect(requestAnimationFrame).not.toHaveBeenCalled();
  driver.stop();
});
