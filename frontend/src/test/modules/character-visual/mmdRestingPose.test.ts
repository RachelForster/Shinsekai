import { afterEach, describe, expect, it } from "vitest";
import { Bone } from "@babylonjs/core/Bones/bone";
import { Skeleton } from "@babylonjs/core/Bones/skeleton";
import { NullEngine } from "@babylonjs/core/Engines/nullEngine";
import { Matrix } from "@babylonjs/core/Maths/math.vector";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { Scene } from "@babylonjs/core/scene";
import { PmxObject } from "babylon-mmd/esm/Loader/Parser/pmxObject";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import type { MmdSkinnedMesh } from "babylon-mmd/esm/Runtime/mmdMesh";
import { createRestingPose } from "../../../modules/character-visual/adapters/mmd/restingPose";
import { loadMotion, MmdMotionPlayer } from "../../../modules/character-visual/adapters/mmd/motion";

let engine: NullEngine;
const flag = PmxObject.Bone.Flag;
function setup(
  scale = 1,
  names = ["頭", "左腕", "左ひじ", "左手首", "右腕", "右ひじ", "右手首"],
  armFlag = flag.IsRotatable,
) {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const root = new Mesh("model", scene);
  const skeleton = new Skeleton("rig", "rig", scene);
  const translate = (x: number, y: number) => Matrix.Translation(x * scale, y * scale, 0);
  const head = new Bone(names[0], skeleton, null, translate(0, 17));
  const left = new Bone(names[1], skeleton, head, translate(1.6, -1));
  const leftElbow = new Bone(names[2], skeleton, left, translate(2.5, 0));
  new Bone(names[3], skeleton, leftElbow, translate(2, 0));
  const right = new Bone(names[4], skeleton, head, translate(-1.6, -1));
  const rightElbow = new Bone(names[5], skeleton, right, translate(-2.5, 0));
  new Bone(names[6], skeleton, rightElbow, translate(-2, 0));
  const bones = names.map((name, i) => ({
    name,
    englishName: "",
    parentBoneIndex: [-1, 0, 1, 2, 0, 4, 5][i],
    transformOrder: i,
    flag: i === 1 ? armFlag : flag.IsRotatable,
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
  const pose = createRestingPose(model.runtimeBones, bones);
  const player = new MmdMotionPlayer(model, pose);
  const sample = (dt = 1 / 60) => {
    player.sample(dt);
    runtime.beforePhysics(dt * 1000);
    runtime.afterPhysics();
  };
  const wrist = (index = 3) => Array.from(model.runtimeBones[index].worldMatrix.slice(12, 15));
  return { scene, root, skeleton, bones, model, pose, player, sample, wrist };
}
afterEach(() => engine?.dispose());

describe("MMD relaxed default arms", () => {
  it.each([1, 10])("lowers both wrists symmetrically with elbow flex and torso clearance at scale %s", (scale) => {
    const { root, skeleton, pose, sample, wrist } = setup(scale);
    const rest = skeleton.bones.map((bone) => bone.getRestMatrix().asArray());
    expect(pose.size).toBe(6);
    sample();
    const left = wrist(),
      right = wrist(6);
    expect(left[1]).toBeLessThan(12 * scale);
    expect(right[1]).toBeCloseTo(left[1], 5);
    expect(left[0]).toBeGreaterThan(2 * scale);
    expect(left[0]).toBeLessThan(3 * scale);
    expect(right[0]).toBeCloseTo(-left[0], 5);
    expect(left[2]).toBeLessThan(-0.3 * scale);
    for (let i = 0; i < 100; i++) sample();
    expect(wrist()).toEqual(left);
    expect(skeleton.bones.map((bone) => bone.getRestMatrix().asArray())).toEqual(rest);
    expect(skeleton.bones[0].rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(root.scaling.asArray()).toEqual([1, 1, 1]);
  });

  it("lets imported poses own the base and crossfades smoothly back to relaxed arms when cleared", async () => {
    const { scene, player, sample, wrist } = setup();
    sample();
    const lowered = wrist()[1];
    const clip = await loadMotion(
      scene,
      "arms.vpd",
      new TextEncoder().encode("Vocaloid Pose Data file\n\nmodel.osm;\n1;\nBone0{左腕\n0,0,0;\n0,0,0,1;\n}\n").buffer,
    );
    player.set(player.bind(clip), "play", true);
    sample(0.1);
    expect(wrist()[1]).toBeGreaterThan(lowered);
    expect(wrist()[1]).toBeLessThan(16);
    sample(0.3);
    expect(wrist()[1]).toBeCloseTo(16, 5);
    player.set(null, "play", true);
    sample(0.1);
    expect(wrist()[1]).toBeGreaterThan(lowered);
    expect(wrist()[1]).toBeLessThan(16);
    sample(0.3);
    expect(wrist()[1]).toBeCloseTo(lowered, 5);
  });

  it("recognizes English metadata and safely skips incomplete pairs", () => {
    const { bones, model } = setup(1, ["head", "custom-A", "custom-B", "custom-C", "custom-D", "custom-E", "custom-F"]);
    ["head", "Arm_L", "Elbow_L", "Wrist_L", "Arm_R", "Elbow_R", "Wrist_R"].forEach(
      (name, i) => (bones[i].englishName = name),
    );
    expect(createRestingPose(model.runtimeBones, bones).size).toBe(6);
    bones[6].englishName = "unknown";
    expect(createRestingPose(model.runtimeBones, bones).size).toBe(0);
  });

  it.each([0, flag.IsRotatable | flag.HasAxisLimit])(
    "leaves incomplete or restricted arm pairs unchanged (%s)",
    (armFlag) => {
      const { pose, sample, wrist } = setup(1, undefined, armFlag);
      expect(pose.size).toBe(0);
      sample();
      expect(wrist()[1]).toBe(16);
      expect(wrist(6)[1]).toBe(16);
    },
  );
});
