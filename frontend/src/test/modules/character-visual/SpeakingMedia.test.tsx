import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SpeakingMedia } from "../../../modules/character-visual/SpeakingMedia";
import { routeAvatarSpeechEvent, routeAvatarVoice } from "../../../modules/character-visual/voiceRoute";

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(performance, "now").mockImplementation(() => Date.now());
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  routeAvatarSpeechEvent("Mika", "finished");
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function mount() {
  const view = render(<SpeakingMedia src="/idle.webm" speakingSrc="/talk.webm" voiceCharacterName="Mika" alt="Mika" />);
  const idle = view.container.querySelector('video[src="/idle.webm"]') as HTMLVideoElement;
  const talk = view.container.querySelector('video[src="/talk.webm"]') as HTMLVideoElement;
  return { ...view, idle, talk };
}

it("waits for a decoded talking frame, pauses on silence, and resumes without seeking or replacing the video", () => {
  const { container, idle, talk } = mount();
  act(() => {
    routeAvatarSpeechEvent("Mika", "started");
    routeAvatarVoice("Mika", 0.5);
  });
  expect(talk.style.opacity).toBe("0");
  fireEvent.loadedData(talk);
  expect(talk.style.opacity).toBe("1");
  expect(idle.style.opacity).toBe("0");
  expect(talk.autoplay).toBe(true);
  talk.currentTime = 0.7;
  act(() => {
    routeAvatarVoice("Mika", 0);
    vi.advanceTimersByTime(100);
    routeAvatarVoice("Mika", 0.3);
    vi.advanceTimersByTime(100);
  });
  expect(talk.autoplay).toBe(true);
  act(() => {
    routeAvatarVoice("Mika", 0);
    vi.advanceTimersByTime(150);
  });
  expect(talk.autoplay).toBe(false);
  expect(talk.style.opacity).toBe("1");
  expect(talk.currentTime).toBe(0.7);
  act(() => routeAvatarVoice("Mika", 0.5));
  expect(talk.autoplay).toBe(true);
  expect(container.querySelector('video[src="/talk.webm"]')).toBe(talk);
  expect(talk.currentTime).toBe(0.7);
  act(() => routeAvatarSpeechEvent("Mika", "finished"));
  expect(talk.autoplay).toBe(false);
  expect(talk.style.opacity).toBe("0");
  expect(idle.style.opacity).toBe("1");
});

it("replays current voice state when an expression changes mid-sentence and ignores other characters", () => {
  act(() => {
    routeAvatarSpeechEvent("Mika", "started");
    routeAvatarVoice("Mika", 0.5);
  });
  const { talk } = mount();
  fireEvent.loadedData(talk);
  expect(talk.style.opacity).toBe("1");
  expect(talk.autoplay).toBe(true);
  act(() => routeAvatarSpeechEvent("Other", "finished"));
  expect(talk.autoplay).toBe(true);
  routeAvatarSpeechEvent("Other", "finished");
});

it("follows vocal accents within a gentle speed range and pauses on the real gap instead of the smoothed tail", () => {
  const { talk } = mount();
  fireEvent.loadedData(talk);
  talk.currentTime = 0.7;
  act(() => {
    routeAvatarSpeechEvent("Mika", "started");
    for (let frame = 0; frame < 30; frame++) {
      vi.advanceTimersByTime(16);
      routeAvatarVoice("Mika", 0.6, 1);
    }
  });
  expect(talk.playbackRate).toBeGreaterThan(1.03);
  expect(talk.playbackRate).toBeLessThanOrEqual(1.08);
  act(() => {
    for (let frame = 0; frame < 30; frame++) {
      vi.advanceTimersByTime(16);
      routeAvatarVoice("Mika", 0.6, 0.03);
    }
  });
  expect(talk.playbackRate).toBeLessThan(1);
  expect(talk.playbackRate).toBeGreaterThanOrEqual(0.92);
  act(() => {
    routeAvatarVoice("Mika", 0.6, 0);
    vi.advanceTimersByTime(150);
  });
  expect(talk.autoplay).toBe(false);
  expect(talk.currentTime).toBe(0.7);
});

it("keeps idle visible on talking-video failure and suspends hidden-stage playback", () => {
  const view = mount();
  fireEvent.loadedData(view.talk);
  act(() => routeAvatarSpeechEvent("Mika", "started"));
  view.rerender(
    <SpeakingMedia src="/idle.webm" speakingSrc="/talk.webm" voiceCharacterName="Mika" alt="Mika" active={false} />,
  );
  expect(view.talk.autoplay).toBe(false);
  view.rerender(<SpeakingMedia src="/idle.webm" speakingSrc="/talk.webm" voiceCharacterName="Mika" alt="Mika" />);
  fireEvent.error(view.talk);
  expect(view.idle.style.opacity).toBe("1");
  expect(view.talk.style.opacity).toBe("0");
});

it("clears an old character's speaking state when its voice route changes", () => {
  const view = mount();
  fireEvent.loadedData(view.talk);
  act(() => routeAvatarSpeechEvent("Mika", "started"));
  expect(view.talk.style.opacity).toBe("1");
  view.rerender(<SpeakingMedia src="/idle.webm" speakingSrc="/talk.webm" voiceCharacterName="Other" alt="Other" />);
  expect(view.talk.style.opacity).toBe("0");
  expect(view.talk.autoplay).toBe(false);
});

it("calibrates the talking loop against idle without changing the original framing or highlight", () => {
  const reference = {
    width: 200,
    height: 400,
    bounds: [0.2, 0.1, 0.8, 0.95] as [number, number, number, number],
    luma: 100,
  };
  const frame = { ...reference, bounds: [0.25, 0.2, 0.75, 0.95] as [number, number, number, number], luma: 80 };
  const view = render(
    <SpeakingMedia
      src="/idle.webm"
      speakingSrc="/talk.webm"
      voiceCharacterName="Mika"
      alt="Mika"
      speakingPresentation={{ from: reference, first: frame, last: frame, to: reference }}
    />,
  );
  Object.defineProperties(view.container, { clientWidth: { value: 200 }, clientHeight: { value: 400 } });
  const [idle, talk] = Array.from(view.container.querySelectorAll("video"));
  fireEvent.loadedData(talk);
  act(() => routeAvatarSpeechEvent("Mika", "started"));
  expect(talk.style.transform).toContain("scale(1.12)");
  expect(talk.style.filter).toBe("brightness(1.18)");
  expect(idle.style.transform).toBe("");
  expect(idle.style.filter).toBe("");
});
