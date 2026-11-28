export interface ModelCamera {
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
} satisfies Record<keyof ModelCamera, { min: number; max: number; step: number }>;

export const defaultCamera = (): ModelCamera => ({ yaw: 0, pitch: 0, zoom: 1, panX: 0, panY: 0 });

export function parseCamera(value: unknown): ModelCamera {
  if (value === undefined) return defaultCamera();
  const keys = Object.keys(cameraLimits) as Array<keyof ModelCamera>;
  if (!value || typeof value !== "object" || Object.keys(value).sort().join() !== keys.slice().sort().join())
    throw new Error("Invalid model camera fields");
  const result = defaultCamera();
  for (const key of keys) {
    const number = (value as Record<string, unknown>)[key];
    const { min, max } = cameraLimits[key];
    if (typeof number !== "number" || !Number.isFinite(number) || number < min || number > max)
      throw new Error(`Invalid model camera ${key}`);
    result[key] = number;
  }
  return result;
}
