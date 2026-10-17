import type { CSSProperties } from "react";

/** Presentation-only framing of a rendered surface, independent of its format. */
export interface VisualFraming {
  /** Fraction of the original height kept visible (1 = full surface). */
  heightRatio: number;
  /** Position within the available crop travel: 0 = top, 1 = bottom. */
  verticalPosition: number;
}

export const visualFramingMinRatio = 0.2;
export const defaultVisualFraming: Readonly<VisualFraming> = Object.freeze({ heightRatio: 1, verticalPosition: 0 });

export function normalizeVisualFraming(value: unknown): VisualFraming {
  const candidate = value && typeof value === "object" ? (value as Partial<VisualFraming>) : {};
  const clamp = (number: unknown, fallback: number, min: number) =>
    typeof number === "number" && Number.isFinite(number) ? Math.min(1, Math.max(min, number)) : fallback;
  return {
    heightRatio: clamp(candidate.heightRatio, 1, visualFramingMinRatio),
    verticalPosition: clamp(candidate.verticalPosition, 0, 0),
  };
}

/** Transform only the inner surface; the host retains layout, animation and hitboxes. */
export function visualFramingStyle(value: unknown): CSSProperties | undefined {
  const { heightRatio, verticalPosition } = normalizeVisualFraming(value);
  if (heightRatio === 1) return undefined;
  const offset = ((1 - heightRatio) * verticalPosition * -100) / heightRatio;
  return { transform: `translateY(${offset}%) scale(${1 / heightRatio})`, transformOrigin: "top center" };
}
