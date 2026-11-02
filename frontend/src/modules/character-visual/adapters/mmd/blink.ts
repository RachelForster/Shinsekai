import { blinkClosure } from "./state";

export type BlinkCue = "reply-start" | "sentence-end" | "gaze-shift";

/** A single scheduler merges contextual cues with spontaneous, occasionally varied blinks. */
export class BlinkMotion {
  private enabled = true;
  private nextBlink: number | null = null;
  private pending: number | null = null;
  private start: number | null = null;
  private opening = 150;
  private double = false;
  private cooldownUntil = 0;

  constructor(private readonly random: () => number = Math.random) {}

  request(cue: BlinkCue, now: number) {
    if (!Number.isFinite(now) || !this.enabled || this.start !== null || now < this.cooldownUntil) return;
    // Cues in one frame share a blink instead of queuing a burst of reactions.
    this.pending ??= now + (cue === "gaze-shift" ? 20 : 50) + this.random() * 80;
  }

  sample(now: number, enabled = true, variation = true): number {
    if (!Number.isFinite(now)) return 0;
    if (!enabled) {
      this.pending = this.start = this.nextBlink = null;
      this.enabled = false;
      return 0;
    }
    this.enabled = true;
    this.nextBlink ??= now + 2500 + this.random() * 2000;
    if (
      this.start === null &&
      now >= this.cooldownUntil &&
      (now >= this.nextBlink || (this.pending !== null && now >= this.pending))
    ) {
      this.start = now;
      const kind = variation ? this.random() : 1;
      this.double = kind < 0.12;
      this.opening = kind >= 0.12 && kind < 0.34 ? 280 + this.random() * 100 : 150;
      this.pending = null;
    }
    if (this.start === null) return 0;
    const elapsed = now - this.start;
    const firstDuration = 150 + this.opening;
    const secondStart = firstDuration + 100;
    const duration = this.double ? secondStart + 300 : firstDuration;
    if (elapsed >= duration) {
      this.start = null;
      this.cooldownUntil = now + 1100;
      this.nextBlink = now + 2500 + this.random() * 2000;
      return 0;
    }
    const stroke = this.double && elapsed >= secondStart ? elapsed - secondStart : elapsed;
    const opening = this.double && elapsed >= secondStart ? 150 : this.opening;
    const phase = stroke <= 150 ? stroke : 150 + ((stroke - 150) * 150) / opening;
    const closure = blinkClosure(phase);
    return closure * closure * (3 - 2 * closure);
  }
}
