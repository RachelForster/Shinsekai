import { VoiceAnalyser, type MouthListener } from "./voiceAnalyser";
import { StageAudioMixer } from "./stageAudioMixer";

export type SoundPlayerLockListener = (locked: boolean) => void;
export type VoicePlaybackState = "started" | "finished" | "interrupted" | "failed";
export interface VoicePlaybackSignal {
  error?: string;
  playbackId: string;
  state: VoicePlaybackState;
}
export type VoicePlaybackSignalListener = (signal: VoicePlaybackSignal) => void;

type AudioFactory = (url: string, cors: boolean) => HTMLAudioElement;
type QueuedVoice = { playbackId: string; url: string; volume: number; characterName: string };
type ActiveVoice = QueuedVoice & { audio: HTMLAudioElement; started: boolean };

function clampVolume(value: number) {
  return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 1));
}

function canMixStageAsset(url: string) {
  try {
    const asset = new URL(url, window.location.href);
    const localBridge = asset.pathname === "/api/media" && /^(127\.0\.0\.1|localhost|\[::1\])$/i.test(asset.hostname);
    return (
      asset.origin === window.location.origin || asset.protocol === "data:" || asset.protocol === "blob:" || localBridge
    );
  } catch {
    return false;
  }
}

function createStageAudio(url: string, cors: boolean) {
  const audio = new Audio();
  if (cors) audio.crossOrigin = "anonymous";
  audio.src = url;
  return audio;
}

function voiceRequestUrl(url: string, playbackId: string) {
  if (playbackId) {
    try {
      const request = new URL(url, window.location.href);
      if (["http:", "https:"].includes(request.protocol) && request.pathname === "/api/media") {
        // TTS reuses disk slots; each playback must bypass earlier cached bytes.
        request.searchParams.set("playbackId", playbackId);
        return request.toString();
      }
    } catch {
      // Leave invalid URLs to the audio element's normal failure handling.
    }
  }
  return url;
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
  private readonly analyser: VoiceAnalyser | null;
  private readonly mixer = new StageAudioMixer();
  private readonly mixable = new WeakSet<HTMLAudioElement>();
  private bgm: HTMLAudioElement | null = null;
  private bgmUrl = "";
  private currentVoice: ActiveVoice | null = null;
  private voicePaused = false;
  private effectVolume = 1;
  private readonly effectPlayers = new Set<HTMLAudioElement>();
  private readonly listeners = new Set<SoundPlayerLockListener>();
  private locked = false;
  private readonly loopPlayers = new Map<string, HTMLAudioElement>();
  private readonly voiceQueue: QueuedVoice[] = [];
  private readonly voiceSignalListeners = new Set<VoicePlaybackSignalListener>();

  constructor(
    createAudio: AudioFactory = createStageAudio,
    onMouth?: MouthListener,
    private readonly onVoiceBoundary?: (characterName: string, state: "started" | "finished" | "interrupted") => void,
  ) {
    this.createAudio = createAudio;
    this.analyser = onMouth ? new VoiceAnalyser(onMouth) : null;
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
      this.releaseAudio(this.bgm);
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
    this.releaseAudio(this.bgm);
    const audio = this.createChannelAudio(nextUrl);
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

  setEffectVolume(volume: number) {
    this.effectVolume = clampVolume(volume);
    for (const audio of [...this.effectPlayers, ...this.loopPlayers.values()]) {
      audio.volume = this.effectVolume;
    }
  }

  playVoice(playbackId: string, url: string, volume = 1, characterName = "") {
    const nextUrl = url.trim();
    if (!nextUrl) {
      return;
    }
    if (this.currentVoice) {
      this.voiceQueue.push({
        playbackId: playbackId.trim(),
        url: nextUrl,
        volume: clampVolume(volume),
        characterName,
      });
      return;
    }
    this.startVoice({
      playbackId: playbackId.trim(),
      url: nextUrl,
      volume: clampVolume(volume),
      characterName,
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
    if (this.currentVoice?.started) this.onVoiceBoundary?.(this.currentVoice.characterName, "interrupted");
    this.analyser?.stop();
    this.releaseAudio(this.currentVoice?.audio);
    this.currentVoice = null;
  }

  setVoicePaused(paused: boolean) {
    this.voicePaused = paused;
    const voice = this.currentVoice;
    if (!voice) return;
    if (paused) {
      voice.audio.pause();
      this.analyser?.stop();
    } else {
      this.requestPlay(
        voice.audio,
        () => {
          if (this.voicePaused) {
            voice.audio.pause();
            return;
          }
          if (voice.started) this.analyseVoice(voice);
          else this.markVoiceStarted(voice);
        },
        (error) => this.finishVoice(voice, "failed", String(error)),
      );
    }
  }

  playEffect(url: string) {
    const nextUrl = url.trim();
    if (!nextUrl) {
      return;
    }
    const audio = this.createChannelAudio(nextUrl);
    audio.preload = "auto";
    audio.volume = this.effectVolume;
    this.effectPlayers.add(audio);
    const release = () => {
      this.effectPlayers.delete(audio);
      this.mixer.release(audio);
    };
    audio.onended = release;
    audio.onerror = release;
    this.requestPlay(audio);
  }

  startLoopEffect(key: string, url: string) {
    const nextKey = key.trim();
    const nextUrl = url.trim();
    if (!nextKey || !nextUrl) {
      return;
    }
    this.stopLoopEffect(nextKey);
    const audio = this.createChannelAudio(nextUrl);
    audio.loop = true;
    audio.preload = "auto";
    audio.volume = this.effectVolume;
    this.loopPlayers.set(nextKey, audio);
    this.requestPlay(audio);
  }

  stopLoopEffect(key: string) {
    const audio = this.loopPlayers.get(key);
    if (!audio) {
      return;
    }
    this.releaseAudio(audio);
    this.loopPlayers.delete(key);
  }

  stopAllLoopEffects() {
    for (const audio of this.loopPlayers.values()) {
      this.releaseAudio(audio);
    }
    this.loopPlayers.clear();
  }

  stopAll() {
    this.releaseAudio(this.bgm);
    this.bgm = null;
    this.bgmUrl = "";
    this.stopVoice();
    for (const audio of this.effectPlayers) {
      this.releaseAudio(audio);
    }
    this.effectPlayers.clear();
    this.stopAllLoopEffects();
  }

  recordAudio() {
    const recording = this.mixer.startRecording();
    for (const audio of [this.bgm, this.currentVoice?.audio, ...this.effectPlayers, ...this.loopPlayers.values()]) {
      this.routeRecordingAudio(audio);
    }
    return recording;
  }

  async unlock() {
    const active = [
      this.bgm,
      this.voicePaused ? null : this.currentVoice?.audio,
      ...this.effectPlayers,
      ...this.loopPlayers.values(),
    ].filter((audio): audio is HTMLAudioElement => Boolean(audio?.paused));
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
    this.mixer.dispose();
    this.listeners.clear();
    this.voiceSignalListeners.clear();
  }

  private startVoice(voice: QueuedVoice) {
    const audio = this.createChannelAudio(voiceRequestUrl(voice.url, voice.playbackId), true);
    audio.preload = "auto";
    audio.volume = voice.volume;
    const activeVoice: ActiveVoice = { ...voice, audio, started: false };
    this.currentVoice = activeVoice;
    audio.onended = () => this.finishVoice(activeVoice, "finished");
    audio.onerror = () => this.finishVoice(activeVoice, "failed", "audio playback failed");
    if (this.voicePaused) return;
    this.requestPlay(
      audio,
      () => {
        if (this.voicePaused) {
          audio.pause();
          return;
        }
        this.markVoiceStarted(activeVoice);
      },
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
      if (this.mixer.recording) this.routeRecordingAudio(audio);
      return Promise.resolve(audio.play());
    } catch (error) {
      return Promise.reject(error);
    }
  }

  private createChannelAudio(url: string, voice = false) {
    const cors = voice || canMixStageAsset(url);
    const audio = this.createAudio(url, cors);
    if (cors) this.mixable.add(audio);
    return audio;
  }

  private routeRecordingAudio(audio: HTMLAudioElement | undefined | null) {
    if (audio && this.mixable.has(audio)) this.mixer.source(audio);
  }

  private releaseAudio(audio: HTMLAudioElement | undefined | null) {
    stopAudio(audio);
    this.mixer.release(audio);
  }

  private analyseVoice(voice: ActiveVoice) {
    if (this.analyser && voice.characterName) {
      this.analyser.start(voice.audio, voice.characterName, this.mixer.source(voice.audio));
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
    this.analyseVoice(voice);
    this.onVoiceBoundary?.(voice.characterName, "started");
    this.emitVoiceSignal(voice.playbackId, "started");
  }

  private finishVoice(voice: ActiveVoice, state: "finished" | "failed", error = "") {
    if (this.currentVoice !== voice) {
      return;
    }
    this.currentVoice = null;
    this.analyser?.stop();
    this.mixer.release(voice.audio);
    if (voice.started) this.onVoiceBoundary?.(voice.characterName, state === "finished" ? "finished" : "interrupted");
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
