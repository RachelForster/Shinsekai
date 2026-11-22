import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatSoundPlayer } from "../../../features/chat-stage/audio/ChatSoundPlayer";
import type { ChatAudioCommand } from "../../../features/chat-stage/state/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const mocks = vi.hoisted(() => ({
  player: {
    subscribeLock: vi.fn(() => () => {}),
    subscribeVoiceSignal: vi.fn(() => () => {}),
    setBgm: vi.fn(),
    setEffectVolume: vi.fn(),
    setVoicePaused: vi.fn(),
    playVoice: vi.fn(),
    stopVoice: vi.fn(),
    playEffect: vi.fn(),
    startLoopEffect: vi.fn(),
    stopLoopEffect: vi.fn(),
    stopAllLoopEffects: vi.fn(),
    stopAll: vi.fn(),
    dispose: vi.fn(),
  },
}));
vi.mock("../../../features/chat-stage/audio/soundPlayer", () => ({
  SoundPlayer: vi.fn(function () {
    return mocks.player;
  }),
}));
vi.mock("../../../shared/platform/chatRenderer", () => ({ currentChatRendererId: () => "local" }));
vi.mock("../../../features/chat-stage/chatStageUtils", () => ({ stageAssetUrl: (path: string) => path }));

function view(commands: ChatAudioCommand[], paused: boolean) {
  return (
    <I18nProvider language="en">
      <ChatSoundPlayer
        commands={commands}
        voicePaused={paused}
        bgmVolume={0.5}
        effectVolume={0.5}
        onPlaybackSignal={vi.fn()}
      />
    </I18nProvider>
  );
}
const play = (id: string, seq: number): ChatAudioCommand => ({
  kind: "voice-play",
  playbackId: id,
  url: id + ".wav",
  rendererId: "local",
  seq,
  volume: 0.7,
});

describe("shared replay audio", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses normal voice commands and retains playback identity when pausing and resuming", () => {
    const commands: ChatAudioCommand[] = [
      play("old", 1),
      { kind: "voice-stop", playbackId: "old", seq: 2 },
      play("pending", 3),
      { kind: "effect-play", url: "effect.wav", seq: 4 },
    ];
    const result = render(view(commands, true));
    expect(mocks.player.setVoicePaused).toHaveBeenCalledWith(true);
    expect(mocks.player.playVoice).toHaveBeenCalledTimes(2);
    result.rerender(view(commands, false));
    expect(mocks.player.setVoicePaused).toHaveBeenLastCalledWith(false);
    expect(mocks.player.playVoice).toHaveBeenCalledTimes(2);
    expect(mocks.player.playVoice).toHaveBeenCalledWith("pending", "pending.wav", 0.7, undefined);
    expect(mocks.player.playEffect).toHaveBeenCalledTimes(1);
    result.rerender(view(commands, false));
    expect(mocks.player.playVoice).toHaveBeenCalledTimes(2);
  });

  it("still processes a stop while paused without replaying the audio request", () => {
    const commands: ChatAudioCommand[] = [play("pending", 1), { kind: "voice-stop", playbackId: "", seq: 2 }];
    const result = render(view(commands, true));
    result.rerender(view(commands, false));
    expect(mocks.player.stopVoice).toHaveBeenCalledWith("");
    expect(mocks.player.playVoice).toHaveBeenCalledTimes(1);
  });
});
