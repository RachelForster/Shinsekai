import { describe, expect, it, vi } from "vitest";

import { SoundPlayer } from "../../../features/chat-stage/audio/soundPlayer";

class FakeAudio {
  currentTime = 0;
  loop = false;
  onended: ((this: GlobalEventHandlers, ev: Event) => unknown) | null = null;
  paused = true;
  preload = "";
  volume = 1;

  constructor(readonly src: string) {}

  pause = vi.fn(() => {
    this.paused = true;
  });

  play = vi.fn(async () => {
    this.paused = false;
  });

  finish() {
    this.paused = true;
    this.onended?.call(this as unknown as GlobalEventHandlers, new Event("ended"));
  }
}

function createHarness() {
  const audio: FakeAudio[] = [];
  const player = new SoundPlayer((url) => {
    const item = new FakeAudio(url);
    audio.push(item);
    return item as unknown as HTMLAudioElement;
  });
  return { audio, player };
}

describe("SoundPlayer", () => {
  it("keeps BGM looping while voice and effects use independent channels", () => {
    const { audio, player } = createHarness();

    player.setBgm("bgm.mp3", 0.4);
    player.playVoice("voice-1.wav");
    player.playVoice("voice-2.wav");
    player.playEffect("impact.wav");
    player.startLoopEffect("rain", "rain.wav");

    expect(audio).toHaveLength(4);
    expect(audio[0]).toMatchObject({ loop: true, src: "bgm.mp3", volume: 0.4 });
    expect(audio[1].src).toBe("voice-1.wav");
    expect(audio[2].src).toBe("impact.wav");
    expect(audio[3]).toMatchObject({ loop: true, src: "rain.wav" });

    audio[1].finish();
    expect(audio).toHaveLength(5);
    expect(audio[4].src).toBe("voice-2.wav");

    player.stopLoopEffect("rain");
    expect(audio[3].pause).toHaveBeenCalledOnce();
  });

  it("reports autoplay blocking and retries active channels after unlock", async () => {
    const { audio, player } = createHarness();
    const lockStates: boolean[] = [];
    player.subscribeLock((locked) => lockStates.push(locked));
    const blocked = Object.assign(new Error("autoplay blocked"), { name: "NotAllowedError" });

    player.setBgm("bgm.mp3");
    audio[0].play.mockRejectedValueOnce(blocked);
    audio[0].paused = true;
    player.setBgm("bgm.mp3");
    await Promise.resolve();
    await Promise.resolve();

    expect(lockStates.at(-1)).toBe(true);
    await player.unlock();
    expect(lockStates.at(-1)).toBe(false);
  });
});
