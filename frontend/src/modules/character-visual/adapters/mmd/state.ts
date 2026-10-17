export interface MmdState {
  morphs: Record<string, number>;
  mouthMorph: string;
  blinkMorph: string;
  camera: MmdCameraState;
  motion?: string;
}

export interface MmdCameraState {
  yaw: number;
  pitch: number;
  zoom: number;
  panX: number;
  panY: number;
}

export const cameraLimits = {
  yaw: { min: -180, max: 180, step: 1 },
  pitch: { min: -80, max: 80, step: 1 },
  zoom: { min: 0.25, max: 4, step: 0.05 },
  panX: { min: -1, max: 1, step: 0.01 },
  panY: { min: -1, max: 1, step: 0.01 },
} satisfies Record<keyof MmdCameraState, { min: number; max: number; step: number }>;

export const defaultCamera = (): MmdCameraState => ({ yaw: 0, pitch: 0, zoom: 1, panX: 0, panY: 0 });

function parseCamera(value: unknown): MmdCameraState {
  // Existing PMX states predate camera controls and use the new eye-level view.
  if (value === undefined) return defaultCamera();
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid MMD camera");
  const input = value as Record<string, unknown>;
  const keys = Object.keys(cameraLimits) as Array<keyof MmdCameraState>;
  if (Object.keys(input).sort().join() !== keys.slice().sort().join()) throw new Error("Invalid MMD camera fields");
  const result = defaultCamera();
  for (const key of keys) {
    const number = input[key];
    const limits = cameraLimits[key];
    if (typeof number !== "number" || !Number.isFinite(number) || number < limits.min || number > limits.max)
      throw new Error(`Invalid MMD camera ${key}`);
    result[key] = number;
  }
  return result;
}

export interface MmdMorphControl {
  name: string;
  englishName: string;
  category: number;
}

export interface MmdControls {
  morphs: MmdMorphControl[];
}

export const neutralState = (mouthMorph = "", blinkMorph = ""): MmdState => ({
  morphs: {},
  mouthMorph,
  blinkMorph,
  camera: defaultCamera(),
});

export function parseState(value: unknown): MmdState {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid MMD state");
  const input = value as Record<string, unknown>;
  if (
    Object.keys(input)
      .filter((key) => key !== "camera" && key !== "motion")
      .sort()
      .join() !== "blinkMorph,morphs,mouthMorph"
  )
    throw new Error("MMD state requires morphs, mouthMorph and blinkMorph");
  if (!input.morphs || typeof input.morphs !== "object" || Array.isArray(input.morphs))
    throw new Error("Invalid MMD morphs");
  const morphs: Record<string, number> = Object.create(null) as Record<string, number>;
  for (const [name, weight] of Object.entries(input.morphs)) {
    if (
      !name ||
      name.length > 200 ||
      typeof weight !== "number" ||
      !Number.isFinite(weight) ||
      weight < 0 ||
      weight > 1
    )
      throw new Error("MMD morph weights must be between 0 and 1");
    morphs[name] = weight;
  }
  if (Object.keys(morphs).length > 512) throw new Error("Too many MMD morphs");
  if (typeof input.mouthMorph !== "string" || typeof input.blinkMorph !== "string")
    throw new Error("Invalid MMD mouth/blink morph");
  const result: MmdState = {
    morphs,
    mouthMorph: input.mouthMorph,
    blinkMorph: input.blinkMorph,
    camera: parseCamera(input.camera),
  };
  if (input.motion !== undefined && typeof input.motion !== "string") throw new Error("Invalid MMD motion path");
  if (input.motion) {
    const motion = input.motion as string;
    if (
      /[:?#%\\\x00-\x1f]/.test(motion) ||
      motion.split("/").some((part) => !part || part === "." || part === "..") ||
      !/\.(vpd|vmd)$/i.test(motion)
    )
      throw new Error("Invalid MMD motion path");
    result.motion = motion;
  }
  return result;
}

export function validateControls(state: MmdState, controls: MmdControls) {
  const known = new Set(controls.morphs.map((item) => item.name));
  for (const name of Object.keys(state.morphs)) if (!known.has(name)) throw new Error(`Unknown MMD morph: ${name}`);
  for (const name of [state.mouthMorph, state.blinkMorph])
    if (name && !known.has(name)) throw new Error(`Unknown MMD mouth/blink morph: ${name}`);
}

/** Close over 100 ms, hold briefly, and reopen over 150 ms. */
export function blinkClosure(elapsedMs: number): number {
  if (elapsedMs < 0) return 0;
  if (elapsedMs < 100) return elapsedMs / 100;
  if (elapsedMs < 150) return 1;
  return Math.max(0, 1 - (elapsedMs - 150) / 150);
}

/** PMX category is an MMD convention; names are only a fallback for custom exports. */
export function detectBindings(morphs: MmdMorphControl[]): Pick<MmdState, "mouthMorph" | "blinkMorph"> {
  const find = (names: string[], category: number) =>
    morphs.find((item) =>
      names.some((name) => item.name.toLowerCase() === name || item.englishName.toLowerCase() === name),
    )?.name ??
    morphs.find((item) => item.category === category)?.name ??
    "";
  return {
    mouthMorph: find(["あ", "口開", "mouth open", "a", "aa"], 3),
    blinkMorph: find(["まばたき", "瞬き", "blink", "eye close"], 2),
  };
}
