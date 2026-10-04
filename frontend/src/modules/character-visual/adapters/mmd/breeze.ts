import { Space } from "@babylonjs/core/Maths/math.axis";
import { Matrix, Quaternion, Vector3 } from "@babylonjs/core/Maths/math.vector";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import type { IMmdRuntimeBone } from "babylon-mmd/esm/Runtime/IMmdRuntimeBone";

interface BreezeOffset {
  pitch: number;
  roll: number;
  phase: number;
}

/** Intermittent gusts with soft starts/ends and a quiet interval between them. */
export class BreezeMotion {
  private elapsed = 0;
  private readonly initialDelay: number;
  private nextGust: number;
  private gustStart = 0;
  private duration = 0;
  private direction = 0;
  private strength = 0;
  private blend = 1;

  constructor(private readonly random: () => number = Math.random) {
    this.initialDelay = this.nextGust = 2 + this.random() * 2;
  }

  sample(deltaSeconds: number, enabled = true, paused = false): BreezeOffset {
    if (!enabled) {
      // Editing and reduced motion restart from calm; temporary transitions only pause.
      this.elapsed = this.gustStart = this.duration = 0;
      this.nextGust = this.initialDelay;
      this.blend = 0;
      return { pitch: 0, roll: 0, phase: 0 };
    }
    if (paused) {
      this.blend = 0;
      return { pitch: 0, roll: 0, phase: this.elapsed * 2.2 };
    }
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(0.05, deltaSeconds)) : 0;
    this.elapsed += dt;
    this.blend += (1 - this.blend) * (1 - Math.exp(-dt * 6));
    if (this.elapsed >= this.nextGust) {
      this.gustStart = this.nextGust;
      this.duration = 4 + this.random() * 3;
      this.direction = this.random() * Math.PI * 2;
      this.strength = 0.65 + this.random() * 0.35;
      this.nextGust = this.gustStart + this.duration + 5 + this.random() * 7;
    }
    const phase = this.elapsed * 2.2;
    const progress = this.duration ? (this.elapsed - this.gustStart) / this.duration : 1;
    if (progress <= 0 || progress >= 1) return { pitch: 0, roll: 0, phase };
    const envelope = Math.sin(Math.PI * progress) ** 2;
    const gust = envelope * this.strength * (0.9 + 0.1 * Math.sin(phase)) * this.blend;
    // Favor lateral wind: purely depthward gusts disappear in the default front view.
    const pitch = Math.sin(this.direction) * 0.45;
    const roll = (Math.cos(this.direction) < 0 ? -1 : 1) * Math.sqrt(1 - pitch * pitch);
    return { pitch: pitch * gust, roll: roll * gust, phase };
  }
}

type Part = "hair" | "cloth";
type BoneName = { name: string; englishName: string };
type RigidBody = Pick<PmxObject.RigidBody, "name" | "englishName" | "boneIndex" | "physicsMode">;
const anchors = new Set([
  "頭",
  "head",
  "頭部",
  "头",
  "头部",
  "首",
  "neck",
  "颈",
  "頸",
  "脖子",
  "上半身",
  "上半身2",
  "上半身２",
  "upperbody",
  "upperbody2",
  "chest",
  "upperchest",
  "胸腔",
  "spine",
  "センター",
  "center",
  "全ての親",
  "root",
  "motherbone",
  "pelvis",
  "hips",
]);

function part(names: string[]): Part | "excluded" | undefined {
  const name = names
    .join(" ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase();
  if (/眉|睫|eyebrow|eyelash|breast|bust|乳|胸/.test(name)) return "excluded";
  if (
    /髪|毛|ツインテール|ポニーテール|もみあげ/.test(name) ||
    /(?:^|[\s_.-])(?:hair|bangs?|ahoge|sideburns?)(?=$|[\s_.\d-])/.test(name)
  )
    return "hair";
  if (
    /スカート|裙|裾|マント|リボン/.test(name) ||
    /(?:^|[\s_.-])(?:skirt|hem|cape|cloak|ribbon)(?=$|[\s_.\d-])/.test(name)
  )
    return "cloth";
}

/** Small additive bone motion; this does not simulate cloth collision or physics. */
export function createBreezePose(
  bones: readonly IMmdRuntimeBone[],
  metadata: readonly BoneName[],
  rigidBodies: readonly RigidBody[],
) {
  const bodiesByBone = new Map<number, RigidBody[]>();
  for (const body of rigidBodies) {
    const bodies = bodiesByBone.get(body.boneIndex) ?? [];
    bodies.push(body);
    bodiesByBone.set(body.boneIndex, bodies);
  }
  const indices = new Map(bones.map((bone, index) => [bone, index]));
  const namesFor = (bone: IMmdRuntimeBone, index: number) => [bone.name, metadata[index]?.englishName ?? ""];
  const isAnchor = (names: string[]) =>
    names.some((name) =>
      anchors.has(
        name
          .trim()
          .toLowerCase()
          .replace(/[\s_]+/g, ""),
      ),
    );
  const kindFor = (bone: IMmdRuntimeBone, index: number) =>
    part([
      ...namesFor(bone, index),
      ...(bodiesByBone.get(index) ?? []).flatMap((body) => [body.name, body.englishName]),
    ]);
  const candidates = bones.flatMap((bone, index) => {
    const flag = PmxObject.Bone.Flag;
    if (!(bone.flag & flag.IsRotatable) || bone.flag & (flag.HasAxisLimit | flag.IsIkEnabled | flag.HasAppendRotate))
      return [];
    if (isAnchor(namesFor(bone, index))) return [];
    const bodies = bodiesByBone.get(index) ?? [];
    // FollowBone bodies anchor the hair/garment to the character and stay fixed.
    if (bodies.length && bodies.every((body) => body.physicsMode === PmxObject.RigidBody.PhysicsMode.FollowBone))
      return [];
    let kind = kindFor(bone, index);
    // Hair tips often have generic names (e.g. サイド/後ろ). Their named hair
    // anchor identifies the chain even when its FollowBone body stays fixed.
    for (let parent = bone.parentBone; !kind && parent; parent = parent.parentBone) {
      const parentIndex = indices.get(parent);
      if (parentIndex === undefined || isAnchor(namesFor(parent, parentIndex))) break;
      kind = kindFor(parent, parentIndex);
    }
    return kind && kind !== "excluded" ? [{ bone, kind, index }] : [];
  });
  const byBone = new Map(candidates.map((binding) => [binding.bone, binding]));
  const chains = candidates.map((binding) => {
    let root = binding.bone;
    let depth = 1;
    for (let parent = root.parentBone; parent; parent = parent.parentBone) {
      if (byBone.get(parent)?.kind === binding.kind) {
        root = parent;
        depth++;
      }
    }
    return { ...binding, root, depth };
  });
  const lengths = new Map<IMmdRuntimeBone, number>();
  for (const binding of chains) lengths.set(binding.root, Math.max(lengths.get(binding.root) ?? 1, binding.depth));
  const positions = bones.map((bone) => Matrix.Invert(bone.linkedBone.getAbsoluteInverseBindMatrix()).getTranslation());
  const head = bones.findIndex((bone, index) =>
    namesFor(bone, index).some((name) => ["頭", "head", "头", "頭部", "头部"].includes(name.trim().toLowerCase())),
  );
  const bodyHeight =
    head > 0
      ? Vector3.Distance(positions[head], positions[0])
      : positions.length
        ? Math.max(...positions.map((p) => p.y)) - Math.min(...positions.map((p) => p.y))
        : 0;
  const bindings = chains.map((binding) => {
    const bangs = /前髪|bang/i.test(namesFor(binding.root, indices.get(binding.root)!).join(" "));
    const budget = binding.kind === "hair" && !bangs ? 8 : 3;
    return {
      ...binding,
      // Share the angular budget across the chain; keep bangs gentler near the face.
      angle:
        ((budget * Math.PI) / 180 / lengths.get(binding.root)!) *
        (0.65 + (0.35 * binding.depth) / lengths.get(binding.root)!),
      // Keep roots pinned, distributing a small, body-scaled sway along the remaining joints.
      travel:
        bangs || binding.depth === 1
          ? 0
          : (bodyHeight * (binding.kind === "hair" ? 0.012 : 0.002)) / (lengths.get(binding.root)! - 1),
      inverseRest: binding.bone.linkedBone.getAbsoluteInverseBindMatrix().clone(),
      position: Vector3.Zero(),
      shift: Vector3.Zero(),
      phase: binding.index * 0.73,
      base: Quaternion.Identity(),
      delta: Quaternion.Identity(),
      result: Quaternion.Identity(),
    };
  });
  let applied = false;
  const restore = () => {
    if (!applied) return;
    for (const { bone, base, position } of bindings) {
      bone.linkedBone.setRotationQuaternion(base, Space.LOCAL);
      bone.linkedBone.position.copyFrom(position);
    }
    applied = false;
  };
  return {
    boneNames: bindings.map(({ bone }) => bone.name),
    apply({ pitch, roll, phase }: BreezeOffset) {
      restore();
      if (![pitch, roll, phase].every(Number.isFinite) || (!pitch && !roll)) return;
      const magnitude = Math.max(1, Math.hypot(pitch, roll));
      const x = pitch / magnitude;
      const z = roll / magnitude;
      for (const binding of bindings) {
        const { bone, base, delta, result, angle, travel, position, shift, inverseRest } = binding;
        const response = 0.82 + 0.18 * Math.sin(phase + binding.phase);
        base.copyFrom(bone.linkedBone.rotationQuaternion);
        position.copyFrom(bone.linkedBone.position);
        Quaternion.RotationYawPitchRollToRef(0, x * angle * response, z * angle * response, delta);
        base.multiplyToRef(delta, result);
        bone.linkedBone.setRotationQuaternion(result, Space.LOCAL);
        shift.set(z * travel * response, 0, -x * travel * response);
        Vector3.TransformNormalToRef(shift, inverseRest, shift);
        bone.linkedBone.position.addInPlace(shift);
      }
      applied = true;
    },
    restore,
  };
}
