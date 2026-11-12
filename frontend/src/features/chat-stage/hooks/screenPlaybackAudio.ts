import type { ScreenPlaybackAudioState } from "../../../shared/platform/types";

const SILENCE_RMS = 0.003;
const QUIET_WINDOW_MS = 600;
const STOP_WINDOW_MS = 2200;
const STILL_WINDOW_MS = 1200;

export function createScreenPlaybackDetector() {
  let average = 0;
  let audibleSince: number | null = null;
  let quietSince: number | null = null;
  let silentSince: number | null = null;
  let heardPlayback = false;
  let stopped = false;

  return (level: number | null, now: number, lastMotionAt: number): ScreenPlaybackAudioState => {
    if (level === null) {
      average = 0;
      audibleSince = quietSince = silentSince = null;
      heardPlayback = stopped = false;
      return "unavailable";
    }
    silentSince = level < SILENCE_RMS ? (silentSince ?? now) : null;
    const audible = level >= Math.max(SILENCE_RMS, average * 0.35);
    if (level >= SILENCE_RMS) {
      const weight = audible ? 0.1 : 0.02;
      average = average ? average + (level - average) * weight : level;
    }
    if (audible) {
      audibleSince ??= now;
      heardPlayback ||= now - audibleSince >= 300;
      quietSince = null;
      stopped = false;
      return "playing";
    }
    audibleSince = null;
    quietSince ??= now;
    const quietFor = now - quietSince;
    if (quietFor < QUIET_WINDOW_MS) return "playing";
    if (now - lastMotionAt < STILL_WINDOW_MS) {
      stopped = false;
    } else if (heardPlayback && silentSince !== null && now - silentSince >= STOP_WINDOW_MS) {
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
