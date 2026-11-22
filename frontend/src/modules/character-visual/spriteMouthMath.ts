import type { MouthPose, SpriteMouthManifest } from "../../shared/assets/spriteMouth";

export type MouthMatrix = [number, number, number, number, number, number];
const identity: MouthMatrix = [1, 0, 0, 1, 0, 0];

export function mouthPose(level: number, previous: MouthPose = "closed", gain = 1): MouthPose {
  const value = Number.isFinite(level) ? Math.max(0, Math.min(1, level * gain)) : 0;
  if (value < 0.045 || (previous === "closed" && value < 0.09)) return "closed";
  if (value >= 0.55 || (previous === "open" && value > 0.35)) return "open";
  return "half";
}

export function mouthMatrixAt(profile: SpriteMouthManifest, seconds: number): MouthMatrix {
  const track = profile.track;
  if (!track.length) return identity;
  const time = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  let low = 0;
  let high = track.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (track[middle].time <= time) low = middle;
    else high = middle - 1;
  }
  const first = track[low];
  const next = track[low + 1];
  if (!next || time <= first.time) return first.matrix;
  const blend = Math.max(0, Math.min(1, (time - first.time) / (next.time - first.time)));
  return first.matrix.map((value, i) => value + (next.matrix[i] - value) * blend) as MouthMatrix;
}

export function multiplyMouthMatrices(a: MouthMatrix, b: MouthMatrix): MouthMatrix {
  return [
    a[0] * b[0] + a[2] * b[1],
    a[1] * b[0] + a[3] * b[1],
    a[0] * b[2] + a[2] * b[3],
    a[1] * b[2] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4],
    a[1] * b[4] + a[3] * b[5] + a[5],
  ];
}

export function mouthPatchMatrix(profile: SpriteMouthManifest, seconds: number): MouthMatrix {
  const [x0, y0, x1, y1] = profile.patchBox;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const change = profile.correction;
  const radians = (change.rotation * Math.PI) / 180;
  const a = Math.cos(radians) * change.scale;
  const b = Math.sin(radians) * change.scale;
  const correction: MouthMatrix = [
    a,
    b,
    -b,
    a,
    cx + change.offsetX - a * cx + b * cy,
    cy + change.offsetY - b * cx - a * cy,
  ];
  return multiplyMouthMatrices(multiplyMouthMatrices(mouthMatrixAt(profile, seconds), correction), [
    1,
    0,
    0,
    1,
    x0,
    y0,
  ]);
}
