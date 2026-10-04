import { Space } from "@babylonjs/core/Maths/math.axis";
import { Quaternion } from "@babylonjs/core/Maths/math.vector";
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

  constructor(private readonly random: () => number = Math.random) {
    this.initialDelay = this.nextGust = 3 + this.random() * 4;
  }

  sample(deltaSeconds: number, enabled = true): BreezeOffset {
    if (!enabled) {
      // Restart from calm after editing, a preset transition or reduced motion.
      this.elapsed = this.gustStart = this.duration = 0;
      this.nextGust = this.initialDelay;
      return { pitch: 0, roll: 0, phase: 0 };
    }
    const dt = Number.isFinite(deltaSeconds) ? Math.max(0, Math.min(0.05, deltaSeconds)) : 0;
    this.elapsed += dt;
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
    const gust = envelope * this.strength * (0.9 + 0.1 * Math.sin(phase));
    return { pitch: Math.sin(this.direction) * gust, roll: Math.cos(this.direction) * gust, phase };
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

function part(names: string[]): Part | undefined {
  const name = names
    .join(" ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase();
  if (/眉|睫|eyebrow|eyelash|breast|bust|乳|胸/.test(name)) return;
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
  const candidates = bones.flatMap((bone, index) => {
    const flag = PmxObject.Bone.Flag;
    if (!(bone.flag & flag.IsRotatable) || bone.flag & (flag.HasAxisLimit | flag.IsIkEnabled | flag.HasAppendRotate))
      return [];
    const names = [bone.name, metadata[index]?.englishName ?? ""];
    if (
      names.some((name) =>
        anchors.has(
          name
            .trim()
            .toLowerCase()
            .replace(/[\s_]+/g, ""),
        ),
      )
    )
      return [];
    const bodies = bodiesByBone.get(index) ?? [];
    // FollowBone bodies anchor the hair/garment to the character and stay fixed.
    if (bodies.length && bodies.every((body) => body.physicsMode === PmxObject.RigidBody.PhysicsMode.FollowBone))
      return [];
    const kind = part([...names, ...bodies.flatMap((b) => [b.name, b.englishName])]);
    return kind ? [{ bone, kind, index }] : [];
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
  const bindings = chains.map((binding) => ({
    ...binding,
    // Share the angular budget across the chain; long hair must not curl up.
    angle:
      (((binding.kind === "hair" ? 2 : 0.6) * Math.PI) / 180 / lengths.get(binding.root)!) *
      (0.65 + (0.35 * binding.depth) / lengths.get(binding.root)!),
    phase: binding.index * 0.73,
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
    apply({ pitch, roll, phase }: BreezeOffset) {
      restore();
      if (![pitch, roll, phase].every(Number.isFinite) || (!pitch && !roll)) return;
      const x = Math.max(-1, Math.min(1, pitch));
      const z = Math.max(-1, Math.min(1, roll));
      for (const binding of bindings) {
        const { bone, base, delta, result, angle } = binding;
        const response = 0.9 + 0.1 * Math.sin(phase + binding.phase);
        base.copyFrom(bone.linkedBone.rotationQuaternion);
        Quaternion.RotationYawPitchRollToRef(0, x * angle * response, z * angle * response, delta);
        base.multiplyToRef(delta, result);
        bone.linkedBone.setRotationQuaternion(result, Space.LOCAL);
      }
      applied = true;
    },
    restore,
  };
}
