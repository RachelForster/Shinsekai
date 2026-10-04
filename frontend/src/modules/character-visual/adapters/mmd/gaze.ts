import { Space } from "@babylonjs/core/Maths/math.axis";
import { Quaternion } from "@babylonjs/core/Maths/math.vector";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import type { IMmdRuntimeBone } from "babylon-mmd/esm/Runtime/IMmdRuntimeBone";
import type { AvatarAttention } from "../../contracts";

export interface GazeOffset {
  yaw: number;
  pitch: number;
}

const radians = Math.PI / 180;
const neutral = (): GazeOffset => ({ yaw: 0, pitch: 0 });

/** Short, held glances separated by quiet periods, with independent per-avatar timing. */
export class GazeMotion {
  private attention: AvatarAttention = "idle";
  private elapsed = 0;
  private thinkingStart = 0;
  private focusUntil = 0;
  private nextGlance: number;
  private glanceEnd = 0;
  private glance = neutral();
  private thought = neutral();
  private offset = neutral();
  private speechLevel = 0;
  private enabled = true;

  constructor(private readonly random: () => number = Math.random) {
    this.nextGlance = 2 + this.random() * 4;
  }

  setAttention(attention: AvatarAttention) {
    if (this.attention === attention) return;
    if (attention === "thinking") {
      this.thinkingStart = this.elapsed;
      this.thought = {
        yaw: (this.random() < 0.5 ? -1 : 1) * (3 + this.random() * 1.5) * radians,
        pitch: (0.8 + this.random() * 0.8) * radians,
      };
    } else {
      this.focusUntil = this.elapsed + 1.5;
      this.nextGlance = this.focusUntil + 2 + this.random() * 4;
      this.glanceEnd = 0;
    }
    this.attention = attention;
  }

  setSpeechLevel(value: number) {
    this.speechLevel = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
    if (this.speechLevel > 0.02) this.focusUntil = this.elapsed + 0.7;
  }

  sample(deltaSeconds: number, enabled = true): GazeOffset {
    if (!enabled) {
      this.offset = neutral();
      this.thinkingStart = this.elapsed;
      this.glanceEnd = 0;
      if (this.enabled) this.nextGlance = this.elapsed + 2 + this.random() * 4;
      this.enabled = false;
      return neutral();
    }
    this.enabled = true;
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(0.05, deltaSeconds)) : 0;
    this.elapsed += dt;
    let target = neutral();
    if (this.speechLevel > 0.02 || this.attention === "responding" || this.elapsed < this.focusUntil) {
      // Hold attention through pauses between spoken syllables.
    } else if (this.attention === "thinking") {
      const since = this.elapsed - this.thinkingStart;
      // First acknowledge the message. One brief thought, then face the user again,
      // even when a slow request takes much longer than expected.
      if (since >= 0.45 && since < 3.2) target = this.thought;
    } else {
      if (this.elapsed >= this.nextGlance) {
        this.glance = { yaw: (this.random() * 2 - 1) * 1.8 * radians, pitch: (this.random() * 2 - 1) * 0.7 * radians };
        this.glanceEnd = this.elapsed + 0.8 + this.random() * 1.2;
        this.nextGlance = this.glanceEnd + 3 + this.random() * 4;
      }
      if (this.elapsed < this.glanceEnd) target = this.glance;
    }
    const blend = 1 - Math.exp(-dt * 12);
    this.offset.yaw += (target.yaw - this.offset.yaw) * blend;
    this.offset.pitch += (target.pitch - this.offset.pitch) * blend;
    return { ...this.offset };
  }
}

type EyeMetadata = Pick<PmxObject.Bone, "englishName" | "appendTransform">;
const normalize = (name: string) =>
  name
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "");

/** Move the two eye bones together; leave their shared append controller untouched. */
export function createGazePose(bones: readonly IMmdRuntimeBone[], metadata: readonly EyeMetadata[]) {
  const find = (names: string[]) =>
    bones.findIndex((bone, index) =>
      Boolean(
        bone.flag & PmxObject.Bone.Flag.IsRotatable &&
        !(bone.flag & PmxObject.Bone.Flag.HasAxisLimit) &&
        [bone.name, metadata[index]?.englishName ?? ""].some((name) => names.includes(normalize(name))),
      ),
    );
  const left = find(["左目", "lefteye", "eyel", "eye.l"]);
  const right = find(["右目", "righteye", "eyer", "eye.r"]);
  // Missing/restricted pairs cannot safely make a coordinated glance.
  const indices = left >= 0 && right >= 0 && left !== right ? [left, right] : [];
  const protectedIndices = new Set<number>(indices);
  for (const index of indices) {
    let parent = index;
    const visited = new Set<number>();
    while (!visited.has(parent) && bones[parent]?.flag & PmxObject.Bone.Flag.HasAppendRotate) {
      visited.add(parent);
      const append = metadata[parent]?.appendTransform;
      if (!append || !append.ratio || !bones[append.parentIndex]) break;
      parent = append.parentIndex;
      protectedIndices.add(parent);
    }
  }
  const bindings = indices.map((index) => ({
    bone: bones[index],
    base: Quaternion.Identity(),
    delta: Quaternion.Identity(),
    result: Quaternion.Identity(),
  }));
  let applied = false;
  const restore = () => {
    if (!applied) return;
    for (const { bone, base } of bindings) bone.linkedBone.setRotationQuaternion(base, Space.LOCAL);
    applied = false;
  };
  return {
    boneNames: [...protectedIndices].map((index) => bones[index].name),
    apply({ yaw, pitch }: GazeOffset) {
      restore();
      if (!Number.isFinite(yaw) || !Number.isFinite(pitch) || (!yaw && !pitch)) return;
      for (const { bone, base, delta, result } of bindings) {
        base.copyFrom(bone.linkedBone.rotationQuaternion);
        Quaternion.RotationYawPitchRollToRef(yaw, pitch, 0, delta);
        base.multiplyToRef(delta, result);
        bone.linkedBone.setRotationQuaternion(result, Space.LOCAL);
      }
      applied = true;
    },
    restore,
  };
}
