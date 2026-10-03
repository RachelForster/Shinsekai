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
import { BreathingMotion, createBreathingPose } from "../../../modules/character-visual/adapters/mmd/breathing";
import { createHeadPose } from "../../../modules/character-visual/adapters/mmd/headPose";

const neutral = { chestPitch: 0, head: { pitch: 0, yaw: 0, roll: 0 } };
const radians = Math.PI / 180;
const flag = PmxObject.Bone.Flag;
let engine: NullEngine;

function setup(names = ["上半身", "上半身2", "首", "頭", "腕"], chestFlag = flag.IsRotatable) {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const root = new Mesh("model", scene);
  const skeleton = new Skeleton("rig", "rig", scene);
  const spine = new Bone(names[0], skeleton, null, Matrix.Translation(0, 10, 0));
  const chest = new Bone(names[1], skeleton, spine, Matrix.Translation(0, 2, 0));
  const neck = new Bone(names[2], skeleton, chest, Matrix.Translation(0, 3, 0));
  const head = new Bone(names[3], skeleton, neck, Matrix.Translation(0, 1.5, 0));
  const arm = new Bone(names[4], skeleton, chest, Matrix.Translation(3, 1, 0));
  const bones = names.map((name, i) => ({
    name,
    englishName: "",
    parentBoneIndex: [-1, 0, 1, 2, 1][i],
    transformOrder: i,
    flag: i === 1 ? chestFlag : flag.IsRotatable,
  }));
  root.skeleton = skeleton;
  root.metadata = {
    isMmdModel: true,
    header: {},
    skeleton,
    bones,
    morphs: [],
    meshes: [root],
    materials: [],
    rigidBodies: [],
    joints: [],
  };
  const runtime = new MmdRuntime(scene, null);
  const model = runtime.createMmdModel(root as MmdSkinnedMesh, { buildPhysics: false, materialProxyConstructor: null });
  return { root, spine, chest, neck, head, arm, bones, model, runtime };
}

afterEach(() => engine?.dispose());

describe("MMD natural breathing", () => {
  it("breathes without speech, gently and continuously through several cycles", () => {
    const motion = new BreathingMotion(0);
    let previous = neutral;
    const samples = Array.from({ length: 1200 }, () => motion.sample(1 / 60));
    for (const sample of samples) {
      expect(Math.abs(sample.chestPitch)).toBeLessThanOrEqual(0.6 * radians);
      expect(Math.abs(sample.head.pitch)).toBeLessThanOrEqual(0.24 * radians);
      expect(Math.abs(sample.head.roll)).toBeLessThanOrEqual(0.04 * radians);
      expect(sample.head.yaw).toBe(0);
      expect(Math.abs(sample.chestPitch - previous.chestPitch)).toBeLessThan(0.0004);
      previous = sample;
    }
    const settled = samples.slice(300);
    expect(Math.min(...settled.map((sample) => sample.chestPitch))).toBeLessThan(-0.008);
    expect(Math.max(...settled.map((sample) => sample.chestPitch))).toBeGreaterThan(-0.0001);
    expect(settled.some((sample) => sample.head.pitch > 0.003)).toBe(true);
  });

  it("keeps the same rhythm at different frame rates and varies between instances", () => {
    const sample = (fps: number, phase = 1) => {
      const motion = new BreathingMotion(phase);
      let result = neutral;
      for (let i = 0; i < fps * 8; i++) result = motion.sample(1 / fps);
      return result;
    };
    const a = sample(30);
    const b = sample(120);
    expect(a.chestPitch).toBeCloseTo(b.chestPitch, 10);
    expect(a.head.pitch).toBeCloseTo(b.head.pitch, 10);
    expect(a.head.roll).toBeCloseTo(b.head.roll, 10);
    expect(sample(60, 2)).not.toEqual(b);
  });

  it("pauses immediately for editing/actions/reduced motion and resumes gently", () => {
    const motion = new BreathingMotion(1);
    for (let i = 0; i < 60; i++) motion.sample(1 / 60);
    expect(motion.sample(0.05, false)).toEqual(neutral);
    const resumed = motion.sample(1 / 60);
    expect(Math.abs(resumed.chestPitch)).toBeLessThan(0.0003);
    expect(Math.abs(resumed.head.pitch)).toBeLessThan(0.0001);
    expect(new BreathingMotion(1).sample(30)).toEqual(new BreathingMotion(1).sample(0.05));
    for (const dt of [NaN, Infinity, -1, 0]) expect(new BreathingMotion(1).sample(dt)).toEqual(neutral);
  });

  it.each([flag.IsRotatable, flag.IsRotatable | flag.TransformAfterPhysics])(
    "moves chest and head through both MMD solver stages without changing the saved pose (%s)",
    (chestFlag) => {
      const { root, spine, chest, neck, head, arm, bones, model, runtime } = setup(undefined, chestFlag);
      const torsoPose = createBreathingPose(model.runtimeBones, bones);
      const headPose = createHeadPose(model.runtimeBones, bones);
      const baseChest = Quaternion.RotationYawPitchRoll(0.15, -0.08, 0.03);
      const baseHead = Quaternion.RotationYawPitchRoll(-0.1, 0.04, 0.02);
      chest.rotationQuaternion = baseChest.clone();
      head.rotationQuaternion = baseHead.clone();
      const chestPosition = chest.position.asArray();
      const armRotation = arm.rotationQuaternion.asArray();
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      const originalChest = Array.from(model.runtimeBones[1].worldMatrix);
      const originalHead = Array.from(model.runtimeBones[3].worldMatrix);
      const breath = new BreathingMotion(1).sample(0.05);
      for (let i = 0; i < 100; i++) {
        torsoPose.apply(breath.chestPitch);
        headPose.apply({ ...breath.head, yaw: 0.02 }); // Speech and breath share one additive head input.
        runtime.beforePhysics(16);
        runtime.afterPhysics();
        expect(Array.from(model.runtimeBones[1].worldMatrix)).not.toEqual(originalChest);
        expect(Array.from(model.runtimeBones[3].worldMatrix)).not.toEqual(originalHead);
        headPose.restore();
        torsoPose.restore();
        expect(chest.rotationQuaternion.asArray()).toEqual(baseChest.asArray());
        expect(head.rotationQuaternion.asArray()).toEqual(baseHead.asArray());
        expect(neck.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
        expect(spine.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
        expect(arm.rotationQuaternion.asArray()).toEqual(armRotation);
        expect(chest.position.asArray()).toEqual(chestPosition);
      }
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      expect(Array.from(model.runtimeBones[1].worldMatrix)).toEqual(originalChest);
      expect(Array.from(model.runtimeBones[3].worldMatrix)).toEqual(originalHead);
      expect(root.position.asArray()).toEqual([0, 0, 0]);
      expect(root.scaling.asArray()).toEqual([1, 1, 1]);
    },
  );

  it("prefers the chest, recognizes English metadata, and falls back to the upper torso", () => {
    const { spine, chest, bones, model } = setup(["custom-spine", "custom-chest", "neck", "head", "arm"]);
    bones[0].englishName = "Upper Body";
    bones[1].englishName = "Upper_Body2";
    const pose = createBreathingPose(model.runtimeBones, bones);
    pose.apply(-0.01);
    expect(chest.rotationQuaternion.x).toBeLessThan(0);
    expect(spine.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    pose.restore();
    bones[1].englishName = "unknown";
    const fallback = createBreathingPose(model.runtimeBones, bones);
    fallback.apply(-0.01);
    expect(spine.rotationQuaternion.x).toBeLessThan(0);
    expect(chest.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    fallback.restore();
  });

  it.each([0, flag.IsRotatable | flag.HasAxisLimit])("skips restricted chest bones (%s)", (chestFlag) => {
    const { chest, model } = setup(["unknown", "chest", "neck", "head", "arm"], chestFlag);
    const pose = createBreathingPose(model.runtimeBones, []);
    pose.apply(-0.01);
    expect(chest.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    pose.restore();
  });

  it("leaves rigs without an upper torso binding untouched, including breast bones", () => {
    const { chest, spine, model } = setup(["胸", "breast", "neck", "head", "arm"]);
    const pose = createBreathingPose(model.runtimeBones, []);
    for (const pitch of [-0.01, NaN, Infinity, 0]) pose.apply(pitch);
    pose.restore();
    expect(chest.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(spine.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(() => createBreathingPose([], []).apply(-0.01)).not.toThrow();
  });
});
