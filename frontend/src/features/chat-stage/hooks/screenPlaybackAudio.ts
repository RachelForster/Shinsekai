import type { ScreenPlaybackAudioSettings, ScreenPlaybackAudioState } from "../../../shared/platform/types";

export function createScreenPlaybackDetector() {
  let average = 0;
  let audibleSince: number | null = null;
  let quietSince: number | null = null;
  let silentSince: number | null = null;
  let heardPlayback = false;
  let stopped = false;

  return (
    level: number | null,
    now: number,
    lastMotionAt: number,
    settings?: ScreenPlaybackAudioSettings,
  ): ScreenPlaybackAudioState => {
    if (level === null || !settings) {
      average = 0;
      audibleSince = quietSince = silentSince = null;
      heardPlayback = stopped = false;
      return "unavailable";
    }
    silentSince = level < settings.silenceRms ? (silentSince ?? now) : null;
    const audible = level >= Math.max(settings.silenceRms, average * settings.quietRatio);
    if (level >= settings.silenceRms) {
      const weight = audible ? 0.1 : 0.02;
      average = average ? average + (level - average) * weight : level;
    }
    if (audible) {
      audibleSince ??= now;
      heardPlayback ||= now - audibleSince >= settings.minPlaybackMs;
      quietSince = null;
      stopped = false;
      return "playing";
    }
    audibleSince = null;
    quietSince ??= now;
    const quietFor = now - quietSince;
    if (quietFor < settings.quietWindowMs) return "playing";
    if (now - lastMotionAt < settings.pauseStillMs) {
      stopped = false;
    } else if (heardPlayback && silentSince !== null && now - silentSince >= settings.pauseSilenceMs) {
      stopped = true;
      heardPlayback = false;
    }
    return stopped ? "stopped" : "quiet";
  };
}

export function measureAudioLevel(analyser: AnalyserNode, samples: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(samples);
  let energy = 0;
  for (const sample of samples) energy += sample * sample;
  return Math.sqrt(energy / samples.length);
}
