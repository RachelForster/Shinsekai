export interface L2DState {
  parameters: Record<string, number>;
  expressions: string[];
  motion: string;
}

export function packagePath(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value ||
    value.startsWith("/") ||
    /[:?#%\\\x00-\x1f]/.test(value) ||
    value.split("/").some((part) => part === ".." || part === "." || !part)
  ) {
    throw new Error("Live2D dependency must be a relative package path");
  }
  return value;
}

export function parseState(value: unknown): L2DState {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Live2D state");
  const input = value as Record<string, unknown>;
  if (Object.keys(input).sort().join() !== "expressions,motion,parameters")
    throw new Error("Live2D state requires parameters, expressions, motion");
  if (!input.parameters || typeof input.parameters !== "object" || Array.isArray(input.parameters))
    throw new Error("Invalid parameters");
  const parameters: Record<string, number> = Object.create(null) as Record<string, number>;
  for (const [id, number] of Object.entries(input.parameters)) {
    if (!id || typeof number !== "number" || !Number.isFinite(number))
      throw new Error("Live2D parameters must be finite numbers");
    parameters[id] = number;
  }
  if (!Array.isArray(input.expressions) || new Set(input.expressions).size !== input.expressions.length)
    throw new Error("Invalid expressions");
  const expressions = input.expressions.map((path) => {
    const checked = packagePath(path);
    if (!checked.endsWith(".exp3.json")) throw new Error("Expected .exp3.json");
    return checked;
  });
  if (typeof input.motion !== "string") throw new Error("Invalid motion");
  const motion = input.motion ? packagePath(input.motion) : "";
  if (motion && !motion.endsWith(".motion3.json")) throw new Error("Expected .motion3.json");
  return { parameters, expressions, motion };
}

export const neutralState = (): L2DState => ({ parameters: {}, expressions: [], motion: "" });

export interface L2DControls {
  parameters: Array<{ id: string; min: number; max: number; default: number }>;
  expressions: string[];
  motions: string[];
}

export function validateControls(state: L2DState, controls: L2DControls) {
  for (const [id, value] of Object.entries(state.parameters)) {
    const parameter = controls.parameters.find((item) => item.id === id);
    if (!parameter || value < parameter.min || value > parameter.max)
      throw new Error(`Unknown or out-of-range Live2D parameter: ${id}`);
  }
  if (state.expressions.some((path) => !controls.expressions.includes(path)))
    throw new Error("Unknown Live2D expression");
  if (state.motion && !controls.motions.includes(state.motion)) throw new Error("Unknown Live2D motion");
}
