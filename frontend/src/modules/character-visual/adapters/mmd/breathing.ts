import { Space } from "@babylonjs/core/Maths/math.axis";
import { Quaternion } from "@babylonjs/core/Maths/math.vector";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import type { IMmdRuntimeBone } from "babylon-mmd/esm/Runtime/IMmdRuntimeBone";
import type { HeadRotation } from "../../talkingHeadMotion";

interface BreathingOffset {
  chestPitch: number;
  head: HeadRotation;
}

const radians = Math.PI / 180;
const neutral = (): BreathingOffset => ({ chestPitch: 0, head: { pitch: 0, yaw: 0, roll: 0 } });

/** A soft inhale and a longer exhale, with slight variation between breaths. */
function breathWave(cycle: number): number {
  const phase = ((cycle % 1) + 1) % 1;
  return phase < 0.42
    ? (1 - Math.cos((Math.PI * phase) / 0.42)) / 2
    : (1 + Math.cos((Math.PI * (phase - 0.42)) / 0.58)) / 2;
}

export class BreathingMotion {
  private elapsed = 0;
  private strength = 0;

  constructor(private readonly phase = Math.random() * Math.PI * 2) {}

  sample(deltaSeconds: number, enabled = true): BreathingOffset {
    if (!enabled) {
      this.strength = 0;
      return neutral();
    }
    // A suspended window resumes from its last breath instead of jumping ahead.
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(0.05, deltaSeconds)) : 0;
    this.elapsed += dt;
    this.strength += (1 - this.strength) * (1 - Math.exp(-dt / 0.7));
    if (!this.strength) return neutral();
    const t = this.elapsed;
    const cycle = t / 4.8 + this.phase / (Math.PI * 2) + 0.018 * Math.sin(t * 0.3 + this.phase);
    const amplitude = this.strength * (0.9 + 0.1 * Math.sin(t * 0.23 + this.phase));
    const chest = breathWave(cycle) * amplitude;
    const head = breathWave(cycle - 0.035) * amplitude;
    return {
      chestPitch: -0.6 * radians * chest,
      head: {
        // Partially compensate for the inherited chest tilt; the head follows gently.
        pitch: 0.24 * radians * head,
        yaw: 0,
        roll: Math.sin(t * 0.45 + this.phase) * 0.04 * radians * head,
      },
    };
  }
}

/** Animate the upper torso without scaling the mesh or driving breast physics bones. */
export function createBreathingPose(
  bones: readonly IMmdRuntimeBone[],
  metadata: readonly { name: string; englishName: string }[],
) {
  const normalize = (name: string) =>
    name
      .trim()
      .toLowerCase()
      .replace(/[\s_]+/g, "");
  const find = (names: string[]) =>
    bones.find((bone, index) =>
      Boolean(
        bone.flag & PmxObject.Bone.Flag.IsRotatable &&
        !(bone.flag & PmxObject.Bone.Flag.HasAxisLimit) &&
        [bone.name, metadata[index]?.englishName ?? ""].some((name) => names.includes(normalize(name))),
      ),
    );
  // Prefer the chest joint over the lower spine, regardless of PMX bone order.
  const chest =
    find(["上半身2", "上半身２", "upperbody2", "chest", "upperchest", "胸腔"]) ??
    find(["上半身", "upperbody", "spine"]);
  const base = Quaternion.Identity();
  const delta = Quaternion.Identity();
  const result = Quaternion.Identity();
  let applied = false;
  const restore = () => {
    if (!applied || !chest) return;
    chest.linkedBone.setRotationQuaternion(base, Space.LOCAL);
    applied = false;
  };
  return {
    apply(pitch: number) {
      restore();
      if (!chest || !Number.isFinite(pitch) || !pitch) return;
      base.copyFrom(chest.linkedBone.rotationQuaternion);
      Quaternion.RotationYawPitchRollToRef(0, pitch, 0, delta);
      base.multiplyToRef(delta, result);
      chest.linkedBone.setRotationQuaternion(result, Space.LOCAL);
      applied = true;
    },
    restore,
  };
}
