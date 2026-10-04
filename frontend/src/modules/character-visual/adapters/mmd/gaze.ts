import { Space } from "@babylonjs/core/Maths/math.axis";
import { Matrix, Quaternion, Vector3 } from "@babylonjs/core/Maths/math.vector";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import type { IMmdRuntimeBone } from "babylon-mmd/esm/Runtime/IMmdRuntimeBone";
import type { AvatarAttention } from "../../contracts";
import type { HeadRotation } from "../../talkingHeadMotion";

export interface GazeOffset {
  yaw: number;
  pitch: number;
}

export interface GazeSample extends GazeOffset {
  head: HeadRotation;
  blink: boolean;
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
  private target = neutral();
  private head = neutral();
  private headTarget = neutral();
  private headStarts = 0;
  private speechLevel = 0;
  private enabled = true;

  constructor(private readonly random: () => number = Math.random) {
    this.nextGlance = 2 + this.random() * 4;
  }

  setAttention(attention: AvatarAttention) {
    if (this.attention === attention) return;
    if (attention === "thinking") {
      this.thinkingStart = this.elapsed;
      this.focusUntil = this.elapsed;
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

  sample(deltaSeconds: number, enabled = true, headEnabled = true): GazeSample {
    if (!enabled) {
      this.offset = neutral();
      this.target = neutral();
      this.head = neutral();
      this.headTarget = neutral();
      this.thinkingStart = this.elapsed;
      this.glanceEnd = 0;
      if (this.enabled) this.nextGlance = this.elapsed + 2 + this.random() * 4;
      this.enabled = false;
      return { ...neutral(), head: { ...neutral(), roll: 0 }, blink: false };
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
        const distant = this.random() < 0.18;
        this.glance = {
          yaw: distant
            ? (this.random() < 0.5 ? -1 : 1) * (3.2 + this.random()) * radians
            : (this.random() * 2 - 1) * 1.8 * radians,
          pitch: (this.random() * 2 - 1) * (distant ? 1.1 : 0.7) * radians,
        };
        this.glanceEnd = this.elapsed + 0.8 + this.random() * 1.2;
        this.nextGlance = this.glanceEnd + 3 + this.random() * 4;
      }
      if (this.elapsed < this.glanceEnd) target = this.glance;
    }
    let blink = false;
    if (target.yaw !== this.target.yaw || target.pitch !== this.target.pitch) {
      const distance = Math.hypot(target.yaw - this.target.yaw, target.pitch - this.target.pitch);
      blink = distance > 2.6 * radians || (distance > radians && this.random() < 0.3);
      this.target = { ...target };
      const follows = Math.hypot(target.yaw, target.pitch) > 2.6 * radians;
      this.headTarget = follows ? { yaw: target.yaw * 0.28, pitch: target.pitch * 0.28 } : neutral();
      this.headStarts = this.elapsed + 0.18 + this.random() * 0.06;
    }
    if (!headEnabled) this.head = neutral();
    else if (this.elapsed >= this.headStarts) {
      const follow = 1 - Math.exp(-dt * 6);
      this.head.yaw += (this.headTarget.yaw - this.head.yaw) * follow;
      this.head.pitch += (this.headTarget.pitch - this.head.pitch) * follow;
    }
    const blend = 1 - Math.exp(-dt * 12);
    this.offset.yaw += (target.yaw - this.offset.yaw) * blend;
    this.offset.pitch += (target.pitch - this.offset.pitch) * blend;
    // Preserve the intended line of sight as the delayed head catches up.
    return {
      yaw: this.offset.yaw - this.head.yaw,
      pitch: this.offset.pitch - this.head.pitch,
      head: { ...this.head, roll: 0 },
      blink,
    };
  }
}

type EyeMetadata = Pick<PmxObject.Bone, "englishName" | "appendTransform">;
const normalize = (name: string) =>
  name
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "");

/** Aim both eyes at one distant point; leave their shared append controller untouched. */
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
    inverseRest: bones[index].linkedBone.getAbsoluteInverseBindMatrix().clone(),
    position: Matrix.Invert(bones[index].linkedBone.getAbsoluteInverseBindMatrix()).getTranslation(),
  }));
  const center = bindings.length ? bindings[0].position.add(bindings[1].position).scale(0.5) : Vector3.Zero();
  const distance = bindings.length
    ? Math.max(0.001, Vector3.Distance(bindings[0].position, bindings[1].position)) * 40
    : 1;
  const target = Vector3.Zero();
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
      if (!Number.isFinite(yaw) || !Number.isFinite(pitch)) return;
      target.set(
        center.x - Math.sin(yaw) * Math.cos(pitch) * distance,
        center.y + Math.sin(pitch) * distance,
        center.z - Math.cos(yaw) * Math.cos(pitch) * distance,
      );
      for (const { bone, base, delta, result, position, inverseRest } of bindings) {
        const direction = Vector3.TransformNormal(target.subtract(position), inverseRest);
        base.copyFrom(bone.linkedBone.rotationQuaternion);
        Quaternion.RotationYawPitchRollToRef(
          Math.atan2(-direction.x, -direction.z),
          Math.atan2(direction.y, Math.hypot(direction.x, direction.z)),
          0,
          delta,
        );
        base.multiplyToRef(delta, result);
        bone.linkedBone.setRotationQuaternion(result, Space.LOCAL);
      }
      applied = true;
    },
    restore,
  };
}
