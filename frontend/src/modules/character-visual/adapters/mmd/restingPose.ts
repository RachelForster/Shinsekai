import { Matrix, Quaternion, Vector3 } from "@babylonjs/core/Maths/math.vector";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import type { IMmdRuntimeBone } from "babylon-mmd/esm/Runtime/IMmdRuntimeBone";

const radians = Math.PI / 180;
const normalize = (name: string) =>
  name
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "");
const descendsFrom = (bone: IMmdRuntimeBone, ancestor: IMmdRuntimeBone) => {
  for (let parent = bone.parentBone; parent; parent = parent.parentBone) if (parent === ancestor) return true;
  return false;
};
const position = (bone: IMmdRuntimeBone) =>
  Matrix.Invert(bone.linkedBone.getAbsoluteInverseBindMatrix()).getTranslation();
const between = (from: Vector3, to: Vector3) =>
  Quaternion.FromUnitVectorsToRef(from.normalize(), to.normalize(), Quaternion.Identity());

/** A geometry-scaled, static default for complete arm pairs; authored motions own their original base. */
export function createRestingPose(bones: readonly IMmdRuntimeBone[], metadata: readonly { englishName: string }[]) {
  const find = (names: string[]) =>
    bones.find((bone, index) =>
      Boolean(
        bone.flag & PmxObject.Bone.Flag.IsRotatable &&
        !(bone.flag & PmxObject.Bone.Flag.HasAxisLimit) &&
        [bone.name, metadata[index]?.englishName ?? ""].some((name) => names.includes(normalize(name))),
      ),
    );
  const pairs = [
    {
      side: 1,
      arm: find(["左腕", "leftarm", "arml", "arm.l", "upperarml", "upperarm.l"]),
      elbow: find(["左ひじ", "左肘", "leftelbow", "elbowl", "elbow.l", "forearml", "forearm.l"]),
      wrist: find(["左手首", "左手腕", "leftwrist", "wristl", "wrist.l", "handl", "hand.l"]),
    },
    {
      side: -1,
      arm: find(["右腕", "rightarm", "armr", "arm.r", "upperarmr", "upperarm.r"]),
      elbow: find(["右ひじ", "右肘", "rightelbow", "elbowr", "elbow.r", "forearmr", "forearm.r"]),
      wrist: find(["右手首", "右手腕", "rightwrist", "wristr", "wrist.r", "handr", "hand.r"]),
    },
  ];
  const rotations = new Map<string, Quaternion>();
  if (
    pairs.some(
      ({ arm, elbow, wrist }) => !arm || !elbow || !wrist || !descendsFrom(elbow, arm) || !descendsFrom(wrist, elbow),
    )
  )
    return rotations;
  for (const { side, arm: maybeArm, elbow: maybeElbow, wrist: maybeWrist } of pairs) {
    const arm = maybeArm!,
      elbow = maybeElbow!,
      wrist = maybeWrist!;
    const upper = position(elbow).subtract(position(arm));
    const lower = position(wrist).subtract(position(elbow));
    if (upper.lengthSquared() < 1e-8 || lower.lengthSquared() < 1e-8) return new Map<string, Quaternion>();
    // A little space beside the torso and in front keeps relaxed hands clear of the hips.
    const upperTarget = new Vector3(side * Math.sin(12 * radians), -Math.cos(12 * radians), -0.04).normalize();
    const lowerTarget = new Vector3(
      side * Math.sin(8 * radians),
      -Math.cos(8 * radians),
      -Math.sin(10 * radians),
    ).normalize();
    const upperWorld = between(upper.clone(), upperTarget.clone());
    const armInverse = arm.linkedBone.getAbsoluteInverseBindMatrix();
    rotations.set(
      arm.name,
      between(Vector3.TransformNormal(upper, armInverse), Vector3.TransformNormal(upperTarget, armInverse)),
    );
    const unturnedLower = Vector3.TransformNormal(
      lowerTarget,
      Matrix.FromQuaternionToRef(upperWorld.conjugate(), Matrix.Identity()),
    );
    const elbowInverse = elbow.linkedBone.getAbsoluteInverseBindMatrix();
    rotations.set(
      elbow.name,
      between(Vector3.TransformNormal(lower, elbowInverse), Vector3.TransformNormal(unturnedLower, elbowInverse)),
    );
    const wristAxis = Vector3.TransformNormal(
      new Vector3(0, 0, 1),
      wrist.linkedBone.getAbsoluteInverseBindMatrix(),
    ).normalize();
    rotations.set(wrist.name, Quaternion.RotationAxis(wristAxis, side * 3 * radians));
  }
  return rotations;
}
