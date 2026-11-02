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
import { createHeadPose } from "../../../modules/character-visual/adapters/mmd/headPose";

let engine: NullEngine;
const flag = PmxObject.Bone.Flag;
const offset = { pitch: 0.02, yaw: 0.03, roll: 0.01 };

function setup(names = ["首", "頭"], englishNames = ["", ""], headFlag = flag.IsRotatable) {
  engine = new NullEngine();
  const scene = new Scene(engine);
  const root = new Mesh("model", scene);
  const skeleton = new Skeleton("rig", "rig", scene);
  const neck = new Bone(names[0], skeleton, null, Matrix.Translation(0, 10, 0));
  const head = new Bone(names[1], skeleton, neck, Matrix.Translation(0, 2, 0));
  root.skeleton = skeleton;
  const bones = names.map((name, i) => ({
    name,
    englishName: englishNames[i],
    parentBoneIndex: i - 1,
    transformOrder: i,
    flag: i === 1 ? headFlag : flag.IsRotatable,
  }));
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
  return { root, neck, head, runtime, model, pose: createHeadPose(model.runtimeBones, bones) };
}

afterEach(() => engine?.dispose());

describe("MMD speech head pose with the real runtime", () => {
  it.each([flag.IsRotatable, flag.IsRotatable | flag.TransformAfterPhysics])(
    "feeds both solver stages and restores local inputs without cumulative rotation (%s)",
    (headFlag) => {
      const { root, neck, head, runtime, model, pose } = setup(undefined, undefined, headFlag);
      const base = Quaternion.RotationYawPitchRoll(0.1, -0.1, 0.05);
      head.rotationQuaternion = base.clone();
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      const original = Array.from(model.worldTransformMatrices);
      for (let i = 0; i < 100; i++) {
        pose.apply(offset);
        expect(neck.rotationQuaternion.w).toBeLessThan(1);
        runtime.beforePhysics(16);
        runtime.afterPhysics();
        expect(Array.from(model.worldTransformMatrices)).not.toEqual(original);
        pose.restore();
        expect(head.rotationQuaternion.asArray()).toEqual(base.asArray());
        expect(neck.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
      }
      pose.apply({ pitch: 0, yaw: 0, roll: 0 });
      runtime.beforePhysics(16);
      runtime.afterPhysics();
      expect(Array.from(model.worldTransformMatrices)).toEqual(original);
      expect(root.position.asArray()).toEqual([0, 0, 0]);
      expect(root.rotation.asArray()).toEqual([0, 0, 0]);
    },
  );

  it("recognizes English aliases", () => {
    const { neck, head, pose } = setup(["custom1", "custom2"], ["Neck", "Head"]);
    pose.apply(offset);
    expect(neck.rotationQuaternion.w).toBeLessThan(1);
    expect(head.rotationQuaternion.w).toBeLessThan(1);
    pose.restore();
  });

  it("uses full rotation on a head-only rig", () => {
    const { neck, head, pose } = setup(["torso", "head"]);
    pose.apply(offset);
    expect(neck.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    expect(head.rotationQuaternion.asArray()).toEqual(
      Quaternion.RotationYawPitchRoll(offset.yaw, offset.pitch, offset.roll).asArray(),
    );
    pose.restore();
  });

  it("falls back to neck-only rigs without rotating unrelated bones", () => {
    const { neck, head, pose } = setup(["neck", "unknown"]);
    pose.apply(offset);
    expect(neck.rotationQuaternion.asArray()).toEqual(
      Quaternion.RotationYawPitchRoll(offset.yaw, offset.pitch, offset.roll).asArray(),
    );
    expect(head.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
    pose.restore();
  });

  it.each([0, flag.IsRotatable | flag.HasAxisLimit])(
    "degrades safely for restricted/missing bindings (%s)",
    (headFlag) => {
      const { head, model } = setup(["torso", "head"], ["", ""], headFlag);
      createHeadPose(model.runtimeBones, []).apply(offset);
      expect(head.rotationQuaternion.asArray()).toEqual([0, 0, 0, 1]);
      const noHead = createHeadPose([], []);
      expect(() => {
        noHead.apply(offset);
        noHead.restore();
      }).not.toThrow();
    },
  );
});
