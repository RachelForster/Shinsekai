import { Space } from "@babylonjs/core/Maths/math.axis";
import { Quaternion } from "@babylonjs/core/Maths/math.vector";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import type { IMmdRuntimeBone } from "babylon-mmd/esm/Runtime/IMmdRuntimeBone";
import type { HeadRotation } from "../../talkingHeadMotion";

type BoneName = { name: string; englishName: string };
const normalize = (name: string) => name.trim().toLowerCase();

/** Temporarily supply local animation inputs to MMD's own morph/IK/append solvers. */
export function createHeadPose(bones: readonly IMmdRuntimeBone[], metadata: readonly BoneName[]) {
  const find = (names: string[]) =>
    bones.find((bone, index) =>
      Boolean(
        bone.flag & PmxObject.Bone.Flag.IsRotatable &&
        !(bone.flag & PmxObject.Bone.Flag.HasAxisLimit) &&
        [bone.name, metadata[index]?.englishName ?? ""].some((name) => names.includes(normalize(name))),
      ),
    );
  const head = find(["頭", "head", "头", "頭部", "头部"]);
  const neck = find(["首", "neck", "颈", "頸", "脖子"]);
  let neckIsParent = false;
  for (let parent = head?.parentBone; parent; parent = parent.parentBone) if (parent === neck) neckIsParent = true;
  const selected = head
    ? neck && neckIsParent
      ? [
          { bone: neck, weight: 0.25 },
          { bone: head, weight: 0.75 },
        ]
      : [{ bone: head, weight: 1 }]
    : neck
      ? [{ bone: neck, weight: 1 }]
      : [];
  const bindings = selected.map((binding) => ({
    ...binding,
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
    apply({ pitch, yaw, roll }: HeadRotation) {
      restore();
      if (!pitch && !yaw && !roll) return;
      for (const { bone, weight, base, delta, result } of bindings) {
        base.copyFrom(bone.linkedBone.rotationQuaternion);
        Quaternion.RotationYawPitchRollToRef(yaw * weight, pitch * weight, roll * weight, delta);
        base.multiplyToRef(delta, result);
        bone.linkedBone.setRotationQuaternion(result, Space.LOCAL);
      }
      applied = true;
    },
    restore,
  };
}
