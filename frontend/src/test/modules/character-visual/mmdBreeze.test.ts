import { afterEach, describe, expect, it } from "vitest";
import { Bone } from "@babylonjs/core/Bones/bone";
import { Skeleton } from "@babylonjs/core/Bones/skeleton";
import { NullEngine } from "@babylonjs/core/Engines/nullEngine";
import { Matrix, Quaternion } from "@babylonjs/core/Maths/math.vector";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { Scene } from "@babylonjs/core/scene";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import type { MmdSkinnedMesh } from "babylon-mmd/esm/Runtime/mmdMesh";
import { BreezeMotion, createBreezePose } from "../../../modules/character-visual/adapters/mmd/breeze";

const flag = PmxObject.Bone.Flag;
const gust = { pitch: 0.7, roll: 0.6, phase: 1 };
const calm = { pitch: 0, roll: 0, phase: 0 };
let engine: NullEngine;

function setup(hairFlag = flag.IsRotatable, namesOverride: Record<number, string> = {}) {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const root = new Mesh("model", scene);
  const skeleton = new Skeleton("rig", "rig", scene);
  const names = ["head", "髪固定", "前髪1", "前髪2", "前髪3", "スカート", "袖", "胸", "眉毛"].map(
    (name, index) => namesOverride[index] ?? name,
  );
  const parents = [-1, 0, 1, 2, 3, 0, 0, 0, 0];
  const linked: Bone[] = [];
  const metadata = names.map((name, i) => ({
    name,
    englishName: "",
    parentBoneIndex: parents[i],
    transformOrder: i,
    flag: i === 2 ? hairFlag : flag.IsRotatable,
  }));
  for (let i = 0; i < names.length; i++)
    linked.push(new Bone(names[i], skeleton, linked[parents[i]] ?? null, Matrix.Translation(0, i ? -1 : 10, 0)));
  root.skeleton = skeleton;
  root.metadata = {
    isMmdModel: true,
    header: {},
    skeleton,
    bones: metadata,
    morphs: [],
    meshes: [root],
    materials: [],
    rigidBodies: [],
    joints: [],
  };
  const runtime = new MmdRuntime(scene, null);
  const model = runtime.createMmdModel(root as MmdSkinnedMesh, { buildPhysics: false, materialProxyConstructor: null });
  const bodies = [
    { name: "hair anchor", englishName: "", boneIndex: 1, physicsMode: PmxObject.RigidBody.PhysicsMode.FollowBone },
  ];
  return { root, model, runtime, linked, metadata, bodies };
}

afterEach(() => engine?.dispose());

describe("MMD intermittent breeze", () => {
  it("starts calm, produces smooth bounded gusts and leaves quiet intervals", () => {
    const motion = new BreezeMotion(() => 0);
    const samples = Array.from({ length: 1200 }, () => motion.sample(1 / 60));
    expect(samples.slice(0, 175).every((s) => s.pitch === 0 && s.roll === 0)).toBe(true);
    expect(samples.slice(200, 400).some((s) => s.roll > 0.4)).toBe(true);
    expect(samples.slice(450, 650).every((s) => s.pitch === 0 && s.roll === 0)).toBe(true);
    expect(samples.slice(750, 950).some((s) => s.roll > 0.4)).toBe(true);
    let previous = calm;
    for (const sample of samples) {
      expect(Math.hypot(sample.pitch, sample.roll)).toBeLessThanOrEqual(1);
      expect(Math.abs(sample.roll - previous.roll)).toBeLessThan(0.015);
      previous = sample;
    }
  });

  it("keeps timing at different frame rates and only randomizes at gust boundaries", () => {
    const run = (fps: number) => {
      let calls = 0;
      const motion = new BreezeMotion(() => {
        calls++;
        return 0.2;
      });
      let result = calm;
      for (let i = 0; i < fps * 6; i++) result = motion.sample(1 / fps);
      return { result, calls };
    };
    const a = run(30);
    const b = run(120);
    expect(a.result.pitch).toBeCloseTo(b.result.pitch, 10);
    expect(a.result.roll).toBeCloseTo(b.result.roll, 10);
    expect(a.calls).toBe(5);
    expect(b.calls).toBe(5);
  });

  it("pauses for editing/actions/reduced motion and restarts from calm without a time jump", () => {
    const motion = new BreezeMotion(() => 0);
    for (let i = 0; i < 300; i++) motion.sample(1 / 60);
    expect(motion.sample(0.05, false)).toEqual(calm);
    for (let i = 0; i < 100; i++) expect(motion.sample(1 / 60).roll).toBe(0);
    expect(new BreezeMotion(() => 0).sample(100)).toEqual(new BreezeMotion(() => 0).sample(0.05));
    for (const dt of [NaN, Infinity, -1]) expect(new BreezeMotion(() => 0).sample(dt)).toEqual(calm);
  });

  it.each([flag.IsRotatable, flag.IsRotatable | flag.TransformAfterPhysics])(
    "feeds both MMD solver stages and restores the authored hair/garment pose (%s)",
    (hairFlag) => {
      const { root, model, runtime, linked, metadata, bodies } = setup(hairFlag);
      const pose = createBreezePose(model.runtimeBones, metadata, bodies);
      const base = Quaternion.RotationYawPitchRoll(0.1, -0.2, 0.05);
      linked[2].rotationQuaternion = base.clone();
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      const originalHair = Array.from(model.runtimeBones[2].worldMatrix);
      const originalSkirt = Array.from(model.runtimeBones[5].worldMatrix);
      for (let i = 0; i < 100; i++) {
        pose.apply(gust);
        runtime.beforePhysics(16);
        runtime.afterPhysics();
        expect(Array.from(model.runtimeBones[2].worldMatrix)).not.toEqual(originalHair);
        expect(Array.from(model.runtimeBones[5].worldMatrix)).not.toEqual(originalSkirt);
        pose.restore();
        expect(linked[2].rotationQuaternion.asArray()).toEqual(base.asArray());
        for (const index of [0, 1, 3, 4, 5, 6, 7, 8])
          expect(linked[index].rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
      }
      pose.apply(calm);
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      expect(Array.from(model.runtimeBones[2].worldMatrix)).toEqual(originalHair);
      expect(Array.from(model.runtimeBones[5].worldMatrix)).toEqual(originalSkirt);
      expect(root.scaling.asArray()).toEqual([1, 1, 1]);
    },
  );

  it("shares the angular budget across hair chains so small offsets cannot accumulate into a large bend", () => {
    const { model, metadata, bodies, linked } = setup();
    const pose = createBreezePose(model.runtimeBones, metadata, bodies);
    pose.apply({ pitch: 1, roll: 0, phase: 0 });
    const totalPitch = linked.slice(2, 5).reduce((sum, bone) => sum + 2 * Math.asin(bone.rotationQuaternion.x), 0);
    expect(totalPitch).toBeGreaterThan(0);
    expect(totalPitch).toBeLessThanOrEqual((2 * Math.PI) / 180);
    expect(2 * Math.asin(linked[5].rotationQuaternion.x)).toBeLessThanOrEqual((0.6 * Math.PI) / 180);
    pose.restore();
  });

  it("recognizes English and dynamic-body names while leaving anchors and unrelated bones alone", () => {
    const { model, metadata, bodies, linked } = setup();
    metadata[6].englishName = "Ribbon";
    bodies.push({
      name: "hair collider",
      englishName: "",
      boneIndex: 0,
      physicsMode: PmxObject.RigidBody.PhysicsMode.Physics,
    });
    const pose = createBreezePose(model.runtimeBones, metadata, bodies);
    pose.apply(gust);
    expect(linked[6].rotationQuaternion.w).toBeLessThan(1);
    for (const index of [0, 1, 7, 8]) expect(linked[index].rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    pose.restore();
    metadata[6].englishName = "chair"; // A prop name containing "hair" is not a hair binding.
    const withoutRibbon = createBreezePose(model.runtimeBones, metadata, bodies);
    withoutRibbon.apply(gust);
    expect(linked[6].rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    withoutRibbon.restore();
  });

  it("recognizes generically named hair descendants without moving the fixed anchor or excluded parts", () => {
    const { model, metadata, bodies, linked } = setup(flag.IsRotatable, {
      2: "サイドA_左01",
      3: "後ろA_左02",
      4: "eyelash",
    });
    const pose = createBreezePose(model.runtimeBones, metadata, bodies);
    pose.apply(gust);
    for (const index of [2, 3]) expect(linked[index].rotationQuaternion.w).toBeLessThan(1);
    for (const index of [0, 1, 4, 6, 7, 8]) expect(linked[index].rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    pose.restore();
    for (const bone of linked) expect(bone.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
  });

  it.each([0, flag.IsRotatable | flag.HasAxisLimit, flag.IsRotatable | flag.IsIkEnabled])(
    "skips restricted bones and restores correctly for calm/invalid input (%s)",
    (hairFlag) => {
      const { model, metadata, bodies, linked } = setup(hairFlag);
      const pose = createBreezePose(model.runtimeBones, metadata, bodies);
      pose.apply(gust);
      expect(linked[2].rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
      pose.apply({ ...gust, pitch: NaN });
      for (const bone of linked) expect(bone.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
      expect(() => createBreezePose([], [], []).apply(gust)).not.toThrow();
    },
  );
});
