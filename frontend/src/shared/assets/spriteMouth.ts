/** Portable mouth data. Renderers receive URLs; persistence stores relative PNG paths. */
export type MouthPose = "closed" | "half" | "open";
export interface SpriteMouthCorrection {
  offsetX: number;
  offsetY: number;
  scale: number;
  rotation: number;
  gain: number;
}
export interface SpriteMouthManual {
  mouthBox: [number, number, number, number];
  chin: [number, number];
}
export interface SpriteMouthManifest {
  version: 1;
  width: number;
  height: number;
  fps: number;
  duration: number;
  patchBox: [number, number, number, number];
  mouths: Record<MouthPose, string>;
  track: { time: number; matrix: [number, number, number, number, number, number] }[];
  correction: SpriteMouthCorrection;
  selectedFrames?: Record<MouthPose, number>;
  manual?: SpriteMouthManual | null;
}
