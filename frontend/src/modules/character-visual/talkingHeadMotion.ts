/** Format-independent, transient local head rotations, in radians. */
export interface HeadRotation {
  pitch: number;
  yaw: number;
  roll: number;
}

const neutral = (): HeadRotation => ({ pitch: 0, yaw: 0, roll: 0 });
const radians = Math.PI / 180;

/** Slow overlapping rhythms, not a nod on every audio sample or syllable. */
export class TalkingHeadMotion {
  private level = 0;
  private strength = 0;
  private elapsed = 0;

  constructor(private readonly phase = Math.random() * Math.PI * 2) {}

  setLevel(value: number) {
    this.level = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
  }

  reset() {
    this.level = this.strength = 0;
  }

  sample(deltaSeconds: number, enabled = true): HeadRotation {
    if (!enabled) {
      this.strength = 0;
      return neutral();
    }
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(0.05, deltaSeconds)) : 0;
    const target = this.level > 0.015 ? 0.45 + this.level * 0.55 : 0;
    const response = target > this.strength ? 0.16 : 0.28;
    this.strength += (target - this.strength) * (1 - Math.exp(-dt / response));
    if (target === 0 && this.strength < 0.001) this.strength = 0;
    if (!this.strength) return neutral();
    this.elapsed += dt;
    const t = this.elapsed;
    const p = this.phase;
    return {
      pitch: (Math.sin(t * 2.1 + p) * 0.7 + Math.sin(t * 4.3 + p * 1.3) * 0.3) * 1.6 * radians * this.strength,
      yaw: (Math.sin(t * 1.4 + p) * 0.75 + Math.sin(t * 2.7 + p * 0.8) * 0.25) * 2.2 * radians * this.strength,
      roll: Math.sin(t * 1.9 + p * 1.1) * 0.8 * radians * this.strength,
    };
  }
}
