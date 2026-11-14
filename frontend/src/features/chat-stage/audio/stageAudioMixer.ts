export interface RecordingAudio {
  track: MediaStreamTrack;
  ready: Promise<void>;
  stop: () => void;
}

/** Keep one Web Audio source per element for playback, lip sync and recording. */
export class StageAudioMixer {
  private context?: AudioContext;
  private output?: GainNode;
  private sources = new WeakMap<HTMLAudioElement, MediaElementAudioSourceNode>();
  private stopRecording?: () => void;

  private getOutput() {
    if (!this.context || !this.output) {
      this.context = new AudioContext();
      this.output = this.context.createGain();
      this.output.connect(this.context.destination);
    }
    return this.output;
  }

  source(audio: HTMLAudioElement) {
    const existing = this.sources.get(audio);
    if (existing) return existing;
    try {
      const output = this.getOutput();
      const context = output.context as AudioContext;
      const source = context.createMediaElementSource(audio);
      source.connect(output);
      this.sources.set(audio, source);
      if (context.state !== "running") void context.resume().catch(() => {});
      return source;
    } catch {
      // Normal media playback can still work in a WebView without Web Audio.
      return undefined;
    }
  }

  get recording() {
    return Boolean(this.stopRecording);
  }

  startRecording(): RecordingAudio {
    if (this.stopRecording) throw new Error("Stage audio is already being recorded");
    const output = this.getOutput();
    const context = output.context as AudioContext;
    const destination = context.createMediaStreamDestination();
    const track = destination.stream.getAudioTracks()[0];
    output.connect(destination);
    const stop = () => {
      if (this.stopRecording !== stop) return;
      this.stopRecording = undefined;
      output.disconnect(destination);
      track.stop();
    };
    this.stopRecording = stop;
    // Resume while the click that opens the share picker still grants activation.
    const ready = context.resume();
    void ready.catch(() => {});
    return { track, ready, stop };
  }

  release(audio: HTMLAudioElement | undefined | null) {
    if (!audio) return;
    this.sources.get(audio)?.disconnect();
    this.sources.delete(audio);
  }

  dispose() {
    this.stopRecording?.();
    if (this.context) void this.context.close().catch(() => {});
  }
}
