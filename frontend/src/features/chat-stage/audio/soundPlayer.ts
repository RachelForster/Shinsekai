export type SoundPlayerLockListener = (locked: boolean) => void;
export type VoicePlaybackState = "started" | "finished" | "interrupted" | "failed";
export interface VoicePlaybackSignal {
  error?: string;
  playbackId: string;
  state: VoicePlaybackState;
}
export type VoicePlaybackSignalListener = (signal: VoicePlaybackSignal) => void;

type AudioFactory = (url: string) => HTMLAudioElement;
type QueuedVoice = { playbackId: string; url: string; volume: number };
type ActiveVoice = QueuedVoice & { audio: HTMLAudioElement; started: boolean };

function clampVolume(value: number) {
  return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 1));
}

function isAutoplayBlock(error: unknown) {
  return error instanceof DOMException
    ? error.name === "NotAllowedError"
    : typeof error === "object" &&
        error !== null &&
        "name" in error &&
        (error as { name?: unknown }).name === "NotAllowedError";
}

function stopAudio(audio: HTMLAudioElement | null | undefined) {
  if (!audio) {
    return;
  }
  audio.pause();
  try {
    audio.currentTime = 0;
  } catch {
    // Some WebViews reject seeks before metadata has loaded.
  }
}

export class SoundPlayer {
  private readonly createAudio: AudioFactory;
  private bgm: HTMLAudioElement | null = null;
  private bgmUrl = "";
  private currentVoice: ActiveVoice | null = null;
  private readonly effectPlayers = new Set<HTMLAudioElement>();
  private readonly listeners = new Set<SoundPlayerLockListener>();
  private locked = false;
  private readonly loopPlayers = new Map<string, HTMLAudioElement>();
  private readonly voiceQueue: QueuedVoice[] = [];
  private readonly voiceSignalListeners = new Set<VoicePlaybackSignalListener>();

  constructor(createAudio: AudioFactory = (url) => new Audio(url)) {
    this.createAudio = createAudio;
  }

  subscribeLock(listener: SoundPlayerLockListener) {
    this.listeners.add(listener);
    listener(this.locked);
    return () => {
      this.listeners.delete(listener);
    };
  }

  subscribeVoiceSignal(listener: VoicePlaybackSignalListener) {
    this.voiceSignalListeners.add(listener);
    return () => {
      this.voiceSignalListeners.delete(listener);
    };
  }

  setBgm(url: string, volume = 1) {
    const nextUrl = url.trim();
    if (!nextUrl) {
      stopAudio(this.bgm);
      this.bgm = null;
      this.bgmUrl = "";
      return;
    }
    if (this.bgm && this.bgmUrl === nextUrl) {
      this.bgm.volume = clampVolume(volume);
      if (this.bgm.paused) {
        this.requestPlay(this.bgm);
      }
      return;
    }
    stopAudio(this.bgm);
    const audio = this.createAudio(nextUrl);
    audio.loop = true;
    audio.preload = "auto";
    audio.volume = clampVolume(volume);
    this.bgm = audio;
    this.bgmUrl = nextUrl;
    this.requestPlay(audio);
  }

  setBgmVolume(volume: number) {
    if (this.bgm) {
      this.bgm.volume = clampVolume(volume);
    }
  }

  playVoice(playbackId: string, url: string, volume = 1) {
    const nextUrl = url.trim();
    if (!nextUrl) {
      return;
    }
    if (this.currentVoice) {
      this.voiceQueue.push({
        playbackId: playbackId.trim(),
        url: nextUrl,
        volume: clampVolume(volume),
      });
      return;
    }
    this.startVoice({
      playbackId: playbackId.trim(),
      url: nextUrl,
      volume: clampVolume(volume),
    });
  }

  stopVoice(playbackId = "") {
    const targetId = playbackId.trim();
    if (targetId && this.currentVoice?.playbackId !== targetId) {
      const queuedIndex = this.voiceQueue.findIndex((voice) => voice.playbackId === targetId);
      if (queuedIndex >= 0) {
        this.voiceQueue.splice(queuedIndex, 1);
      }
      return;
    }
    this.voiceQueue.length = 0;
    stopAudio(this.currentVoice?.audio);
    this.currentVoice = null;
  }

  playEffect(url: string) {
    const nextUrl = url.trim();
    if (!nextUrl) {
      return;
    }
    const audio = this.createAudio(nextUrl);
    audio.preload = "auto";
    this.effectPlayers.add(audio);
    audio.onended = () => this.effectPlayers.delete(audio);
    this.requestPlay(audio);
  }

  startLoopEffect(key: string, url: string) {
    const nextKey = key.trim();
    const nextUrl = url.trim();
    if (!nextKey || !nextUrl) {
      return;
    }
    this.stopLoopEffect(nextKey);
    const audio = this.createAudio(nextUrl);
    audio.loop = true;
    audio.preload = "auto";
    this.loopPlayers.set(nextKey, audio);
    this.requestPlay(audio);
  }

  stopLoopEffect(key: string) {
    const audio = this.loopPlayers.get(key);
    if (!audio) {
      return;
    }
    stopAudio(audio);
    this.loopPlayers.delete(key);
  }

  stopAllLoopEffects() {
    for (const audio of this.loopPlayers.values()) {
      stopAudio(audio);
    }
    this.loopPlayers.clear();
  }

  stopAll() {
    stopAudio(this.bgm);
    this.bgm = null;
    this.bgmUrl = "";
    this.stopVoice();
    for (const audio of this.effectPlayers) {
      stopAudio(audio);
    }
    this.effectPlayers.clear();
    this.stopAllLoopEffects();
  }

  async unlock() {
    const active = [this.bgm, this.currentVoice?.audio, ...this.effectPlayers, ...this.loopPlayers.values()].filter(
      (audio): audio is HTMLAudioElement => Boolean(audio?.paused),
    );
    const results = await Promise.allSettled(
      active.map(async (audio) => {
        await this.play(audio);
        if (this.currentVoice?.audio === audio) {
          this.markVoiceStarted(this.currentVoice);
        }
      }),
    );
    this.setLocked(results.some((result) => result.status === "rejected" && isAutoplayBlock(result.reason)));
  }

  dispose() {
    this.stopAll();
    this.listeners.clear();
    this.voiceSignalListeners.clear();
  }

  private startVoice(voice: QueuedVoice) {
    const audio = this.createAudio(voice.url);
    audio.preload = "auto";
    audio.volume = voice.volume;
    const activeVoice: ActiveVoice = { ...voice, audio, started: false };
    this.currentVoice = activeVoice;
    audio.onended = () => this.finishVoice(activeVoice, "finished");
    audio.onerror = () => this.finishVoice(activeVoice, "failed", "audio playback failed");
    this.requestPlay(
      audio,
      () => this.markVoiceStarted(activeVoice),
      (error) => this.finishVoice(activeVoice, "failed", String(error)),
    );
  }

  private requestPlay(audio: HTMLAudioElement, onStarted?: () => void, onFailed?: (error: unknown) => void) {
    void this.play(audio)
      .then(() => {
        this.setLocked(false);
        onStarted?.();
      })
      .catch((error) => {
        if (isAutoplayBlock(error)) {
          this.setLocked(true);
          return;
        }
        onFailed?.(error);
      });
  }

  private play(audio: HTMLAudioElement) {
    try {
      return Promise.resolve(audio.play());
    } catch (error) {
      return Promise.reject(error);
    }
  }

  private setLocked(locked: boolean) {
    if (this.locked === locked) {
      return;
    }
    this.locked = locked;
    for (const listener of this.listeners) {
      listener(locked);
    }
  }

  private markVoiceStarted(voice: ActiveVoice) {
    if (this.currentVoice !== voice || voice.started) {
      return;
    }
    voice.started = true;
    this.emitVoiceSignal(voice.playbackId, "started");
  }

  private finishVoice(voice: ActiveVoice, state: "finished" | "failed", error = "") {
    if (this.currentVoice !== voice) {
      return;
    }
    this.currentVoice = null;
    this.emitVoiceSignal(voice.playbackId, state, error);
    const next = this.voiceQueue.shift();
    if (next) {
      this.startVoice(next);
    }
  }

  private emitVoiceSignal(playbackId: string, state: VoicePlaybackState, error = "") {
    if (!playbackId) {
      return;
    }
    const signal: VoicePlaybackSignal = {
      playbackId,
      state,
      ...(error ? { error } : {}),
    };
    for (const listener of this.voiceSignalListeners) {
      listener(signal);
    }
  }
}
