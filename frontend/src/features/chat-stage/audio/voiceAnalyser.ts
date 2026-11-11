export type MouthListener = (characterName: string, value: number, instantLevel?: number) => void;

/** Only voice passes through this analyser. Silence/transport stalls remove the drive. */
export class VoiceAnalyser {
  private frame = 0;
  private generation = 0;
  private stopCurrent: (() => void) | null = null;

  constructor(private readonly listener: MouthListener) {}

  start(audio: HTMLAudioElement, characterName: string, source?: MediaElementAudioSourceNode) {
    this.stop();
    if (!characterName || !source) return;
    const generation = ++this.generation;
    try {
      const context = source.context;
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
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
        source.disconnect(analyser);
        this.listener(characterName, 0);
      };
      const tick = () => {
        if (generation !== this.generation) return;
        if (!stalled && !audio.paused && !audio.ended && context.state === "running") {
          analyser.getFloatTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
          const target = Math.min(1, Math.max(0, (rms - 0.01) * 8)) * audio.volume;
          smooth += (target - smooth) * (target > smooth ? 0.65 : 0.25);
          // Keep model-mouth smoothing, but let video cadence see real syllable gaps.
          this.listener(characterName, smooth, target);
        } else {
          smooth = 0;
          this.listener(characterName, 0);
        }
        this.frame = requestAnimationFrame(tick);
      };
      tick();
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
  }
}
