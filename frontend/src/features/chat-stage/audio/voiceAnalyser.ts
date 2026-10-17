export type MouthListener = (characterName: string, value: number) => void;

/** Only voice passes through this analyser. Silence/transport stalls remove the drive. */
export class VoiceAnalyser {
  private context: AudioContext | null = null;
  private source: MediaElementAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;
  private frame = 0;
  private generation = 0;
  private stopCurrent: (() => void) | null = null;

  constructor(private readonly listener: MouthListener) {}

  start(audio: HTMLAudioElement, characterName: string) {
    this.stop();
    if (!characterName || typeof AudioContext === "undefined") return;
    const generation = ++this.generation;
    try {
      this.context ??= new AudioContext();
      const source = this.context.createMediaElementSource(audio);
      const analyser = this.context.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyser.connect(this.context.destination);
      this.source = source;
      this.analyser = analyser;
      const samples = new Float32Array(analyser.fftSize);
      let smooth = 0;
      let stalled = false;
      const reset = () => {
        stalled = true;
        smooth = 0;
        this.listener(characterName, 0);
      };
      const resume = () => {
        stalled = false;
      };
      for (const type of ["pause", "waiting", "stalled", "ended", "error"]) audio.addEventListener(type, reset);
      audio.addEventListener("playing", resume);
      this.stopCurrent = () => {
        for (const type of ["pause", "waiting", "stalled", "ended", "error"]) audio.removeEventListener(type, reset);
        audio.removeEventListener("playing", resume);
        this.listener(characterName, 0);
      };
      const tick = () => {
        if (generation !== this.generation) return;
        if (!stalled && !audio.paused && !audio.ended && this.context?.state === "running") {
          analyser.getFloatTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
          const target = Math.min(1, Math.max(0, (rms - 0.01) * 8)) * audio.volume;
          smooth += (target - smooth) * (target > smooth ? 0.65 : 0.25);
          this.listener(characterName, smooth);
        } else {
          smooth = 0;
          this.listener(characterName, 0);
        }
        this.frame = requestAnimationFrame(tick);
      };
      void this.context
        .resume()
        .then(() => {
          if (generation === this.generation) tick();
        })
        .catch(() => {
          if (generation === this.generation) this.stop();
        });
    } catch {
      // Unsupported WebAudio must not break normal voice playback.
      this.stop();
    }
  }

  stop() {
    ++this.generation;
    cancelAnimationFrame(this.frame);
    this.stopCurrent?.();
    this.stopCurrent = null;
    this.source?.disconnect();
    this.analyser?.disconnect();
    this.source = null;
    this.analyser = null;
  }

  dispose() {
    this.stop();
    void this.context?.close();
    this.context = null;
  }
}
