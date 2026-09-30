/** Blend the pre-procedural pose, never the mouth/blink/physics output. */
export class ParameterTransition {
  private displayed: readonly number[] | undefined;
  private from: readonly number[] | undefined;
  private startedAt = 0;

  constructor(private readonly durationMs = 300) {}

  start(animate: boolean, now: number) {
    // Retarget from the last presented frame, including an interrupted blend.
    this.from = animate ? this.displayed?.slice() : undefined;
    this.startedAt = now;
  }

  sample(target: readonly number[], now: number): readonly number[] {
    const progress = this.durationMs > 0 ? Math.min(1, Math.max(0, (now - this.startedAt) / this.durationMs)) : 1;
    const weight = progress * progress * (3 - 2 * progress);
    const from = this.from;
    this.displayed =
      from && progress < 1 ? target.map((value, index) => from[index] + (value - from[index]) * weight) : target;
    if (progress === 1) this.from = undefined;
    return this.displayed;
  }
}
