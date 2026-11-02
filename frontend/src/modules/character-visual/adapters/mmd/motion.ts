import { Space } from "@babylonjs/core/Maths/math.axis";
import { Quaternion, Vector3 } from "@babylonjs/core/Maths/math.vector";
import type { Scene } from "@babylonjs/core/scene";
import type { MmdAnimation } from "babylon-mmd/esm/Loader/Animation/mmdAnimation";
import { VpdReader } from "babylon-mmd/esm/Loader/Parser/vpdReader";
import { VpdLoader } from "babylon-mmd/esm/Loader/vpdLoader";
import { VmdLoader } from "babylon-mmd/esm/Loader/vmdLoader";
import { MmdRuntimeModelAnimation } from "babylon-mmd/esm/Runtime/Animation/mmdRuntimeModelAnimation.pure";
import type { IMmdModel } from "babylon-mmd/esm/Runtime/IMmdModel";
import type { ApplyMode } from "../../contracts";

export async function loadMotion(scene: Scene, path: string, data: ArrayBuffer): Promise<MmdAnimation> {
  if (path.toLowerCase().endsWith(".vmd")) return new VmdLoader(scene).loadFromBufferAsync(path, data);
  if (!path.toLowerCase().endsWith(".vpd")) throw new Error("MMD presets require VPD or VMD");
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(data);
  } catch {
    text = new TextDecoder("shift_jis", { fatal: true }).decode(data);
  }
  return new VpdLoader(scene).loadFromVpdObject(path, VpdReader.Parse(text));
}

/** SDK evaluates Bezier/keyframes; this layer only owns timing and cross-pose blending. */
export class MmdMotionPlayer {
  private animation: MmdRuntimeModelAnimation | null = null;
  private elapsed = 0;
  private frame = 0;
  private playing = false;
  private blend = 1;
  private readonly poses;
  private readonly scratchPosition = Vector3.Zero();
  private readonly scratchRotation = Quaternion.Identity();
  private readonly identity = Quaternion.Identity();

  constructor(
    private readonly model: IMmdModel,
    private readonly defaultRotations: ReadonlyMap<string, Quaternion> = new Map(),
  ) {
    this.poses = model.skeleton.bones.map((bone) => ({
      bone,
      rest: Vector3.FromArray(bone.getRestMatrix().m, 12),
      position: bone.position.clone(),
      rotation: bone.rotationQuaternion.clone(),
    }));
  }

  bind(animation: MmdAnimation): MmdRuntimeModelAnimation {
    const bound = MmdRuntimeModelAnimation.Create(animation, this.model);
    if (![...bound.boneBindIndexMap, ...bound.movableBoneBindIndexMap, ...bound.morphBindIndexMap].some(Boolean))
      throw new Error("MMD preset has no tracks matching this model");
    bound.induceMaterialRecompile(true);
    return bound;
  }

  set(animation: MmdRuntimeModelAnimation | null, mode: ApplyMode, smooth: boolean) {
    this.poses.forEach(({ bone, position, rotation }) => {
      position.copyFrom(bone.position);
      rotation.copyFrom(bone.rotationQuaternion);
    });
    this.animation = animation;
    this.elapsed = 0;
    this.playing = mode === "play";
    // A restored snapshot represents the persistent final pose, not a replay.
    this.frame = animation ? (mode === "restore" ? animation.animation.endFrame : animation.animation.startFrame) : 0;
    this.blend = smooth ? 0 : 1;
  }

  get hasPose(): boolean {
    return this.animation !== null || this.blend < 1;
  }

  /** Held VPD/VMD poses can breathe; running clips and crossfades own the body. */
  get isAnimating(): boolean {
    return this.blend < 1 || Boolean(this.animation && this.playing && this.frame < this.animation.animation.endFrame);
  }

  controlsMorph(name: string): boolean {
    return !!name && !!this.animation?.animation.morphTracks.some((track) => track.name === name);
  }

  controlsBone(name: string): boolean {
    const animation = this.animation?.animation;
    return Boolean(
      name &&
      animation &&
      (animation.boneTracks.some((track) => track.name === name) ||
        animation.movableBoneTracks.some((track) => track.name === name)),
    );
  }

  sample(dt: number) {
    const seconds = Number.isFinite(dt) ? Math.max(0, dt) : 0;
    this.elapsed += seconds;
    if (this.animation && this.playing)
      this.frame = Math.min(this.animation.animation.endFrame, this.animation.animation.startFrame + this.elapsed * 30);
    this.poses.forEach(({ bone, rest }) => {
      bone.position.copyFrom(rest);
      bone.setRotationQuaternion(
        this.animation ? this.identity : (this.defaultRotations.get(bone.name) ?? this.identity),
        Space.LOCAL,
      );
    });
    this.model.ikSolverStates.fill(1);
    this.animation?.animate(this.frame);
    if (this.blend < 1) {
      this.blend = Math.min(1, this.blend + seconds / 0.3);
      const weight = this.blend * this.blend * (3 - 2 * this.blend);
      this.poses.forEach(({ bone, position, rotation }) => {
        Vector3.LerpToRef(position, bone.position, weight, this.scratchPosition);
        Quaternion.SlerpToRef(rotation, bone.rotationQuaternion, weight, this.scratchRotation);
        bone.position.copyFrom(this.scratchPosition);
        bone.setRotationQuaternion(this.scratchRotation, Space.LOCAL);
      });
    }
  }
}
