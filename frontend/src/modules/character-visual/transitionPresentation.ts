import type { SpriteFramePresentation, SpriteTransitionPresentation } from "../../shared/assets/spriteTransition";

export interface TransitionAdjustment {
  scale: number;
  x: number;
  y: number;
  brightness: number;
}

const neutral: TransitionAdjustment = { scale: 1, x: 0, y: 0, brightness: 1 };
const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(high, value));

function projected(frame: SpriteFramePresentation, aspect: number) {
  const ratio = frame.width / frame.height;
  const height = Math.min(1, aspect / ratio);
  const width = (height * ratio) / aspect;
  const [left, top, right, bottom] = frame.bounds;
  return {
    x: (1 - width) / 2 + (width * (left + right)) / 2,
    y: 1 - height + (height * (top + bottom)) / 2,
    height: height * (bottom - top),
  };
}

function endpoint(
  reference: SpriteFramePresentation,
  frame: SpriteFramePresentation,
  aspect: number,
): TransitionAdjustment {
  const target = projected(reference, aspect);
  const actual = projected(frame, aspect);
  if (!(actual.height > 0)) return neutral;
  const scale = clamp(target.height / actual.height, 0.88, 1.12);
  return {
    scale,
    x: clamp(target.x - (0.5 + (actual.x - 0.5) * scale), -0.08, 0.08),
    y: clamp(target.y - (0.5 + (actual.y - 0.5) * scale), -0.08, 0.08),
    brightness: frame.luma > 8 ? clamp(reference.luma / frame.luma, 0.85, 1.18) : 1,
  };
}

/** Correct the bridge only; preserve each sprite's authored framing and stage highlight. */
export function transitionAdjustment(
  presentation: SpriteTransitionPresentation | undefined,
  progress: number,
  aspect: number,
): TransitionAdjustment {
  if (!presentation || !(aspect > 0)) return neutral;
  const from = endpoint(presentation.from, presentation.first, aspect);
  const to = endpoint(presentation.to, presentation.last, aspect);
  const time = clamp(Number.isFinite(progress) ? progress : 0, 0, 1);
  const mix = (a: number, b: number) => a + (b - a) * time;
  const result = {
    scale: mix(from.scale, to.scale),
    x: mix(from.x, to.x),
    y: mix(from.y, to.y),
    brightness: mix(from.brightness, to.brightness),
  };
  return Object.values(result).every(Number.isFinite) ? result : neutral;
}
