import { defaultCamera, parseCamera, type ModelCamera } from "../../modelCamera";

export const blinkExpressions = ["blink", "blinkLeft", "blinkRight"];
export const pairedBlink = "blinkLeft+blinkRight";

export interface VrmMotionTiming {
  entryStart: number;
  bodyStart: number;
  bodyEnd: number;
  exitEnd: number;
}

export interface VrmState {
  expressions: Record<string, number>;
  bones: Record<string, [number, number, number, number]>;
  motion: string;
  camera: ModelCamera;
  mouthExpression?: string;
  blinkExpression?: string;
  motionTiming?: VrmMotionTiming;
}
export interface VrmControls {
  expressions: string[];
  bones: string[];
}
export const emptyState = (): VrmState => ({ expressions: {}, bones: {}, motion: "", camera: defaultCamera() });
export function parseState(value: unknown): VrmState {
  if (!value || typeof value !== "object") throw new Error("Invalid VRM state");
  const s = value as VrmState;
  if (
    Object.keys(s)
      .filter((key) => !["camera", "mouthExpression", "blinkExpression", "motionTiming"].includes(key))
      .sort()
      .join() !== "bones,expressions,motion" ||
    !s.expressions ||
    !s.bones ||
    Array.isArray(s.expressions) ||
    Array.isArray(s.bones) ||
    typeof s.expressions !== "object" ||
    typeof s.bones !== "object" ||
    typeof s.motion !== "string"
  )
    throw new Error("State requires expressions, bones and motion");
  for (const binding of [s.mouthExpression, s.blinkExpression])
    if (binding !== undefined && (typeof binding !== "string" || binding.length > 200))
      throw new Error("Invalid VRM expression binding");
  if (s.motionTiming !== undefined) {
    const timing = s.motionTiming;
    const keys = ["entryStart", "bodyStart", "bodyEnd", "exitEnd"] as const;
    if (!s.motion || !timing || Object.keys(timing).sort().join() !== [...keys].sort().join())
      throw new Error("Motion timing requires all four boundaries and an animation");
    let previous = 0;
    for (const key of keys) {
      const seconds = timing[key];
      if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < previous)
        throw new Error("Motion boundaries must be finite, non-negative and ordered");
      previous = seconds;
    }
  }
  for (const [name, v] of Object.entries(s.expressions)) {
    if (!name || typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > 1)
      throw new Error("Invalid expression weight");
  }
  for (const [name, q] of Object.entries(s.bones)) {
    if (
      !name ||
      !Array.isArray(q) ||
      q.length !== 4 ||
      q.some((v) => typeof v !== "number" || !Number.isFinite(v)) ||
      Math.abs(q.reduce((sum, v) => sum + v * v, 0) - 1) > 0.01
    )
      throw new Error("Invalid bone quaternion");
  }
  if (
    s.motion &&
    (/[\\:?#%\x00-\x1f\x7f]/.test(s.motion) ||
      s.motion.startsWith("/") ||
      s.motion.split("/").some((part) => part === "" || part === "." || part === "..") ||
      !s.motion.toLowerCase().endsWith(".vrma"))
  )
    throw new Error("Invalid animation path");
  return { ...structuredClone(s), camera: parseCamera(s.camera) };
}
